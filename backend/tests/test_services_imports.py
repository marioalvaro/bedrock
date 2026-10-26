"""Statement imports: template, dry run, confirmed import, delete (FR-DATA-15), on a followed AAPL
(recorded fixtures, no network)."""

import io
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.mapping.config import load_canonical_items
from bedrock.models.company import Company
from bedrock.models.imported_fact import ImportedFact
from bedrock.models.statement_import import StatementImport
from bedrock.services.errors import ImportNotFound, InvalidStatementImport
from bedrock.services.imports import (
    ImportPreview,
    confirm_import,
    delete_import,
    import_template,
    list_imports,
    preview_import,
)
from bedrock.services.refresh import refresh_company
from bedrock.services.statements import build_statements, fiscal_periods

from .import_data import FY2006, Q1_2006, Q2_2006, Q3_2006, filled, save, statement_rows, workbook
from .seed import fake_sources, follow

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


@pytest.fixture
def aapl(db_session: Session) -> Iterator[Company]:
    sources = fake_sources()
    company = follow(db_session, sources.edgar, "AAPL")
    refresh_company(db_session, sources, "AAPL", NOW)
    yield company


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _template(session: Session, company: Company, prefill: bool = True, fmt: str = "xlsx") -> bytes:
    return import_template(session, company, fmt, "millions", prefill)  # type: ignore[arg-type]


def _grid(session: Session, company: Company) -> dict[tuple[str, str, str], Any]:
    """Value and provenance of every annual and quarterly cell, by (statement, code, key)."""
    out: dict[tuple[str, str, str], Any] = {}
    for statement in ("IS", "BS", "CF"):
        for freq in ("annual", "quarterly"):
            table = build_statements(session, company, statement, freq)  # type: ignore[arg-type]
            for row in table.rows:
                for period, value, provenance in zip(
                    table.periods, row.values, row.provenance, strict=True
                ):
                    out[(statement, row.code, period.key)] = (value, provenance)
    return out


RESIDUALS = {i.code for i in load_canonical_items() if i.residual}

# Cells the SEC data leaves empty (tests/golden/statements/AAPL.yaml `expected_missing`)
EMPTY_CELLS = [
    ("IS", "interest_expense", "FY2008"),
    ("BS", "ppe_net", "FY2008"),
    ("CF", "buybacks", "FY2008"),
]


def test_the_prefilled_template_imports_as_all_unchanged(
    db_session: Session, aapl: Company
) -> None:
    preview = preview_import(db_session, aapl, _template(db_session, aapl), "aapl.xlsx", None)

    assert preview.fills == [] and preview.ignored == []
    assert preview.unchanged > 1_000
    assert [w for w in preview.warnings if w.sheet is not None] == []
    assert _count(db_session, StatementImport) == 0


def test_typing_into_three_empty_cells_fills_exactly_those(
    db_session: Session, aapl: Company
) -> None:
    before = _grid(db_session, aapl)
    book = load_workbook(io.BytesIO(_template(db_session, aapl)))
    for sheet, code, period in EMPTY_CELLS:
        filled(book, sheet, code, period, 12)

    preview = preview_import(db_session, aapl, save(book), "aapl.xlsx", None)
    assert {(f.statement, f.code, f.period_key) for f in preview.fills} == set(EMPTY_CELLS)
    assert all(f.previous is None for f in preview.fills)
    assert preview.ignored == []
    assert _grid(db_session, aapl) == before  # a dry run changes nothing

    result = confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    assert result.import_id is not None
    after = _grid(db_session, aapl)
    changed = {key for key in after if after[key] != before[key]}
    assert {key for key in changed if after[key][1] == "imported"} == set(EMPTY_CELLS)
    assert after[("IS", "interest_expense", "FY2008")][0] == 12_000_000
    # a non-empty cell changes only when it is a residual absorbing the new line
    for key in changed:
        assert before[key][0] is None or key[1] in RESIDUALS, key


def test_a_typed_value_over_an_sec_cell_is_ignored_and_not_stored(
    db_session: Session, aapl: Company
) -> None:
    book = load_workbook(io.BytesIO(_template(db_session, aapl)))
    filled(book, "IS", "revenue", "FY2024", 1)

    preview = preview_import(db_session, aapl, save(book), "aapl.xlsx", None)
    result = confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    assert preview.fills == []
    (ignored,) = preview.ignored
    assert (ignored.code, ignored.period_key, ignored.imported_value) == (
        "revenue",
        "FY2024",
        1_000_000,
    )
    assert ignored.existing_value > 391_000_000_000 and ignored.reason == "sec"
    assert result.import_id is None  # nothing to store
    assert _count(db_session, StatementImport) == 0 and _count(db_session, ImportedFact) == 0


def test_confirming_stores_one_import_with_its_facts_and_lists_it(
    db_session: Session, aapl: Company
) -> None:
    book = load_workbook(io.BytesIO(_template(db_session, aapl)))
    for sheet, code, period in EMPTY_CELLS:
        filled(book, sheet, code, period, 12)

    confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    (listed,) = list_imports(db_session, aapl)
    assert (listed.filename, listed.format, listed.scale, listed.cells) == (
        "aapl.xlsx",
        "xlsx",
        "millions",
        3,
    )
    assert listed.imported_at == datetime(2026, 10, 26, 9, 0)
    assert _count(db_session, ImportedFact) == 3


def test_deleting_an_import_removes_its_facts_and_the_cells_go_back_to_empty(
    db_session: Session, aapl: Company
) -> None:
    before = _grid(db_session, aapl)
    book = load_workbook(io.BytesIO(_template(db_session, aapl)))
    filled(book, "IS", "interest_expense", "FY2008", 12)
    result = confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)
    assert result.import_id is not None

    delete_import(db_session, aapl, result.import_id)

    assert _count(db_session, StatementImport) == 0 and _count(db_session, ImportedFact) == 0
    assert _grid(db_session, aapl) == before


def test_deleting_an_unknown_or_foreign_import_is_not_found(
    db_session: Session, aapl: Company
) -> None:
    with pytest.raises(ImportNotFound):
        delete_import(db_session, aapl, 999)


def test_a_second_import_of_the_same_cell_replaces_the_first_and_keeps_it_as_a_vintage(
    db_session: Session, aapl: Company
) -> None:
    for value, at in ((12, NOW), (13, NOW + timedelta(hours=1))):
        book = load_workbook(io.BytesIO(_template(db_session, aapl)))
        filled(book, "IS", "interest_expense", "FY2008", value)
        confirm_import(db_session, aapl, save(book), f"v{value}.xlsx", None, at)

    assert _grid(db_session, aapl)[("IS", "interest_expense", "FY2008")][0] == 13_000_000
    assert _count(db_session, ImportedFact) == 2


def test_an_error_names_its_sheet_row_and_column_and_nothing_is_stored(
    db_session: Session, aapl: Company
) -> None:
    book = load_workbook(io.BytesIO(_template(db_session, aapl)))
    filled(book, "IS", "interest_expense", "FY2008", "abc")  # type: ignore[arg-type]

    with pytest.raises(InvalidStatementImport) as raised:
        confirm_import(db_session, aapl, save(book), "aapl.xlsx", None, NOW)

    (issue,) = raised.value.issues
    assert issue.sheet == "IS" and issue.row is not None and issue.column is not None
    assert _count(db_session, StatementImport) == 0


def test_a_period_that_is_not_in_the_calendar_is_an_error(
    db_session: Session, aapl: Company
) -> None:
    future = (2031, "FY", FY2006[2].replace(year=2030), FY2006[3].replace(year=2031))
    content = workbook({"IS": statement_rows([future], {"revenue": [1]})})

    with pytest.raises(InvalidStatementImport) as raised:
        preview_import(db_session, aapl, content, "aapl.xlsx", None)

    assert "FY2031" in raised.value.issues[0].message


def test_a_year_before_the_first_sec_year_joins_the_statements(
    db_session: Session, aapl: Company
) -> None:
    assert (2006, "FY") not in fiscal_periods(db_session, aapl)
    content = workbook(
        {
            "IS": statement_rows(
                [FY2006, Q1_2006, Q2_2006, Q3_2006],
                {"revenue": [19315, 4359, 4370, 4400], "net_income": [2000, None, None, None]},
            )
        },
        "millions",
    )

    preview = preview_import(db_session, aapl, content, "old.xlsx", None)
    confirm_import(db_session, aapl, content, "old.xlsx", None, NOW)

    assert {(f.code, f.period_key) for f in preview.fills} == {
        ("revenue", "FY2006"),
        ("revenue", "FY2006Q1"),
        ("revenue", "FY2006Q2"),
        ("revenue", "FY2006Q3"),
        ("net_income", "FY2006"),
    }
    assert {(2006, "FY"), (2006, "Q1"), (2006, "Q4")} <= fiscal_periods(db_session, aapl)
    table = build_statements(db_session, aapl, "IS", "annual")
    revenue = next(r for r in table.rows if r.code == "revenue")
    at = [p.key for p in table.periods].index("FY2006")
    assert (revenue.values[at], revenue.provenance[at]) == (19_315_000_000, "imported")


def test_a_balance_sheet_that_does_not_balance_is_a_warning_not_an_error(
    db_session: Session, aapl: Company
) -> None:
    year = (2005, "FY", date(2004, 9, 26), date(2005, 9, 24))
    content = workbook(
        {
            "IS": statement_rows([year], {"revenue": [13931]}),  # gives the year its dates
            "BS": statement_rows(
                [year], {"total_assets": [100], "total_liabilities": [40], "total_equity": [50]}
            ),
        }
    )

    preview = preview_import(db_session, aapl, content, "bs.xlsx", None)

    assert len(preview.fills) == 4
    assert any("balance" in w.message.lower() and "FY2005" in w.message for w in preview.warnings)


def test_a_balance_sheet_alone_cannot_open_a_new_year(db_session: Session, aapl: Company) -> None:
    year = (2005, "FY", None, date(2005, 9, 24))
    content = workbook({"BS": statement_rows([year], {"total_assets": [100]})})

    preview = preview_import(db_session, aapl, content, "bs.xlsx", None)

    assert preview.fills == []
    assert any("FY2005" in w.message and "income" in w.message for w in preview.warnings)


def test_a_manual_scale_argument_is_used_when_the_file_has_none(
    db_session: Session, aapl: Company
) -> None:
    book = load_workbook(io.BytesIO(_template(db_session, aapl, prefill=False)))
    filled(book, "IS", "interest_expense", "FY2008", 12)
    book["Instructions"]["A1"].value = "notes"  # the scale row is gone

    preview = preview_import(db_session, aapl, save(book), "aapl.xlsx", "thousands")

    assert preview.fills[0].value == 12_000
    assert isinstance(preview, ImportPreview)
