"""Fiscal periods inferred from one fiscal-year-end date (erd/data.md, "Template")."""

from datetime import date, timedelta

import pytest

from bedrock.ingest.manual_import import FY_DAYS, QUARTER_DAYS
from bedrock.statements.fiscal_grid import annual_then_quarterly, period_dates, period_grid
from bedrock.statements.periods import fiscal_year_of

DEC31 = date(2024, 12, 31)
SEP30 = date(2024, 9, 30)
SEP28 = date(2024, 9, 28)  # a 52/53-week year, as Apple's
JAN31 = date(2025, 1, 31)
JAN3 = date(2025, 1, 3)  # a 53-week year ending in the first week of January


def dates(fye: date, year: int, period: str) -> tuple[date, date]:
    return period_dates(fye, year, period)


def test_a_december_year_end_gives_calendar_quarters() -> None:
    assert dates(DEC31, 2024, "FY") == (date(2024, 1, 1), date(2024, 12, 31))
    assert dates(DEC31, 2024, "Q1") == (date(2024, 1, 1), date(2024, 3, 31))
    assert dates(DEC31, 2024, "Q2") == (date(2024, 4, 1), date(2024, 6, 30))
    assert dates(DEC31, 2024, "Q3") == (date(2024, 7, 1), date(2024, 9, 30))
    assert dates(DEC31, 2024, "Q4") == (date(2024, 10, 1), date(2024, 12, 31))


def test_the_reference_date_may_be_any_year() -> None:
    assert dates(date(2019, 12, 31), 2024, "FY") == dates(DEC31, 2024, "FY")
    assert dates(DEC31, 1999, "FY") == (date(1999, 1, 1), date(1999, 12, 31))


def test_a_month_end_year_end_keeps_month_ends_in_every_year() -> None:
    assert dates(SEP30, 2023, "FY") == (date(2022, 10, 1), date(2023, 9, 30))
    assert dates(SEP30, 2023, "Q1") == (date(2022, 10, 1), date(2022, 12, 31))
    assert dates(SEP30, 2023, "Q2") == (date(2023, 1, 1), date(2023, 3, 31))
    assert dates(SEP30, 2023, "Q3") == (date(2023, 4, 1), date(2023, 6, 30))
    assert dates(SEP30, 2023, "Q4") == (date(2023, 7, 1), date(2023, 9, 30))


def test_february_year_end_follows_the_leap_year() -> None:
    feb = date(2024, 2, 29)
    assert dates(feb, 2023, "FY") == (date(2022, 3, 1), date(2023, 2, 28))
    assert dates(feb, 2024, "FY") == (date(2023, 3, 1), date(2024, 2, 29))


def test_a_year_end_inside_the_month_repeats_its_day() -> None:
    assert dates(SEP28, 2023, "FY") == (date(2022, 9, 29), date(2023, 9, 28))
    assert dates(SEP28, 2023, "Q1") == (date(2022, 9, 29), date(2022, 12, 28))
    assert dates(SEP28, 2023, "Q3") == (date(2023, 3, 29), date(2023, 6, 28))
    assert dates(date(2024, 8, 30), 2023, "Q2")[1] == date(2023, 2, 28)  # clamped to the month


def test_a_january_year_end_belongs_to_the_year_it_ends_in() -> None:
    assert dates(JAN31, 2025, "FY") == (date(2024, 2, 1), date(2025, 1, 31))
    assert dates(JAN31, 2025, "Q1") == (date(2024, 2, 1), date(2024, 4, 30))
    assert fiscal_year_of(dates(JAN31, 2025, "FY")[1]) == 2025


def test_a_53_week_year_ending_in_the_first_week_of_january_belongs_to_the_year_before() -> None:
    start, end = dates(JAN3, 2024, "FY")
    assert end == date(2025, 1, 3) and fiscal_year_of(end) == 2024
    assert start == date(2024, 1, 4)


@pytest.mark.parametrize(
    "fye", [DEC31, SEP30, SEP28, JAN31, JAN3, date(2024, 2, 29), date(2024, 6, 29)]
)
def test_every_period_is_consistent_with_the_parsers_rules(fye: date) -> None:
    for year in range(1990, 2031):
        fy_start, fy_end = dates(fye, year, "FY")
        assert FY_DAYS[0] <= (fy_end - fy_start).days <= FY_DAYS[1]
        assert fiscal_year_of(fy_end) == year
        previous = dates(fye, year - 1, "FY")[1]
        assert fy_start == previous + timedelta(days=1)
        quarters = [dates(fye, year, f"Q{n}") for n in (1, 2, 3, 4)]
        assert quarters[0][0] == fy_start and quarters[3][1] == fy_end
        for (_, end), (start, _) in zip(quarters, quarters[1:], strict=False):
            assert start == end + timedelta(days=1)
        for start, end in quarters:
            assert QUARTER_DAYS[0] <= (end - start).days <= QUARTER_DAYS[1]


def test_an_unknown_period_is_refused() -> None:
    with pytest.raises(ValueError, match="Q5"):
        dates(DEC31, 2024, "Q5")


def test_the_grid_is_twenty_years_of_five_periods_oldest_first() -> None:
    grid = period_grid(DEC31, 2025)

    assert len(grid) == 100
    assert [p.fiscal_year for p in grid[:5]] == [2006] * 5
    assert [p.fiscal_period for p in grid[:5]] == ["FY", "Q1", "Q2", "Q3", "Q4"]
    assert grid[-1].fiscal_year == 2025 and grid[-1].fiscal_period == "Q4"
    assert grid[0].key == "FY2006" and grid[1].key == "FY2006Q1"
    assert grid[0].label == "FY06" and grid[1].label == "Q1 FY06"
    assert (grid[1].start, grid[1].end) == (date(2006, 1, 1), date(2006, 3, 31))


def test_the_grid_length_can_be_chosen() -> None:
    assert [p.fiscal_year for p in period_grid(DEC31, 2025, years=2)][::5] == [2024, 2025]


def test_the_template_columns_are_the_years_then_the_quarters() -> None:
    columns = annual_then_quarterly(period_grid(DEC31, 2025))

    assert len(columns) == 100
    years, quarters = columns[:20], columns[20:]
    assert [(p.fiscal_year, p.fiscal_period) for p in years] == [
        (y, "FY") for y in range(2006, 2026)
    ]
    assert [(p.fiscal_year, p.fiscal_period) for p in quarters[:5]] == [
        (2006, "Q1"),
        (2006, "Q2"),
        (2006, "Q3"),
        (2006, "Q4"),
        (2007, "Q1"),
    ]
    assert (quarters[-1].fiscal_year, quarters[-1].fiscal_period) == (2025, "Q4")


def test_the_order_does_not_depend_on_the_input_order() -> None:
    grid = period_grid(DEC31, 2025, years=3)

    assert annual_then_quarterly(list(reversed(grid))) == annual_then_quarterly(grid)
