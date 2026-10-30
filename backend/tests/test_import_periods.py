"""An import's periods against the company's fiscal calendar (erd/data.md, "Fiscal calendar")."""

from datetime import date

import pandas as pd

from bedrock.ingest.manual_import import ImportPlan, PlanPeriod, check_periods
from bedrock.mapping.mapper import CANONICAL_COLUMNS, map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.periods import Calendar, fiscal_calendar
from tests.engine_data import facts, fy_dates
from tests.test_import_pipeline import ITEMS, MAPS, sec_rows


def calendar() -> Calendar:
    return fiscal_calendar(map_facts(select_vintage(facts(sec_rows())), MAPS, ITEMS))


def period(fy: int, fp: str, start: date | None, end: date) -> PlanPeriod:
    return PlanPeriod(fy, fp, start, end, "IS", "F")


def plan(*periods: PlanPeriod) -> ImportPlan:
    return ImportPlan("xlsx", "units", periods, (), ())


FY2024 = fy_dates(2024)
EMPTY = fiscal_calendar(pd.DataFrame(columns=CANONICAL_COLUMNS))


def test_a_period_of_the_calendar_is_accepted_with_the_calendars_dates() -> None:
    off_by_two = period(2024, "FY", FY2024[0], date(2024, 7, 2))

    issues, snapped = check_periods(plan(off_by_two), calendar(), calendar())

    assert issues == []
    assert (snapped.periods[0].start, snapped.periods[0].end) == (FY2024[0], FY2024[1])


def test_a_quarter_of_the_calendar_is_accepted() -> None:
    q2 = period(2024, "Q2", date(2023, 10, 1), date(2023, 12, 31))

    issues, snapped = check_periods(plan(q2), calendar(), calendar())

    assert issues == [] and snapped.periods == (q2,)


def test_a_balance_sheet_only_period_matches_on_its_end_date() -> None:
    issues, snapped = check_periods(
        plan(period(2024, "FY", None, date(2024, 6, 28))), calendar(), calendar()
    )

    assert issues == [] and snapped.periods[0].end == FY2024[1]


def test_a_period_with_other_dates_than_the_calendars_is_an_error() -> None:
    wrong = period(2024, "FY", date(2023, 1, 1), date(2023, 12, 31))

    (issue,), _ = check_periods(plan(wrong), calendar(), calendar())

    assert (issue.sheet, issue.row, issue.column) == ("IS", 4, "F")
    assert "FY2024" in issue.message and "2024-06-30" in issue.message


def test_a_year_before_the_first_sec_year_is_accepted_as_it_is() -> None:
    old = period(2020, "FY", date(2019, 7, 1), date(2020, 6, 30))

    issues, snapped = check_periods(plan(old), calendar(), calendar())

    assert issues == [] and snapped.periods == (old,)


def test_a_new_period_inside_the_sec_years_is_an_error() -> None:
    later = period(2026, "FY", date(2025, 7, 1), date(2026, 6, 30))

    (issue,), _ = check_periods(plan(later), calendar(), calendar())

    assert "FY2026" in issue.message and "calendar" in issue.message


def test_a_label_that_belongs_to_other_dates_is_an_error() -> None:
    mislabelled = period(2025, "FY", FY2024[0], FY2024[1])

    (issue,), _ = check_periods(plan(mislabelled), calendar(), calendar())

    assert "FY2024" in issue.message


def test_any_period_is_accepted_for_a_company_without_sec_years() -> None:
    new = period(2025, "FY", date(2024, 7, 1), date(2025, 6, 30))

    issues, _ = check_periods(plan(new), EMPTY, EMPTY)

    assert issues == []


def test_a_company_without_sec_years_still_matches_its_imported_calendar() -> None:
    imported = fiscal_calendar(
        pd.DataFrame(
            [
                {"period_start": FY2024[0], "period_end": FY2024[1], "kind": "flow"},
            ]
        )
    )
    clash = period(2024, "FY", date(2023, 1, 1), date(2023, 12, 31))

    (issue,), _ = check_periods(plan(clash), EMPTY, imported)

    assert "FY2024" in issue.message
