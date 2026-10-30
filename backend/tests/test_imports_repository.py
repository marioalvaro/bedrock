"""Statement imports and their facts: storage, newest first, scoping, delete (FR-DATA-15)."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.models.imported_fact import ImportedFact
from bedrock.repositories import imports as repo

from .seed import fake_sources, follow

NOW = datetime(2026, 10, 26, 9, 0)
FY2006 = (date(2005, 9, 25), date(2006, 9, 30))


@pytest.fixture
def company(db_session: Session) -> Company:
    return follow(db_session, fake_sources().edgar, "AAPL")


def _fact(
    code: str, value: str, *, start: date | None = FY2006[0], period: str = "FY"
) -> repo.NewFact:
    return repo.NewFact(code, 2006, period, start, FY2006[1], Decimal(value))


def _add(session: Session, company: Company, name: str, at: datetime, *facts: repo.NewFact) -> int:
    row = repo.add_import(session, company.id, name, "xlsx", "millions", at, None, list(facts))
    session.commit()
    return row.id


def test_add_import_stores_the_import_and_its_facts(db_session: Session, company: Company) -> None:
    import_id = _add(
        db_session,
        company,
        "a.xlsx",
        NOW,
        _fact("revenue", "19315000000"),
        _fact("cash", "10110000000", start=None),
    )

    stored = repo.get(db_session, company.id, import_id)
    assert stored is not None
    assert (stored.filename, stored.format, stored.scale, stored.cells) == (
        "a.xlsx",
        "xlsx",
        "millions",
        2,
    )
    facts = repo.list_facts(db_session, company.id)
    assert [(f.line_code, f.period_start) for f in facts] == [
        ("cash", None),
        ("revenue", FY2006[0]),
    ]


def test_facts_come_back_without_numeric_padding(db_session: Session, company: Company) -> None:
    _add(
        db_session,
        company,
        "a.xlsx",
        NOW,
        _fact("revenue", "19315000000"),
        _fact("eps_basic", "1.55"),
    )
    db_session.expire_all()

    values = {f.line_code: f.value for f in repo.list_facts(db_session, company.id)}

    assert values == {"revenue": Decimal("19315000000"), "eps_basic": Decimal("1.55")}
    assert str(values["revenue"]) == "19315000000"
    assert repo.list_facts(db_session, company.id)[0] is not None  # a second read stays clean


def test_imports_list_newest_first(db_session: Session, company: Company) -> None:
    older = _add(db_session, company, "old.xlsx", NOW, _fact("revenue", "1"))
    newer = _add(db_session, company, "new.csv", NOW + timedelta(hours=1), _fact("revenue", "2"))

    assert [i.id for i in repo.list_imports(db_session, company.id)] == [newer, older]
    assert repo.list_imports(db_session, company.id + 1) == []


def test_an_import_of_another_company_is_not_found(db_session: Session, company: Company) -> None:
    import_id = _add(db_session, company, "a.xlsx", NOW, _fact("revenue", "1"))

    assert repo.get(db_session, company.id + 1, import_id) is None
    assert repo.get(db_session, company.id, import_id + 1) is None
    assert repo.list_facts(db_session, company.id + 1) == []


def test_delete_import_removes_its_facts_and_keeps_the_others(
    db_session: Session, company: Company
) -> None:
    first = _add(db_session, company, "a.xlsx", NOW, _fact("revenue", "1"), _fact("cogs", "2"))
    _add(db_session, company, "b.xlsx", NOW + timedelta(hours=1), _fact("revenue", "3"))

    stored = repo.get(db_session, company.id, first)
    assert stored is not None
    repo.delete_import(db_session, stored)
    db_session.commit()

    assert [i.filename for i in repo.list_imports(db_session, company.id)] == ["b.xlsx"]
    remaining = db_session.execute(select(func.count()).select_from(ImportedFact)).scalar_one()
    assert remaining == 1


def test_the_same_cell_in_two_imports_keeps_both_vintages(
    db_session: Session, company: Company
) -> None:
    _add(db_session, company, "a.xlsx", NOW, _fact("revenue", "1"))
    _add(db_session, company, "b.xlsx", NOW + timedelta(hours=1), _fact("revenue", "2"))

    facts = repo.list_facts(db_session, company.id)

    assert [(f.import_id, f.value) for f in facts] == [
        (facts[0].import_id, 1),
        (facts[1].import_id, 2),
    ]
    assert facts[0].import_id < facts[1].import_id


# -- custom lines (FR-DATA-16) ------------------------------------------------------------------


def _line(
    code: str, parent: str = "cost_of_revenue", *, complete: bool = False, label: str = ""
) -> repo.NewLine:
    return repo.NewLine(
        code, label or code.removeprefix("custom:").title(), "IS", parent, "flow", "USD", complete
    )


def _add_with(
    session: Session,
    company: Company,
    name: str,
    at: datetime,
    facts: list[repo.NewFact],
    lines: list[repo.NewLine],
) -> int:
    row = repo.add_import(session, company.id, name, "xlsx", "millions", at, None, facts, lines)
    session.commit()
    return row.id


def test_add_import_stores_new_custom_lines_in_the_order_given(
    db_session: Session, company: Company
) -> None:
    _add_with(
        db_session,
        company,
        "a.xlsx",
        NOW,
        [_fact("custom:products", "5"), _fact("custom:services", "6"), _fact("custom:rd", "1")],
        [
            _line("custom:products", complete=True),
            _line("custom:services", complete=True),
            _line("custom:rd", "research_development"),
        ],
    )

    lines = repo.list_lines(db_session, company.id)
    assert {(ln.code, ln.parent_code, ln.display_order) for ln in lines} == {
        ("custom:products", "cost_of_revenue", 0),
        ("custom:services", "cost_of_revenue", 1),
        ("custom:rd", "research_development", 0),
    }
    under = [ln.code for ln in lines if ln.parent_code == "cost_of_revenue"]
    assert under == ["custom:products", "custom:services"]
    first = lines[0]
    assert (first.label, first.statement, first.kind, first.unit, first.children_complete) == (
        "Products",
        "IS",
        "flow",
        "USD",
        True,
    )


def test_a_later_import_adds_lines_after_the_ones_stored(
    db_session: Session, company: Company
) -> None:
    _add_with(
        db_session,
        company,
        "a.xlsx",
        NOW,
        [_fact("custom:products", "5")],
        [_line("custom:products")],
    )

    _add_with(
        db_session,
        company,
        "b.xlsx",
        NOW + timedelta(days=1),
        [_fact("custom:services", "6")],
        [_line("custom:services")],
    )

    assert [(ln.code, ln.display_order) for ln in repo.list_lines(db_session, company.id)] == [
        ("custom:products", 0),
        ("custom:services", 1),
    ]


def test_listing_a_line_again_updates_its_label_and_flag_only(
    db_session: Session, company: Company
) -> None:
    _add_with(
        db_session,
        company,
        "a.xlsx",
        NOW,
        [_fact("custom:products", "5")],
        [_line("custom:products")],
    )

    _add_with(
        db_session,
        company,
        "b.xlsx",
        NOW + timedelta(days=1),
        [_fact("custom:products", "6")],
        [_line("custom:products", complete=True, label="Product lines")],
    )

    (line,) = repo.list_lines(db_session, company.id)
    assert (line.label, line.children_complete, line.display_order) == ("Product lines", True, 0)


def test_custom_lines_belong_to_their_company(db_session: Session, company: Company) -> None:
    other = follow(db_session, fake_sources().edgar, "MSFT")
    _add_with(
        db_session,
        company,
        "a.xlsx",
        NOW,
        [_fact("custom:products", "5")],
        [_line("custom:products")],
    )

    assert repo.list_lines(db_session, other.id) == []


def test_deleting_an_import_removes_the_lines_left_without_values(
    db_session: Session, company: Company
) -> None:
    import_id = _add_with(
        db_session,
        company,
        "a.xlsx",
        NOW,
        [_fact("custom:products", "5"), _fact("custom:phones", "2"), _fact("revenue", "9")],
        [_line("custom:products"), _line("custom:phones", "custom:products")],
    )
    row = repo.get(db_session, company.id, import_id)
    assert row is not None

    repo.delete_import(db_session, row)
    db_session.commit()

    assert repo.list_lines(db_session, company.id) == []


def test_a_line_with_values_in_another_import_stays(db_session: Session, company: Company) -> None:
    first = _add_with(
        db_session,
        company,
        "a.xlsx",
        NOW,
        [_fact("custom:products", "5")],
        [_line("custom:products")],
    )
    _add_with(
        db_session,
        company,
        "b.xlsx",
        NOW + timedelta(days=1),
        [_fact("custom:products", "6")],
        [_line("custom:products")],
    )
    row = repo.get(db_session, company.id, first)
    assert row is not None

    repo.delete_import(db_session, row)
    db_session.commit()

    assert [ln.code for ln in repo.list_lines(db_session, company.id)] == ["custom:products"]


def test_a_line_without_values_stays_while_a_line_under_it_has_some(
    db_session: Session, company: Company
) -> None:
    first = _add_with(
        db_session,
        company,
        "a.xlsx",
        NOW,
        [_fact("custom:products", "5")],
        [_line("custom:products")],
    )
    _add_with(
        db_session,
        company,
        "b.xlsx",
        NOW + timedelta(days=1),
        [_fact("custom:phones", "2")],
        [_line("custom:phones", "custom:products")],
    )
    row = repo.get(db_session, company.id, first)
    assert row is not None

    repo.delete_import(db_session, row)
    db_session.commit()

    assert [ln.code for ln in repo.list_lines(db_session, company.id)] == [
        "custom:products",
        "custom:phones",
    ]
