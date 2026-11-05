"""Segment and KPI series: CRUD, values, grid and import (FR-DATA-11)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.models.segment_series import SegmentSeries
from bedrock.models.segment_value import SegmentValue
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import segments as repo
from bedrock.services.errors import InvalidImport, InvalidSeries, SeriesNotFound
from bedrock.services.segments import (
    SeriesInput,
    ValueInput,
    create_series,
    delete_series,
    import_segments,
    segment_grid,
    set_values,
    update_series,
)

from .seed import fake_sources, follow

NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)

IPHONE = SeriesInput("business", "iPhone", "revenue", "USD")


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


def _rejects(inp: SeriesInput, session: Session, company: Company) -> None:
    with pytest.raises(InvalidSeries):
        create_series(session, company, inp, NOW)
    assert _count(session, SegmentSeries) == 0


def test_create_strips_the_name_and_numbers_from_one(db_session: Session, aapl: Company) -> None:
    first = create_series(
        db_session, aapl, SeriesInput("business", "  iPhone  ", "revenue", "USD"), NOW
    )
    second = create_series(db_session, aapl, SeriesInput("geo", "Europe", "revenue", "USD"), NOW)

    assert (first.name, first.display_order, second.display_order) == ("iPhone", 1, 2)
    assert first.created_at == datetime(2026, 10, 8, 14, 30)  # naive UTC


@pytest.mark.parametrize(
    "inp",
    [
        SeriesInput("sector", "X", "revenue", "USD"),
        SeriesInput("business", "X", "revenue", "EUR"),
        SeriesInput("business", "   ", "revenue", "USD"),
        SeriesInput("business", "x" * 81, "revenue", "USD"),
        SeriesInput("business", "X", "gross_profit", "USD"),
        SeriesInput("geo", "X", "revenue", "pct"),
        SeriesInput("kpi", "Subs", "Bad Code", "count"),
        SeriesInput("kpi", "Subs", "1subs", "count"),
        SeriesInput("kpi", "Subs", "a" * 41, "count"),
    ],
)
def test_create_rejects_invalid_input(inp: SeriesInput, db_session: Session, aapl: Company) -> None:
    _rejects(inp, db_session, aapl)


def test_create_rejects_a_duplicate_dimension_name_metric(
    db_session: Session, aapl: Company
) -> None:
    create_series(db_session, aapl, IPHONE, NOW)

    with pytest.raises(InvalidSeries):
        create_series(db_session, aapl, IPHONE, NOW)


def test_same_name_and_metric_is_allowed_under_another_dimension(
    db_session: Session, aapl: Company
) -> None:
    create_series(db_session, aapl, SeriesInput("business", "Other", "revenue", "USD"), NOW)
    create_series(db_session, aapl, SeriesInput("geo", "Other", "revenue", "USD"), NOW)

    assert _count(db_session, SegmentSeries) == 2


def test_a_kpi_code_is_unique_among_the_companys_kpis_across_names(
    db_session: Session, aapl: Company
) -> None:
    create_series(db_session, aapl, SeriesInput("kpi", "Subscribers", "subs", "count"), NOW)

    with pytest.raises(InvalidSeries):
        create_series(db_session, aapl, SeriesInput("kpi", "Members", "subs", "count"), NOW)


def test_the_same_kpi_code_is_allowed_in_another_company(
    db_session: Session, aapl: Company
) -> None:
    other = follow(db_session, fake_sources().edgar, "MSFT")
    create_series(db_session, aapl, SeriesInput("kpi", "Subscribers", "subs", "count"), NOW)

    create_series(db_session, other, SeriesInput("kpi", "Subscribers", "subs", "count"), NOW)

    assert _count(db_session, SegmentSeries) == 2


def test_update_renames_and_reorders(db_session: Session, aapl: Company) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    updated = update_series(db_session, aapl, created.id, "  Phone ", 5, LATER)

    assert (updated.name, updated.display_order) == ("Phone", 5)
    assert updated.updated_at == datetime(2026, 10, 8, 16, 30)


def test_update_rejects_a_duplicate_or_blank_name_but_allows_keeping_its_own(
    db_session: Session, aapl: Company
) -> None:
    first = create_series(db_session, aapl, IPHONE, NOW)
    create_series(db_session, aapl, SeriesInput("business", "Mac", "revenue", "USD"), NOW)

    with pytest.raises(InvalidSeries):
        update_series(db_session, aapl, first.id, "Mac", 1, NOW)
    with pytest.raises(InvalidSeries):
        update_series(db_session, aapl, first.id, " ", 1, NOW)
    assert update_series(db_session, aapl, first.id, "iPhone", 9, NOW).display_order == 9


def test_unknown_or_other_companys_series_is_not_found(db_session: Session, aapl: Company) -> None:
    other = follow(db_session, fake_sources().edgar, "MSFT")
    foreign = create_series(db_session, other, IPHONE, NOW)

    for series_id in (9999, foreign.id):
        with pytest.raises(SeriesNotFound):
            update_series(db_session, aapl, series_id, "X", 1, NOW)
        with pytest.raises(SeriesNotFound):
            delete_series(db_session, aapl, series_id)
        with pytest.raises(SeriesNotFound):
            set_values(db_session, aapl, series_id, [ValueInput(2024, "FY", Decimal(1))], NOW)


def test_delete_removes_the_series_and_its_values(db_session: Session, aapl: Company) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)
    set_values(db_session, aapl, created.id, [ValueInput(2024, "FY", Decimal(5))], NOW)

    delete_series(db_session, aapl, created.id)

    assert _count(db_session, SegmentSeries) == 0
    assert _count(db_session, SegmentValue) == 0


def _stored(session: Session) -> dict[tuple[int, str], Decimal]:
    ids = session.execute(select(SegmentSeries.id)).scalars().all()
    return {(r.fiscal_year, r.fiscal_period): r.value for r in repo.list_values(session, ids)}


def test_set_values_upserts_and_none_deletes(db_session: Session, aapl: Company) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)
    set_values(
        db_session,
        aapl,
        created.id,
        [ValueInput(2023, "FY", Decimal("1.5")), ValueInput(2024, "FY", Decimal(2))],
        NOW,
    )

    set_values(
        db_session,
        aapl,
        created.id,
        [
            ValueInput(2024, "FY", Decimal(7)),  # update
            ValueInput(2023, "FY", None),  # delete
            ValueInput(2022, "FY", None),  # absent: no-op
        ],
        LATER,
    )

    stored = _stored(db_session)
    assert stored == {(2024, "FY"): Decimal(7)}
    assert str(stored[(2024, "FY")]) == "7"  # plain, no Numeric padding


@pytest.mark.parametrize(
    "bad",
    [
        Decimal("1e400"),
        Decimal(10) ** 15,
        Decimal("-1e15"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0.12345678901"),
    ],
)
def test_set_values_rejects_out_of_bound_values_and_writes_nothing(
    bad: Decimal, db_session: Session, aapl: Company
) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    with pytest.raises(InvalidSeries):
        set_values(
            db_session,
            aapl,
            created.id,
            [ValueInput(2023, "FY", Decimal(1)), ValueInput(2024, "FY", bad)],
            NOW,
        )

    assert _count(db_session, SegmentValue) == 0


def test_set_values_accepts_ten_decimals_and_just_under_the_limit(
    db_session: Session, aapl: Company
) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    set_values(
        db_session,
        aapl,
        created.id,
        [
            ValueInput(2023, "FY", Decimal("0.1234567891")),
            ValueInput(2024, "FY", Decimal("999999999999999")),
        ],
        NOW,
    )

    assert _stored(db_session) == {
        (2023, "FY"): Decimal("0.1234567891"),
        (2024, "FY"): Decimal("999999999999999"),
    }


def test_set_values_rejects_a_duplicated_period_and_writes_nothing(
    db_session: Session, aapl: Company
) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    with pytest.raises(InvalidSeries):
        set_values(
            db_session,
            aapl,
            created.id,
            [ValueInput(2024, "Q1", Decimal(1)), ValueInput(2024, "Q1", Decimal(2))],
            NOW,
        )

    assert _count(db_session, SegmentValue) == 0


def test_grid_of_a_company_with_nothing_is_empty(db_session: Session) -> None:
    company = follow(db_session, fake_sources().edgar, "MSFT")

    grid = segment_grid(db_session, company, "annual")

    assert grid.periods == [] and grid.blocks == []


def test_grid_reconciles_a_manual_geo_series_to_reported_revenue(
    db_session: Session, aapl: Company
) -> None:
    created = create_series(db_session, aapl, SeriesInput("geo", "Americas", "revenue", "USD"), NOW)
    set_values(
        db_session, aapl, created.id, [ValueInput(2024, "FY", Decimal(167_045_000_000))], NOW
    )

    grid = segment_grid(db_session, aapl, "annual")

    (block,) = grid.blocks
    i = [p.key for p in grid.periods].index("FY2024")
    assert block.series[0].values[i] == Decimal(167_045_000_000)
    assert block.unallocated is not None
    assert block.unallocated[i] == Decimal(391_035_000_000 - 167_045_000_000)


def test_grid_loads_series_and_values_in_bulk(db_session: Session, aapl: Company) -> None:
    from sqlalchemy import event

    for n in range(4):
        s = create_series(db_session, aapl, SeriesInput("kpi", f"K{n}", f"k{n}", "count"), NOW)
        set_values(db_session, aapl, s.id, [ValueInput(2024, "FY", Decimal(n))], NOW)
    statements: list[str] = []
    engine = db_session.get_bind()

    def record(conn, cursor, statement, *args):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        segment_grid(db_session, aapl, "annual")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert sum("FROM segment_series" in s for s in statements) == 1
    assert sum("FROM segment_value" in s for s in statements) == 1


GEO = "name,metric,unit,FY2023,Q1 FY2024\nAmericas,revenue,USD,100,5\nEurope,revenue,USD,,7\n"


def test_import_creates_series_and_values_scaled(db_session: Session, aapl: Company) -> None:
    result = import_segments(db_session, aapl, "geo", GEO, "M", NOW)

    assert (result.series_created, result.values_created, result.values_updated) == (2, 3, 0)
    series = db_session.execute(select(SegmentSeries).order_by(SegmentSeries.id)).scalars().all()
    assert [(s.name, s.display_order) for s in series] == [("Americas", 1), ("Europe", 2)]
    values = db_session.execute(select(SegmentValue.value)).scalars().all()
    assert sorted(values) == [Decimal(5_000_000), Decimal(7_000_000), Decimal(100_000_000)]


def test_reimporting_the_same_text_is_idempotent(db_session: Session, aapl: Company) -> None:
    import_segments(db_session, aapl, "geo", GEO, "units", NOW)

    again = import_segments(db_session, aapl, "geo", GEO, "units", LATER)

    assert (again.series_created, again.values_created, again.values_updated) == (0, 0, 3)
    assert _count(db_session, SegmentSeries) == 2
    assert _count(db_session, SegmentValue) == 3


def test_new_import_series_continue_the_display_order(db_session: Session, aapl: Company) -> None:
    create_series(db_session, aapl, IPHONE, NOW)

    import_segments(db_session, aapl, "geo", GEO, "units", NOW)

    orders = db_session.execute(
        select(SegmentSeries.name, SegmentSeries.display_order).order_by(SegmentSeries.id)
    ).all()
    assert [tuple(r) for r in orders] == [("iPhone", 1), ("Americas", 2), ("Europe", 3)]


def test_a_bad_import_writes_nothing_even_for_a_valid_first_row(
    db_session: Session, aapl: Company
) -> None:
    text = "name,metric,unit,FY2024\nAmericas,revenue,USD,100\nEurope,revenue,USD,abc\n"

    with pytest.raises(InvalidImport) as caught:
        import_segments(db_session, aapl, "geo", text, "units", NOW)

    assert [(i.row, i.column) for i in caught.value.issues] == [(3, 4)]
    assert _count(db_session, SegmentSeries) == 0
    assert _count(db_session, SegmentValue) == 0


def test_an_import_unit_that_differs_from_an_existing_series_is_an_issue(
    db_session: Session, aapl: Company
) -> None:
    create_series(db_session, aapl, SeriesInput("kpi", "Subscribers", "subs", "count"), NOW)
    text = "name,metric,unit,FY2024\nSubscribers,subs,pct,5\n"

    with pytest.raises(InvalidImport) as caught:
        import_segments(db_session, aapl, "kpi", text, "units", NOW)

    assert [(i.row, i.column) for i in caught.value.issues] == [(2, 3)]
    assert _count(db_session, SegmentValue) == 0


def test_an_import_kpi_code_used_by_another_name_is_an_issue_at_column_two(
    db_session: Session, aapl: Company
) -> None:
    create_series(db_session, aapl, SeriesInput("kpi", "Subscribers", "subs", "count"), NOW)
    text = "name,metric,unit,FY2024\nMembers,subs,count,5\nSubscribers,other,count,6\n"

    with pytest.raises(InvalidImport) as caught:
        import_segments(db_session, aapl, "kpi", text, "units", NOW)

    assert [(i.row, i.column) for i in caught.value.issues] == [(2, 2)]
    assert _count(db_session, SegmentSeries) == 1


def test_a_service_issue_without_parser_issues_writes_nothing(
    db_session: Session, aapl: Company
) -> None:
    create_series(db_session, aapl, SeriesInput("kpi", "Subscribers", "subs", "count"), NOW)
    text = "name,metric,unit,FY2024\nNew,new,count,1\nMembers,subs,count,5\n"

    with pytest.raises(InvalidImport):
        import_segments(db_session, aapl, "kpi", text, "units", NOW)

    assert _count(db_session, SegmentSeries) == 1


def test_reimport_with_changed_numbers_overwrites_the_stored_values(
    db_session: Session, aapl: Company
) -> None:
    first = "name,metric,unit,FY2024\nAmericas,revenue,USD,100\nEurope,revenue,USD,50\n"
    import_segments(db_session, aapl, "geo", first, "M", NOW)
    changed = first.replace("Americas,revenue,USD,100", "Americas,revenue,USD,110")

    again = import_segments(db_session, aapl, "geo", changed, "M", LATER)

    assert (again.series_created, again.values_created, again.values_updated) == (0, 0, 2)
    assert sorted(db_session.execute(select(SegmentValue.value)).scalars()) == [
        Decimal(50_000_000),
        Decimal(110_000_000),
    ]


def test_a_blank_import_cell_keeps_the_existing_value(db_session: Session, aapl: Company) -> None:
    created = create_series(db_session, aapl, SeriesInput("geo", "Americas", "revenue", "USD"), NOW)
    set_values(db_session, aapl, created.id, [ValueInput(2023, "FY", Decimal(100))], NOW)
    text = "name,metric,unit,FY2023,FY2024\nAmericas,revenue,USD,,5\n"

    result = import_segments(db_session, aapl, "geo", text, "units", LATER)

    assert (result.series_created, result.values_created, result.values_updated) == (0, 1, 0)
    assert _stored(db_session) == {(2023, "FY"): Decimal(100), (2024, "FY"): Decimal(5)}


def test_an_import_matches_series_only_within_its_own_dimension(
    db_session: Session, aapl: Company
) -> None:
    business = create_series(
        db_session, aapl, SeriesInput("business", "Other", "revenue", "USD"), NOW
    )
    set_values(db_session, aapl, business.id, [ValueInput(2024, "FY", Decimal(7))], NOW)

    result = import_segments(
        db_session, aapl, "geo", "name,metric,unit,FY2024\nOther,revenue,USD,9\n", "units", NOW
    )

    assert (result.series_created, result.values_created, result.values_updated) == (1, 1, 0)
    assert _count(db_session, SegmentSeries) == 2
    assert [v.value for v in repo.list_values(db_session, [business.id])] == [Decimal(7)]


def test_an_import_reports_parser_and_service_issues_in_one_round(
    db_session: Session, aapl: Company
) -> None:
    create_series(db_session, aapl, SeriesInput("kpi", "Subscribers", "subs", "count"), NOW)
    text = "name,metric,unit,FY2024\nSubscribers,subs,pct,5\nOther,other,count,abc\n"

    with pytest.raises(InvalidImport) as caught:
        import_segments(db_session, aapl, "kpi", text, "units", NOW)

    assert [(i.row, i.column) for i in caught.value.issues] == [(2, 3), (3, 4)]
    assert _count(db_session, SegmentValue) == 0


def test_a_kpi_code_on_two_names_in_one_paste_is_an_issue_and_writes_nothing(
    db_session: Session, aapl: Company
) -> None:
    text = "name,metric,unit,FY2024\nSubs,subs,count,1\nMembers,subs,count,2\n"

    with pytest.raises(InvalidImport) as caught:
        import_segments(db_session, aapl, "kpi", text, "units", NOW)

    assert [(i.row, i.column) for i in caught.value.issues] == [(3, 2)]
    assert _count(db_session, SegmentSeries) == 0


@pytest.mark.parametrize("year", [2**63, 20244, -5, 999, 10000])
def test_set_values_rejects_a_fiscal_year_outside_four_digits(
    year: int, db_session: Session, aapl: Company
) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    with pytest.raises(InvalidSeries):
        set_values(
            db_session,
            aapl,
            created.id,
            [ValueInput(2024, "FY", Decimal(1)), ValueInput(year, "FY", Decimal(1))],
            NOW,
        )

    assert _count(db_session, SegmentValue) == 0


def test_set_values_accepts_the_edge_fiscal_years(db_session: Session, aapl: Company) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    set_values(
        db_session,
        aapl,
        created.id,
        [ValueInput(1000, "FY", Decimal(1)), ValueInput(9999, "FY", Decimal(2))],
        NOW,
    )

    assert sorted(_stored(db_session)) == [(1000, "FY"), (9999, "FY")]


@pytest.mark.parametrize("order", [-1, 1_000_001, 2**63])
def test_update_rejects_a_display_order_outside_bounds(
    order: int, db_session: Session, aapl: Company
) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    with pytest.raises(InvalidSeries):
        update_series(db_session, aapl, created.id, "Phone", order, LATER)

    stored = db_session.execute(select(SegmentSeries)).scalar_one()
    assert (stored.name, stored.display_order) == ("iPhone", 1)


@pytest.mark.parametrize("order", [0, 1_000_000])
def test_update_accepts_the_edge_display_orders(
    order: int, db_session: Session, aapl: Company
) -> None:
    created = create_series(db_session, aapl, IPHONE, NOW)

    assert (
        update_series(db_session, aapl, created.id, "iPhone", order, LATER).display_order == order
    )
