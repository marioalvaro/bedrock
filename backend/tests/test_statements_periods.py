from datetime import date

from bedrock.statements.periods import (
    annual_periods,
    fiscal_calendar,
    quarterly_periods,
    ttm_windows,
)
from tests.engine_data import canon, canon_frame, flow_facts


def calendar_of(rows: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    return fiscal_calendar(canon_frame(rows))


def fictco_rows(quarters: dict[int, tuple[int, int, int, int]], **kw):  # type: ignore[no-untyped-def]
    """Flow facts as canonical rows (the calendar looks only at period dates)."""
    return [
        canon("revenue", r["period_start"], r["period_end"], r["value"])  # type: ignore[arg-type]
        for r in flow_facts("Revenues", quarters, **kw)
    ]


TWO_YEARS = {2022: (10, 11, 12, 13), 2023: (14, 15, 16, 17)}


def test_june_fiscal_year_end() -> None:
    calendar = calendar_of(fictco_rows(TWO_YEARS))

    assert [y.fiscal_year for y in calendar.years] == [2022, 2023]
    fy23 = calendar.years[1]
    assert (fy23.start, fy23.end) == (date(2022, 7, 1), date(2023, 6, 30))
    assert fy23.quarter_ends == (date(2022, 9, 30), date(2022, 12, 31), date(2023, 3, 31))
    assert calendar.warnings == ()


def test_annual_periods_have_keys_labels_and_dates() -> None:
    periods = annual_periods(calendar_of(fictco_rows(TWO_YEARS)))

    assert [(p.key, p.label, p.fiscal_year, p.fiscal_period) for p in periods] == [
        ("FY2022", "FY22", 2022, "FY"),
        ("FY2023", "FY23", 2023, "FY"),
    ]
    assert (periods[0].start, periods[0].end) == (date(2021, 7, 1), date(2022, 6, 30))


def test_quarterly_periods_run_oldest_first_with_q4() -> None:
    periods = quarterly_periods(calendar_of(fictco_rows(TWO_YEARS)))

    assert [p.key for p in periods] == [f"FY{y}Q{n}" for y in (2022, 2023) for n in (1, 2, 3, 4)]
    q3, q4 = periods[2], periods[3]
    assert q3.label == "Q3 FY22"
    assert (q3.start, q3.end) == (date(2022, 1, 1), date(2022, 3, 31))
    assert (q4.start, q4.end) == (date(2022, 4, 1), date(2022, 6, 30))
    assert q4.fiscal_period == "Q4"


def test_a_53_week_year_ending_on_jan_3_belongs_to_the_previous_calendar_year() -> None:
    rows = [
        canon("revenue", date(2018, 12, 31), date(2019, 12, 29), 1),
        canon("revenue", date(2019, 12, 30), date(2021, 1, 3), 1),  # 371 days
        canon("revenue", date(2021, 1, 4), date(2022, 1, 2), 1),
        # fiscal 2020 quarters (13 weeks each)
        canon("revenue", date(2019, 12, 30), date(2020, 3, 29), 1),
        canon("revenue", date(2019, 12, 30), date(2020, 6, 28), 1),
        canon("revenue", date(2019, 12, 30), date(2020, 9, 27), 1),
    ]

    calendar = calendar_of(rows)

    assert [y.fiscal_year for y in calendar.years[:3]] == [2019, 2020, 2021]
    fy20 = calendar.years[1]
    assert fy20.end == date(2021, 1, 3)
    assert fy20.quarter_ends == (date(2020, 3, 29), date(2020, 6, 28), date(2020, 9, 27))
    assert [p.key for p in annual_periods(calendar)] == ["FY2019", "FY2020", "FY2021"]


def test_a_year_with_only_two_10qs_has_no_quarters_and_a_warning() -> None:
    rows = fictco_rows(TWO_YEARS, skip=frozenset({(2023, 3)}))

    calendar = calendar_of(rows)

    assert calendar.years[1].quarter_ends == ()
    assert len(calendar.warnings) == 1
    assert "2023" in calendar.warnings[0]
    assert [p.key for p in annual_periods(calendar)] == ["FY2022", "FY2023"]
    assert [p.key for p in quarterly_periods(calendar)] == [f"FY2022Q{n}" for n in (1, 2, 3, 4)]


def test_a_trailing_year_still_open_exposes_its_reported_quarters() -> None:
    rows = fictco_rows({2022: (10, 11, 12, 13)})
    rows.append(canon("revenue", date(2022, 7, 1), date(2022, 9, 30), 14, form="10-Q"))
    rows.append(canon("revenue", date(2022, 10, 1), date(2022, 12, 31), 15, form="10-Q"))
    rows.append(canon("revenue", date(2022, 7, 1), date(2022, 12, 31), 29, form="10-Q"))

    calendar = calendar_of(rows)

    open_year = calendar.years[-1]
    assert (open_year.fiscal_year, open_year.end) == (2023, None)
    assert open_year.quarter_ends == (date(2022, 9, 30), date(2022, 12, 31))
    assert [p.key for p in annual_periods(calendar)] == ["FY2022"]
    assert [p.key for p in quarterly_periods(calendar)][-2:] == ["FY2023Q1", "FY2023Q2"]


def test_instants_and_averages_do_not_define_the_calendar() -> None:
    rows = [
        canon("cash", None, date(2023, 6, 30), kind="instant"),
        canon("eps_diluted", date(2022, 7, 1), date(2023, 6, 30), kind="average"),
    ]

    calendar = calendar_of(rows)

    assert calendar.years == ()
    assert annual_periods(calendar) == []


def test_empty_frame_gives_an_empty_calendar() -> None:
    calendar = calendar_of([])

    assert calendar.years == () and calendar.warnings == ()
    assert quarterly_periods(calendar) == [] and ttm_windows(calendar) == []


def test_ttm_windows_cover_the_last_four_quarters() -> None:
    windows = ttm_windows(calendar_of(fictco_rows(TWO_YEARS)))

    assert [w.period.key for w in windows] == [
        "TTM-FY2022Q4",
        "TTM-FY2023Q1",
        "TTM-FY2023Q2",
        "TTM-FY2023Q3",
        "TTM-FY2023Q4",
    ]
    last = windows[-1]
    assert last.period.label == "TTM Q4 FY23"
    assert (last.period.start, last.period.end) == (date(2022, 7, 1), date(2023, 6, 30))
    assert [q.key for q in last.quarters] == [f"FY2023Q{n}" for n in (1, 2, 3, 4)]
    second = windows[1]
    assert [q.key for q in second.quarters] == ["FY2022Q2", "FY2022Q3", "FY2022Q4", "FY2023Q1"]


def test_no_ttm_window_spans_a_year_without_quarters() -> None:
    three = {2022: (1, 1, 1, 1), 2023: (1, 1, 1, 1), 2024: (1, 1, 1, 1)}
    rows = fictco_rows(three, skip=frozenset({(2023, 2)}))

    windows = ttm_windows(calendar_of(rows))

    # FY2023 has no quarters, so only windows wholly inside FY2022 or FY2024 exist
    assert [w.period.key for w in windows] == ["TTM-FY2022Q4", "TTM-FY2024Q4"]
