"""Period dates inferred from one fiscal_year_end (erd/data.md, "Template"): the parser and the
check against the company's calendar."""

from datetime import date
from typing import Any

import pytest

from bedrock.ingest.manual_import import (
    ImportParseError,
    ImportPlan,
    check_periods,
    parse_import,
)
from bedrock.mapping.config import load_canonical_items
from bedrock.statements.fiscal_grid import period_dates
from bedrock.statements.periods import Calendar, FiscalYear

from .import_data import FY2006, csv_file, statement_rows, workbook

ITEMS = load_canonical_items()
SEP30 = date(2006, 9, 30)
NO_DATES = ("fiscal_year", "fiscal_period")
FORMATS = pytest.mark.parametrize("fmt", ["xlsx", "csv"])
YEAR = (2006, "FY", None, None)
QUARTER = (2006, "Q2", None, None)
EMPTY = Calendar((), ())


def file(
    fmt: str,
    statements: dict[str, list[list[Any]]],
    fiscal_year_end: str | date | None = "2006-09-30",
) -> tuple[bytes, str]:
    if fmt == "xlsx":
        return workbook(statements, "millions", fiscal_year_end), "f.xlsx"
    return csv_file(statements, "millions", fiscal_year_end=fiscal_year_end), "f.csv"


def parse(content: bytes, name: str, fye: date | None = None) -> ImportPlan:
    return parse_import(content, name, ITEMS, fiscal_year_end=fye)


def errors(content: bytes, name: str, fye: date | None = None) -> list[Any]:
    with pytest.raises(ImportParseError) as raised:
        parse(content, name, fye)
    return raised.value.errors


def sheets(periods: tuple[Any, ...] = (YEAR, QUARTER)) -> dict[str, list[list[Any]]]:
    return {
        "IS": statement_rows(periods, {"revenue": [100, 25][: len(periods)]}, NO_DATES),
        "BS": statement_rows(periods, {"cash": [10, 12][: len(periods)]}, NO_DATES),
    }


@FORMATS
def test_blank_dates_are_inferred_from_the_fiscal_year_end(fmt: str) -> None:
    plan = parse(*file(fmt, sheets()))

    by_key = {p.key: p for p in plan.periods}
    assert (by_key["FY2006"].start, by_key["FY2006"].end) == period_dates(SEP30, 2006, "FY")
    assert (by_key["FY2006Q2"].start, by_key["FY2006Q2"].end) == (
        date(2006, 1, 1),
        date(2006, 3, 31),
    )
    assert all(p.inferred for p in plan.periods)


@FORMATS
def test_the_date_rows_may_be_present_and_blank(fmt: str) -> None:
    statements = {
        "IS": statement_rows((YEAR,), {"revenue": [100]}),
        "BS": statement_rows((YEAR,), {"cash": [10]}),
    }

    plan = parse(*file(fmt, statements))

    (period,) = plan.periods
    assert period.end == date(2006, 9, 30) and period.inferred


@FORMATS
def test_a_balance_sheet_only_period_has_no_start(fmt: str) -> None:
    statements = {"BS": statement_rows((YEAR,), {"cash": [10]}, NO_DATES)}

    (period,) = parse(*file(fmt, statements)).periods

    assert period.start is None and period.end == date(2006, 9, 30)


@FORMATS
def test_dates_typed_in_a_column_win_over_the_fiscal_year_end(fmt: str) -> None:
    statements = {"IS": statement_rows((FY2006,), {"revenue": [100]})}

    (period,) = parse(*file(fmt, statements, "2006-12-31")).periods

    assert (period.start, period.end) == (date(2005, 9, 25), date(2006, 9, 30))
    assert not period.inferred


@FORMATS
def test_the_fiscal_year_end_of_the_file_wins_over_the_fallback(fmt: str) -> None:
    (period,) = parse(*file(fmt, sheets((YEAR,)), "2006-09-30"), fye=date(2006, 12, 31)).periods

    assert period.end == date(2006, 9, 30)


@FORMATS
def test_the_fallback_stands_in_for_a_file_without_one(fmt: str) -> None:
    (period,) = parse(*file(fmt, sheets((YEAR,)), None), fye=date(2006, 12, 31)).periods

    assert (period.start, period.end) == (date(2006, 1, 1), date(2006, 12, 31))


@FORMATS
def test_a_column_that_needs_dates_without_a_fiscal_year_end_is_located(fmt: str) -> None:
    found = [e for e in errors(*file(fmt, sheets((YEAR,)), None)) if "fiscal_year_end" in e.message]

    assert [e.sheet for e in found] == ["IS", "BS"]  # one per sheet
    first = found[0]
    # the fiscal_year row, over the period column (a CSV row is numbered by file line, and its
    # columns count the leading statement column)
    assert (first.row, first.column) == ((1, "F") if fmt == "xlsx" else (2, "G"))
    assert "period_start" in first.message


@FORMATS
def test_an_unreadable_fiscal_year_end_is_an_error(fmt: str) -> None:
    found = errors(*file(fmt, sheets((YEAR,)), "September"))

    (bad,) = [e for e in found if "fiscal_year_end must be a date" in e.message]
    assert (bad.sheet, bad.row, bad.column) == (
        "Instructions" if fmt == "xlsx" else None,
        None,
        None,
    )


def test_an_excel_date_cell_is_a_fiscal_year_end() -> None:
    (period,) = parse(*file("xlsx", sheets((YEAR,)), date(2006, 9, 30))).periods

    assert period.end == date(2006, 9, 30)


@FORMATS
def test_one_of_the_two_dates_alone_is_an_error(fmt: str) -> None:
    statements = {
        "IS": statement_rows(((2006, "FY", None, SEP30),), {"revenue": [100]}),
    }

    found = errors(*file(fmt, statements))

    assert "period_start and period_end go together" in found[0].message
    # the period_start row, where the date is missing (a CSV row is numbered by file line)
    assert found[0].row == (3 if fmt == "xlsx" else 5)


@FORMATS
def test_a_column_without_values_is_not_a_period_of_the_plan(fmt: str) -> None:
    statements = {
        "IS": statement_rows((YEAR, QUARTER), {"revenue": [100, None]}, NO_DATES),
    }

    plan = parse(*file(fmt, statements))

    assert [p.key for p in plan.periods] == ["FY2006"]


def test_inferred_dates_agree_across_sheets_but_a_typed_end_that_differs_is_an_error() -> None:
    statements = {
        "IS": statement_rows((FY2006,), {"revenue": [100]}),  # typed: ends 2006-09-30, 4 rows
        "BS": statement_rows((YEAR,), {"cash": [10]}, NO_DATES),
    }

    assert parse(*file("xlsx", statements, "2006-09-30")).periods[0].end == SEP30
    found = errors(*file("xlsx", statements, "2006-12-31"))
    assert "ends 2006-12-31 here but 2006-09-30 on IS" in found[0].message
    assert (found[0].sheet, found[0].row) == ("BS", 2)  # no date rows: the fiscal_period row


# -- against the company's calendar -----------------------------------------------------------


def calendar_with(year: int, end: date, start: date) -> Calendar:
    return Calendar((FiscalYear(year, start, end, (date(2006, 3, 31),)),), ())


def test_an_inferred_period_snaps_to_the_calendar_however_far_the_dates_are() -> None:
    plan = parse(*file("xlsx", sheets((YEAR,)), "2006-10-20"))  # the real year ends Sept. 30
    sec = calendar_with(2006, date(2006, 9, 30), date(2005, 10, 1))

    issues, snapped = check_periods(plan, sec, sec)

    assert issues == []
    (period,) = snapped.periods
    assert (period.start, period.end) == (date(2005, 10, 1), date(2006, 9, 30))


def test_a_typed_period_that_differs_from_the_calendar_is_still_an_error() -> None:
    statements = {
        "IS": statement_rows(
            ((2006, "FY", date(2005, 11, 1), date(2006, 10, 20)),), {"revenue": [1]}
        )
    }
    plan = parse(*file("xlsx", statements))
    sec = calendar_with(2006, date(2006, 9, 30), date(2005, 10, 1))

    issues, _ = check_periods(plan, sec, sec)

    assert "in the company's calendar" in issues[0].message


def test_an_inferred_period_inside_the_sec_years_that_is_not_in_the_calendar_is_an_error() -> None:
    plan = parse(*file("xlsx", sheets((QUARTER,)), "2006-09-30"))
    sec = calendar_with(2006, date(2006, 9, 30), date(2005, 10, 1))
    sec = Calendar((FiscalYear(2006, date(2005, 10, 1), date(2006, 9, 30), ()),), ())

    issues, _ = check_periods(plan, sec, sec)

    assert "not a period of the company's calendar" in issues[0].message


def test_an_inferred_period_before_the_first_sec_year_is_accepted() -> None:
    plan = parse(*file("xlsx", sheets((YEAR,)), "2006-09-30"))
    sec = calendar_with(2010, date(2010, 9, 30), date(2009, 10, 1))

    issues, snapped = check_periods(plan, sec, sec)

    assert issues == [] and snapped.periods[0].end == SEP30


@FORMATS
def test_many_undated_columns_give_one_error_per_sheet_and_no_cascade(fmt: str) -> None:
    quarters = ((2006, "FY", None, None), (2006, "Q1", None, None), (2006, "Q2", None, None))
    statements = {"IS": statement_rows(quarters, {"revenue": [100, 20, 30]}, NO_DATES)}

    found = errors(*file(fmt, statements, None))

    assert len(found) == 1 and "fiscal_year_end" in found[0].message
