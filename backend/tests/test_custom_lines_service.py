"""Custom lines through the import service on a followed AAPL (FR-DATA-16): dry run, confirm,
the statements, the guard, delete (recorded fixtures, no network)."""

import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.models.custom_line import CustomLine
from bedrock.models.imported_fact import ImportedFact
from bedrock.models.statement_import import StatementImport
from bedrock.repositories import companies as companies_repo
from bedrock.services.companies import add_manual_company
from bedrock.services.errors import CellNotFound, InvalidStatementImport
from bedrock.services.imports import (
    confirm_import,
    delete_import,
    import_template,
    preview_import,
)
from bedrock.services.statements import build_statements, cell_detail
from bedrock.statements.custom_lines import BUILT_FROM_CHILDREN

from .import_data import (
    FY2006,
    Q1_2006,
    Q2_2006,
    Q3_2006,
    add_line,
    mark_complete,
    save,
    statement_rows,
    workbook,
)

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)


@pytest.fixture
def aapl_db(seed_db: Callable[..., None]) -> None:
    seed_db("AAPL")


@pytest.fixture
def aapl(aapl_db: None, db_session: Session) -> Company:
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    return company


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _book(session: Session, company: Company) -> Any:
    return load_workbook(io.BytesIO(import_template(session, company, "xlsx", "millions", True)))


def _grid(session: Session, company: Company) -> dict[tuple[str, str, str], Any]:
    out: dict[tuple[str, str, str], Any] = {}
    for statement in ("IS", "BS", "CF"):
        for freq in ("annual", "quarterly"):
            table = build_statements(session, company, statement, freq)  # type: ignore[arg-type]
            for row in table.rows:
                for period, value, provenance in zip(
                    table.periods, row.values, row.provenance, strict=True
                ):
                    out[(statement, row.code, period.key)] = (value, provenance, row.custom)
    return out


def _canonical(grid: dict[tuple[str, str, str], Any]) -> dict[tuple[str, str, str], Any]:
    return {k: v for k, v in grid.items() if not v[2]}


def _cost_breakdown(book: Any, flag: bool = False, products: float = 1000, services: float = 2000):
    add_line(book, "IS", "cost_of_revenue", "Products", {"FY2024": products})
    add_line(book, "IS", "cost_of_revenue", "Services", {"FY2024": services})
    if flag:
        mark_complete(book, "IS", "cost_of_revenue")


def _interest_breakdown(book: Any, flag: bool = True) -> None:
    """Interest expense is empty in AAPL's FY2008 (tests/golden/statements/AAPL.yaml)."""
    add_line(book, "IS", "interest_expense", "Notes", {"FY2008": 3})
    add_line(book, "IS", "interest_expense", "Loans", {"FY2008": 4})
    if flag:
        mark_complete(book, "IS", "interest_expense")


def test_a_dry_run_lists_the_new_lines_and_their_cells_and_stores_nothing(
    db_session: Session, aapl: Company
) -> None:
    book = _book(db_session, aapl)
    _cost_breakdown(book)

    preview = preview_import(db_session, aapl, save(book), "aapl.xlsx", None)

    assert [(c.statement, c.code, c.period_key, c.value) for c in preview.fills] == [
        ("IS", "custom:products", "FY2024", 1_000_000_000),
        ("IS", "custom:services", "FY2024", 2_000_000_000),
    ]
    assert [
        (ln.code, ln.label, ln.parent, ln.parent_label, ln.statement) for ln in preview.lines
    ] == [
        ("custom:products", "Products", "cost_of_revenue", "Cost of revenue", "IS"),
        ("custom:services", "Services", "cost_of_revenue", "Cost of revenue", "IS"),
    ]
    assert preview.built == []
    assert [_count(db_session, m) for m in (CustomLine, ImportedFact, StatementImport)] == [0, 0, 0]


def test_confirming_stores_the_lines_and_the_statement_shows_them_and_the_other_row(
    db_session: Session, aapl: Company
) -> None:
    book = _book(db_session, aapl)
    _cost_breakdown(book)

    result = confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    assert result.import_id is not None and _count(db_session, CustomLine) == 2
    table = build_statements(db_session, aapl, "IS", "annual")
    codes = [r.code for r in table.rows]
    at = codes.index("cost_of_revenue")
    assert codes[at + 1 : at + 4] == ["custom:products", "custom:services", "other:cost_of_revenue"]
    values = {r.code: r.values[[p.key for p in table.periods].index("FY2024")] for r in table.rows}
    assert (values["custom:products"], values["custom:services"]) == (1_000_000_000, 2_000_000_000)
    assert values["other:cost_of_revenue"] == values["cost_of_revenue"] - 3_000_000_000
    custom = next(r for r in table.rows if r.code == "custom:products")
    assert (custom.custom, custom.parent, custom.depth, custom.adjustable) == (
        True,
        "cost_of_revenue",
        1,
        False,
    )


def test_custom_lines_under_a_reported_parent_change_no_canonical_cell(
    db_session: Session, aapl: Company
) -> None:
    before = _grid(db_session, aapl)
    book = _book(db_session, aapl)
    _cost_breakdown(book)
    add_line(book, "BS", "cash", "Money market", {"FY2024": 5000})
    confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    after = _grid(db_session, aapl)

    assert _canonical(after) == _canonical(before)
    assert any(v[2] for v in after.values())


def test_a_complete_breakdown_fills_an_empty_parent_and_only_what_derives_from_it(
    db_session: Session, aapl: Company
) -> None:
    before = _grid(db_session, aapl)
    assert before[("IS", "interest_expense", "FY2008")][0] is None
    book = _book(db_session, aapl)
    _interest_breakdown(book)

    preview = preview_import(db_session, aapl, save(book), "aapl.xlsx", None)
    confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)
    after = _grid(db_session, aapl)

    (built,) = preview.built
    assert (built.statement, built.code, built.period_key, built.value) == (
        "IS",
        "interest_expense",
        "FY2008",
        7_000_000,
    )
    assert after[("IS", "interest_expense", "FY2008")][:2] == (7_000_000, "derived")
    changed = {k for k, v in _canonical(after).items() if v != _canonical(before)[k]}
    assert ("IS", "interest_expense", "FY2008") in changed
    assert {k[2] for k in changed} <= {"FY2008", "FY2008Q4"}  # nothing outside the year
    for key in changed:  # what moved is the parent, or a cell that now derives from it
        assert before[key][0] is None or after[key][1] != "reported", key


def test_the_built_parents_cell_detail_names_its_children(
    db_session: Session, aapl: Company
) -> None:
    book = _book(db_session, aapl)
    _interest_breakdown(book)
    confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    detail = cell_detail(db_session, aapl, "interest_expense", 2008, "FY")

    assert detail.provenance == "derived"
    assert detail.derivation is not None
    assert detail.derivation.formula == BUILT_FROM_CHILDREN
    assert [(i.code, i.value) for i in detail.derivation.inputs] == [
        ("custom:notes", 3_000_000),
        ("custom:loans", 4_000_000),
    ]


def test_a_custom_cells_detail_says_it_was_imported(db_session: Session, aapl: Company) -> None:
    book = _book(db_session, aapl)
    _cost_breakdown(book)
    result = confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    detail = cell_detail(db_session, aapl, "custom:products", 2024, "FY")

    assert detail.provenance == "imported"
    assert detail.filing is not None
    assert (detail.filing.form, detail.filing.accession_no) == (
        "import",
        f"import:{result.import_id}",
    )
    assert [v.accession_no for v in detail.vintages] == [f"import:{result.import_id}"]


def test_a_breakdown_marked_complete_that_does_not_foot_is_a_warning(
    db_session: Session, aapl: Company
) -> None:
    book = _book(db_session, aapl)
    _cost_breakdown(book, flag=True)  # 1.0B + 2.0B against AAPL's 2024 cost of revenue

    preview = preview_import(db_session, aapl, save(book), "aapl.xlsx", None)

    texts = [w.message for w in preview.warnings]
    assert any("Cost of revenue FY2024" in t and "adds up to" in t for t in texts), texts


def test_marking_a_listed_breakdown_complete_later_stores_the_flag(
    db_session: Session, aapl: Company
) -> None:
    first = _book(db_session, aapl)
    _interest_breakdown(first, flag=False)
    confirm_import(db_session, aapl, save(first), "a.xlsx", None, NOW)
    assert _grid(db_session, aapl)[("IS", "interest_expense", "FY2008")][0] is None

    second = _book(db_session, aapl)
    _interest_breakdown(second, flag=True)
    result = confirm_import(db_session, aapl, save(second), "b.xlsx", None, LATER)

    assert result.import_id is not None and result.preview.fills == []
    assert _grid(db_session, aapl)[("IS", "interest_expense", "FY2008")][:2] == (
        7_000_000,
        "derived",
    )


def test_the_same_file_again_changes_nothing(db_session: Session, aapl: Company) -> None:
    book = _book(db_session, aapl)
    _interest_breakdown(book)
    confirm_import(db_session, aapl, save(book), "a.xlsx", None, NOW)

    again = confirm_import(db_session, aapl, save(book), "a.xlsx", None, LATER)

    assert again.import_id is None
    assert again.preview.fills == [] and again.preview.lines == []
    assert _count(db_session, StatementImport) == 1


def test_deleting_the_import_removes_the_lines_and_restores_the_statements(
    db_session: Session, aapl: Company
) -> None:
    before = _grid(db_session, aapl)
    book = _book(db_session, aapl)
    _interest_breakdown(book)
    _cost_breakdown(book)
    result = confirm_import(db_session, aapl, save(book), "a.xlsx", None, NOW)
    assert result.import_id is not None

    delete_import(db_session, aapl, result.import_id)

    assert _count(db_session, CustomLine) == 0
    assert _grid(db_session, aapl) == before


def test_a_template_taken_after_an_import_imports_as_unchanged(
    db_session: Session, aapl: Company
) -> None:
    book = _book(db_session, aapl)
    _interest_breakdown(book)
    confirm_import(db_session, aapl, save(book), "a.xlsx", None, NOW)

    preview = preview_import(
        db_session,
        aapl,
        import_template(db_session, aapl, "xlsx", "millions", True),
        "t.xlsx",
        None,
    )

    assert preview.fills == [] and preview.ignored == [] and preview.lines == []


def test_a_value_typed_for_a_line_listed_under_two_parents_is_one_error(
    db_session: Session, aapl: Company
) -> None:
    book = _book(db_session, aapl)
    add_line(book, "IS", "cost_of_revenue", "Other", {"FY2024": 1})
    add_line(book, "IS", "research_development", "Other", {"FY2024": 1})

    with pytest.raises(InvalidStatementImport) as raised:
        preview_import(db_session, aapl, save(book), "a.xlsx", None)

    assert "custom:other" in raised.value.issues[0].message


def test_a_manual_company_builds_its_cost_of_revenue_from_quarterly_lines(
    db_session: Session,
) -> None:
    company = add_manual_company(db_session, "ACME", "Acme", 9, None).company
    periods = [FY2006, Q1_2006, Q2_2006, Q3_2006]
    rows = statement_rows(
        periods,
        [
            ["revenue", None, None, None, None, 100, 25, 25, 25],
            ["cost_of_revenue", None, None, None, True, None, None, None, None],
            [None, "Products", "cost_of_revenue", None, None, 40, 9, 10, 11],
            [None, "Services", "cost_of_revenue", None, None, 20, 4, 5, 6],
        ],
    )

    confirm_import(db_session, company, workbook({"IS": rows}), "acme.xlsx", None, NOW)

    table = build_statements(db_session, company, "IS", "quarterly")
    keys = [p.key for p in table.periods]
    cells = {r.code: dict(zip(keys, r.values, strict=True)) for r in table.rows}
    assert cells["custom:products"]["FY2006Q4"] == 10_000_000  # 40 - (9 + 10 + 11), millions
    assert [cells["cost_of_revenue"][f"FY2006Q{n}"] for n in (1, 2, 3, 4)] == [
        13_000_000,
        15_000_000,
        17_000_000,
        15_000_000,
    ]
    annual = build_statements(db_session, company, "IS", "annual")
    assert next(r for r in annual.rows if r.code == "cost_of_revenue").values == [60_000_000]
    assert next(r for r in annual.rows if r.code == "gross_profit").values == [40_000_000]


def test_the_other_row_has_no_cell_detail(db_session: Session, aapl: Company) -> None:
    book = _book(db_session, aapl)
    _cost_breakdown(book)
    confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    with pytest.raises(CellNotFound):
        cell_detail(db_session, aapl, "other:cost_of_revenue", 2024, "FY")
