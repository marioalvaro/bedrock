"""The earnings review's pure parts (FR-ACC-06; docs/erd/accountability.md "Earnings review"): the
reviewed period, the restated prior values, the flags that changed state and the pickers that read
a snapshot's line and driver cells."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pytest

from bedrock.analysis.qoe import FlagRow, FlagTable, Severity, Thresholds
from bedrock.backtest.review import (
    DRIVER_MISSES,
    PERIOD_SLACK,
    RESTATED_LIMIT,
    RESTATED_TOLERANCE,
    FlagChange,
    LinePick,
    Restated,
    driver_misses,
    flag_changes,
    line_pick,
    restated,
    review_period,
)
from bedrock.statements.build import Row, StatementTable
from bedrock.statements.periods import Period


def test_the_constants_are_the_erds() -> None:
    assert PERIOD_SLACK == timedelta(days=10)
    assert RESTATED_TOLERANCE == Decimal("0.005")
    assert RESTATED_LIMIT == 50
    assert DRIVER_MISSES == 5


# --- review_period ---------------------------------------------------------------------------


def fy(year: int, end: date) -> Period:
    return Period(f"FY{year}", f"FY{year % 100}", year, "FY", end - timedelta(days=364), end)


def quarter(year: int, q: int, end: date) -> Period:
    return Period(f"FY{year}Q{q}", f"Q{q} FY{year % 100}", year, f"Q{q}", end - timedelta(91), end)


QUARTERS = [
    quarter(2026, 1, date(2025, 12, 27)),
    quarter(2026, 2, date(2026, 3, 28)),
    quarter(2026, 3, date(2026, 6, 27)),
]


def test_the_period_is_the_one_whose_end_is_the_filings_period_end() -> None:
    assert review_period(QUARTERS, date(2026, 6, 27)) == QUARTERS[2]


@pytest.mark.parametrize("days", [-10, -3, 4, 10])
def test_an_end_within_the_slack_matches(days: int) -> None:
    assert review_period(QUARTERS, date(2026, 6, 27) + timedelta(days)) == QUARTERS[2]


@pytest.mark.parametrize("days", [-11, 11])
def test_an_end_beyond_the_slack_has_no_period(days: int) -> None:
    assert review_period(QUARTERS, date(2026, 6, 27) + timedelta(days)) is None


def test_the_nearest_end_wins() -> None:
    near = quarter(2026, 3, date(2026, 6, 30))
    far = quarter(2026, 2, date(2026, 6, 22))
    assert review_period([far, near], date(2026, 6, 28)) == near


def test_an_equally_near_pair_takes_the_earlier_end() -> None:
    early = quarter(2026, 2, date(2026, 6, 25))
    late = quarter(2026, 3, date(2026, 6, 29))
    assert review_period([late, early], date(2026, 6, 27)) == early


def test_no_periods_has_no_period() -> None:
    assert review_period([], date(2026, 6, 27)) is None


def test_the_frequency_is_the_tables_an_annual_list_gives_the_year() -> None:
    years = [fy(2024, date(2024, 9, 28)), fy(2025, date(2025, 9, 27))]
    assert review_period(years, date(2025, 9, 27)) == years[1]
    assert review_period(years, date(2026, 6, 27)) is None  # a 10-Q's end is no year's end


# --- restated --------------------------------------------------------------------------------

FY24 = fy(2024, date(2024, 9, 28))
FY25 = fy(2025, date(2025, 9, 27))
FY26 = fy(2026, date(2026, 9, 26))
CUTOFF = FY26.end


def row(code: str, values: list[Decimal | None], label: str | None = None) -> Row:
    return Row(
        code=code,
        label=label or code.title(),
        unit="USD",
        kind="flow",
        depth=0,
        values=values,
        provenance=["reported" if v is not None else None for v in values],
        yoy=[None] * len(values),
        common_size=[None] * len(values),
    )


def table(
    statement: str, periods: list[Period], *rows: Row, freq: str = "annual"
) -> StatementTable:
    return StatementTable(statement, freq, periods, list(rows), None, [])


def d(text: str) -> Decimal:
    return Decimal(text)


def test_a_value_changed_by_more_than_the_tolerance_is_restated() -> None:
    before = [table("IS", [FY24, FY25], row("revenue", [d("100"), d("200")], "Revenue"))]
    after = [table("IS", [FY24, FY25, FY26], row("revenue", [d("100"), d("210"), d("300")]))]

    assert restated(before, after, CUTOFF) == [
        Restated("IS", "revenue", "Revenue", "USD", 2025, "FY", d("200"), d("210"), d("0.05"))
    ]


def test_a_change_within_the_tolerance_is_not_a_restatement() -> None:
    before = [table("IS", [FY25], row("revenue", [d("1000")]))]
    exactly = [table("IS", [FY25], row("revenue", [d("1005")]))]  # 0.5%: not more than
    over = [table("IS", [FY25], row("revenue", [d("994.9")]))]

    assert restated(before, exactly, CUTOFF) == []
    assert [r.after for r in restated(before, over, CUTOFF)] == [d("994.9")]


def test_any_change_from_zero_is_restated_with_no_pct_change() -> None:
    before = [table("IS", [FY25], row("other", [d("0")]))]
    after = [table("IS", [FY25], row("other", [d("0.01")]))]

    [only] = restated(before, after, CUTOFF)
    assert (only.before, only.after, only.pct_change) == (d("0"), d("0.01"), None)


def test_zero_to_zero_is_not_restated() -> None:
    same = [table("IS", [FY25], row("other", [d("0")]))]
    assert restated(same, same, CUTOFF) == []


def test_a_value_that_only_appeared_or_vanished_is_not_a_restatement() -> None:
    before = [table("IS", [FY25], row("a", [None]), row("b", [d("5")]))]
    after = [table("IS", [FY25], row("a", [d("5")]), row("b", [None]))]

    assert restated(before, after, CUTOFF) == []


def test_a_line_or_period_of_one_read_only_is_not_a_restatement() -> None:
    before = [table("IS", [FY24], row("a", [d("1")]))]
    after = [table("IS", [FY25], row("a", [d("9")]), row("b", [d("9")]))]

    assert restated(before, after, CUTOFF) == []


def test_only_periods_ending_before_the_cutoff_count() -> None:
    before = [table("IS", [FY25, FY26], row("a", [d("1"), d("1")]))]
    after = [table("IS", [FY25, FY26], row("a", [d("2"), d("2")]))]

    assert [r.fiscal_year for r in restated(before, after, FY26.end)] == [2025]
    assert restated(before, after, FY25.end) == []


def test_tables_are_matched_by_statement_and_frequency() -> None:
    q4 = Period("FY2025Q4", "Q4 FY25", 2025, "Q4", date(2025, 6, 29), FY25.end)
    before = [
        table("IS", [FY25], row("a", [d("1")])),
        table("IS", [q4], row("a", [d("10")]), freq="quarterly"),
        table("BS", [FY25], row("a", [d("100")])),
    ]
    after = [
        table("BS", [FY25], row("a", [d("100")])),
        table("IS", [q4], row("a", [d("12")]), freq="quarterly"),
        table("IS", [FY25], row("a", [d("1")])),
    ]

    [only] = restated(before, after, CUTOFF)
    assert (only.statement, only.fiscal_period, only.after) == ("IS", "Q4", d("12"))


def test_the_label_and_unit_are_the_read_nows() -> None:
    before = [table("IS", [FY25], row("a", [d("1")], "Old name"))]
    after = [table("IS", [FY25], row("a", [d("2")], "New name"))]
    assert restated(before, after, CUTOFF)[0].label == "New name"


def test_the_order_is_largest_change_first_nulls_last_then_statement_code_period() -> None:
    before = [
        table("IS", [FY24, FY25], row("b", [d("100"), d("100")]), row("a", [d("100"), d("0")])),
        table("BS", [FY25], row("z", [d("100")])),
    ]
    after = [
        table("IS", [FY24, FY25], row("b", [d("110"), d("50")]), row("a", [d("110"), d("3")])),
        table("BS", [FY25], row("z", [d("90")])),
    ]

    order = [
        (r.statement, r.code, r.fiscal_year, r.pct_change) for r in restated(before, after, CUTOFF)
    ]

    assert order == [
        ("IS", "b", 2025, d("-0.5")),
        ("BS", "z", 2025, d("-0.1")),
        ("IS", "a", 2024, d("0.1")),
        ("IS", "b", 2024, d("0.1")),
        ("IS", "a", 2025, None),
    ]


def test_every_restatement_is_returned_the_cap_is_the_callers() -> None:
    periods = [fy(year, date(year, 9, 30)) for year in range(1960, 1960 + RESTATED_LIMIT + 5)]
    before = [table("IS", periods, row("a", [d("1")] * len(periods)))]
    after = [table("IS", periods, row("a", [d("2")] * len(periods)))]

    assert len(restated(before, after, CUTOFF)) == RESTATED_LIMIT + 5


def test_empty_reads_restate_nothing() -> None:
    assert restated([], [], CUTOFF) == []


# --- flag_changes ----------------------------------------------------------------------------


def flag_row(code: str, severity: list[Severity | None], values: list[Decimal | None]) -> FlagRow:
    return FlagRow(
        code=code,
        label=code.title(),
        rule=f"{code} rule",
        direction="above",
        unit="pct",
        thresholds=Thresholds(None, None),
        values=values,
        severity=severity,
        warn_levels=[None] * len(values),
        alert_levels=[None] * len(values),
        custom=False,
        error=None,
    )


def flags(periods: list[Period], *rows: FlagRow) -> FlagTable:
    return FlagTable("annual", periods, list(rows))


def test_a_flag_that_turned_to_warn_or_alert_or_back_is_listed() -> None:
    before = flags(
        [FY24, FY25],
        flag_row("a", ["alert", "none"], [d("9"), d("1")]),
        flag_row("b", ["none", "warn"], [d("1"), d("5")]),
        flag_row("c", ["none", "none"], [d("1"), d("1")]),
    )
    after = flags(
        [FY24, FY25, FY26],
        flag_row("a", ["alert", "none", "alert"], [d("9"), d("1"), d("8")]),
        flag_row("b", ["none", "warn", "none"], [d("1"), d("5"), d("2")]),
        flag_row("c", ["none", "none", "none"], [d("1"), d("1"), d("1")]),
    )

    assert flag_changes(before, after) == [
        FlagChange("a", "A", "pct", "none", "alert", d("1"), d("8")),
        FlagChange("b", "B", "pct", "warn", "none", d("5"), d("2")),
    ]


def test_warn_to_alert_is_listed_and_an_unchanged_alert_is_not() -> None:
    before = flags([FY25], flag_row("a", ["warn"], [d("5")]), flag_row("b", ["alert"], [d("9")]))
    after = flags([FY25], flag_row("a", ["alert"], [d("9")]), flag_row("b", ["alert"], [d("8")]))

    assert [(c.code, c.before, c.after) for c in flag_changes(before, after)] == [
        ("a", "warn", "alert")
    ]


def test_none_to_no_value_is_not_listed_and_no_value_to_warn_is() -> None:
    before = flags([FY25], flag_row("a", ["none"], [d("1")]), flag_row("b", [None], [None]))
    after = flags([FY25], flag_row("a", [None], [None]), flag_row("b", ["warn"], [d("5")]))

    assert [(c.code, c.before, c.after, c.value_before) for c in flag_changes(before, after)] == [
        ("b", None, "warn", None)
    ]


def test_a_table_with_no_periods_reads_every_severity_as_none() -> None:
    empty = flags([], flag_row("a", [], []))
    after = flags([FY25], flag_row("a", ["alert"], [d("9")]))

    assert [(c.before, c.after) for c in flag_changes(empty, after)] == [(None, "alert")]


def test_a_rule_in_one_table_only_reads_none_on_the_other_side() -> None:
    before = flags([FY25], flag_row("gone", ["alert"], [d("9")]))
    after = flags([FY25], flag_row("new", ["warn"], [d("5")]))

    assert [(c.code, c.before, c.after) for c in flag_changes(before, after)] == [
        ("new", None, "warn"),
        ("gone", "alert", None),
    ]


# --- line_pick and driver_misses -------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    fiscal_year: int
    fiscal_period: str
    forecast: Decimal
    actual: Decimal | None = None
    pct_error: Decimal | None = None
    in_range: bool | None = None
    source: str | None = None


@dataclass(frozen=True)
class Series:
    code: str
    label: str
    unit: str
    cells: list[Cell]


@dataclass(frozen=True)
class Case:
    case: str
    lines: list[Series] = field(default_factory=list)
    drivers: list[Series] = field(default_factory=list)


def revenue(*cells: Cell) -> list[Series]:
    return [Series("revenue", "Revenue", "USD", list(cells))]


Q3 = (2026, "Q3")


def three_cases() -> list[Case]:
    return [
        Case("base", revenue(Cell(2026, "Q3", d("100"), d("90"), d("0.111"), True))),
        Case("bull", revenue(Cell(2026, "Q3", d("120")))),
        Case("bear", revenue(Cell(2026, "Q3", d("80")), Cell(2026, "Q4", d("1")))),
    ]


def test_a_line_reads_the_base_cell_and_the_envelope_of_the_three_cases() -> None:
    assert line_pick(three_cases(), "revenue", Q3) == LinePick(
        d("100"), d("80"), d("120"), d("0.111"), True
    )


def test_a_case_without_the_cell_leaves_no_envelope() -> None:
    cases = three_cases()
    cases[1] = Case("bull")  # a case that could not run has no lines

    pick = line_pick(cases, "revenue", Q3)

    assert (pick.forecast, pick.low, pick.high) == (d("100"), None, None)


def test_a_line_or_period_the_snapshot_lacks_is_all_nulls() -> None:
    empty = LinePick(None, None, None, None, None)
    assert line_pick(three_cases(), "cash", Q3) == empty
    assert line_pick(three_cases(), "revenue", (2026, "Q4")) == empty
    assert line_pick([], "revenue", Q3) == empty


def drivers_case(*cells: tuple[str, int, str, Decimal | None]) -> Case:
    return Case(
        "base",
        drivers=[
            Series(code, code.title(), "pct", [Cell(year, period, d("0.1"), d("0.1"), pct)])
            for code, year, period, pct in cells
        ],
    )


def test_the_drivers_that_missed_most_are_the_five_largest_base_errors() -> None:
    base = drivers_case(
        ("a", 2025, "FY", d("0.1")),
        ("b", 2025, "FY", d("-0.6")),
        ("c", 2025, "FY", d("0.3")),
        ("d", 2025, "FY", d("-0.3")),
        ("e", 2025, "FY", d("0.05")),
        ("f", 2025, "FY", d("0.2")),
        ("g", 2025, "FY", None),  # no error: never listed
        ("h", 2024, "FY", d("0.9")),  # another year
    )
    bull = Case(
        "bull", drivers=[Series("z", "Z", "pct", [Cell(2025, "FY", d("1"), d("2"), d("9"))])]
    )

    missed = driver_misses([bull, base], 2025)

    assert [m.code for m in missed] == ["b", "c", "d", "f", "a"]
    assert (missed[0].label, missed[0].unit, missed[0].pct_error) == ("B", "pct", d("-0.6"))


def test_fewer_drivers_than_the_limit_are_all_listed_and_none_without_a_base() -> None:
    assert [m.code for m in driver_misses([drivers_case(("a", 2025, "FY", d("0.1")))], 2025)] == [
        "a"
    ]
    assert driver_misses([Case("bull")], 2025) == []


def test_a_quarter_cell_is_never_a_driver_miss() -> None:
    assert driver_misses([drivers_case(("a", 2025, "Q1", d("0.1")))], 2025) == []
