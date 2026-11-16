"""Scoring stored rows against the latest actuals (docs/erd/accountability.md "Scoring"). Pure;
every expected number is worked out by hand."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from bedrock.backtest.scoring import (
    ACTUAL_PROVENANCE,
    SCORED_CODES,
    Scored,
    SummaryRow,
    driver_actuals,
    line_actuals,
    line_ranges,
    score_run,
    summarize,
    units_of,
)
from bedrock.backtest.snapshot import ValueRow
from bedrock.forecast.history import ScenarioSettings
from bedrock.services.forecasts import COMPARE_CODES
from tests.forecast_data import make_history

D = Decimal
CREATED = date(2020, 1, 15)
GROWTH = ScenarioSettings("growth")


@dataclass(frozen=True)
class Split:
    effective_date: date
    ratio: Decimal


def line(
    point: str, code: str = "revenue", fy: int = 2020, fp: str = "FY", horizon: int = 1
) -> ValueRow:
    return ValueRow("line", code, fy, fp, horizon, D(point), None, None, None, None, None, None)


def driver(
    point: str, p05: str | None = None, p95: str | None = None, code: str = "tax_rate"
) -> ValueRow:
    low = None if p05 is None else D(p05)
    high = None if p95 is None else D(p95)
    return ValueRow("driver", code, 2020, "FY", 1, D(point), low, None, None, None, high, "engine")


UNITS = {
    "revenue": "USD",
    "tax_rate": "pct",
    "shares_diluted": "shares",
    "eps_diluted": "USD/shares",
}


def score_line(row: ValueRow, actual: str) -> Scored:
    lines = {(row.code, row.fiscal_year, row.fiscal_period): D(actual)}
    [scored] = score_run([row], lines, {}, UNITS, CREATED, [])
    return scored


def score_driver(row: ValueRow, actual: str) -> Scored:
    [scored] = score_run([row], {}, {(row.code, 2020): D(actual)}, UNITS, CREATED, [])
    return scored


def test_scored_codes_are_the_comparison_lines() -> None:
    assert SCORED_CODES == COMPARE_CODES


@pytest.mark.parametrize(
    ("forecast", "actual", "expected"),
    [
        ("110", "100", "0.1"),  # ran high
        ("90", "100", "-0.1"),  # ran low
        ("-90", "-100", "0.1"),  # a loss smaller than the actual one ran high
    ],
)
def test_pct_error_is_signed_on_the_absolute_actual(
    forecast: str, actual: str, expected: str
) -> None:
    assert score_line(line(forecast), actual).pct_error == D(expected)


def test_a_zero_actual_is_scored_with_no_pct_error() -> None:
    scored = score_line(line("5"), "0")
    assert scored.actual == 0
    assert scored.pct_error is None


def test_a_row_with_no_actual_is_not_scored() -> None:
    assert score_run([line("5"), driver("0.1")], {}, {}, UNITS, CREATED, []) == []


def test_a_scored_row_carries_its_row_and_actual() -> None:
    assert score_line(line("110", fy=2021, fp="Q2", horizon=3), "100") == Scored(
        "line", "revenue", 2021, "Q2", 3, D("110"), D("100"), D("0.1"), None
    )


def history_with(provenance: str) -> object:
    history = make_history({2020: {"revenue": 100, "cash": 7}})
    table = history.annual["IS"]
    next(r for r in table.rows if r.code == "revenue").provenance[0] = provenance  # type: ignore[call-overload]  # a test's provenance
    return history


@pytest.mark.parametrize("provenance", sorted(ACTUAL_PROVENANCE))
def test_every_actual_provenance_counts(provenance: str) -> None:
    actuals = line_actuals(history_with(provenance))  # type: ignore[arg-type]  # made above
    assert actuals[("revenue", 2020, "FY")] == D(100)


def test_an_approximated_cell_is_not_an_actual() -> None:
    actuals = line_actuals(history_with("approximated"))  # type: ignore[arg-type]  # made above
    assert ("revenue", 2020, "FY") not in actuals
    assert actuals[("cash", 2020, "FY")] == D(7)


def test_imported_is_an_actual_provenance() -> None:
    assert "imported" in ACTUAL_PROVENANCE
    assert "approximated" not in ACTUAL_PROVENANCE


def test_line_actuals_read_the_quarters_too() -> None:
    history = make_history({2020: {"revenue": 100}}, {"FY2020Q2": {"revenue": 30}})
    actuals = line_actuals(history)
    assert actuals[("revenue", 2020, "Q2")] == D(30)
    assert actuals[("revenue", 2020, "FY")] == D(100)


def test_a_null_cell_is_not_an_actual() -> None:
    assert line_actuals(make_history({2020: {"revenue": None}})) == {}


def test_driver_actuals_are_the_history_values_without_the_nulls() -> None:
    history = make_history(
        {2019: {"revenue": 100}, 2020: {"revenue": 110}, 2021: {"revenue": None}}
    )
    actuals = driver_actuals(history, GROWTH, [2020, 2021, 2030])
    assert actuals[("revenue_growth", 2020)] == D("0.1")
    assert ("revenue_growth", 2021) not in actuals
    assert ("revenue_growth", 2030) not in actuals


def test_units_of_covers_lines_and_drivers() -> None:
    units = units_of(make_history({2020: {"revenue": 100}}), GROWTH)
    assert units["revenue"] == "USD"
    assert units["eps_diluted"] == "USD/shares"
    assert units["gross_margin"] == "pct"


SPLIT = Split(date(2020, 8, 31), D(4))


@pytest.mark.parametrize(
    ("code", "point", "restated"),
    [("shares_diluted", "100", "400"), ("eps_diluted", "10", "2.5"), ("revenue", "10", "10")],
)
def test_a_split_after_the_run_restates_shares_and_per_share_only(
    code: str, point: str, restated: str
) -> None:
    lines = {(code, 2020, "FY"): D(restated)}
    [scored] = score_run([line(point, code)], lines, {}, UNITS, CREATED, [SPLIT])
    assert scored.forecast == D(restated)
    assert scored.pct_error == 0


def test_a_split_before_the_run_changes_nothing() -> None:
    before = Split(date(2019, 1, 1), D(4))
    lines = {("eps_diluted", 2020, "FY"): D("10")}
    [scored] = score_run([line("10", "eps_diluted")], lines, {}, UNITS, CREATED, [before])
    assert scored.forecast == D("10")


@pytest.mark.parametrize(
    ("actual", "inside"),
    [("0.01", True), ("0.05", True), ("0.03", True), ("0.0099", False), ("0.0501", False)],
)
def test_a_driver_is_in_range_inside_its_band_bounds_included(actual: str, inside: bool) -> None:
    assert score_driver(driver("0.03", "0.01", "0.05"), actual).in_range is inside


def test_a_driver_with_no_band_has_no_in_range() -> None:
    assert score_driver(driver("0.03"), "0.03").in_range is None


def test_a_backtest_line_has_no_in_range() -> None:
    assert score_line(line("100"), "100").in_range is None


def cases(base: str, bull: str, bear: str) -> dict[str, list[ValueRow]]:
    return {"base": [line(base)], "bull": [line(bull)], "bear": [line(bear)]}


def test_line_ranges_are_the_envelope_of_the_three_cases() -> None:
    assert line_ranges(cases("100", "120", "80")) == {("revenue", 2020, "FY"): (D(80), D(120))}


def test_line_ranges_work_with_bull_below_bear() -> None:
    assert line_ranges(cases("100", "80", "120")) == {("revenue", 2020, "FY"): (D(80), D(120))}


def test_line_ranges_include_base_when_it_sits_outside_bull_and_bear() -> None:
    assert line_ranges(cases("200", "120", "80")) == {("revenue", 2020, "FY"): (D(80), D(200))}


def test_a_period_missing_from_a_case_has_no_range() -> None:
    three = cases("100", "120", "80")
    three["bear"] = []
    assert line_ranges(three) == {}


def test_a_missing_case_gives_no_ranges() -> None:
    assert line_ranges({"base": [line("100")], "bull": [line("120")]}) == {}


def test_driver_rows_have_no_line_range() -> None:
    assert line_ranges({c: [driver("0.1")] for c in ("base", "bull", "bear")}) == {}


RANGES = {("revenue", 2020, "FY"): (D(80), D(120))}


def score_case(case: str | None, actual: str) -> bool | None:
    lines = {("revenue", 2020, "FY"): D(actual)}
    [scored] = score_run([line("100")], lines, {}, UNITS, CREATED, [], RANGES, case)
    return scored.in_range


@pytest.mark.parametrize(
    ("actual", "inside"), [("80", True), ("120", True), ("79", False), ("121", False)]
)
def test_a_base_line_is_in_range_inside_the_envelope(actual: str, inside: bool) -> None:
    assert score_case("base", actual) is inside


@pytest.mark.parametrize("case", ["bull", "bear", None])
def test_only_a_base_line_has_a_range(case: str | None) -> None:
    assert score_case(case, "100") is None


def test_a_base_line_with_no_range_for_its_period_has_no_in_range() -> None:
    lines = {("revenue", 2021, "FY"): D("100")}
    [scored] = score_run([line("100", fy=2021)], lines, {}, UNITS, CREATED, [], RANGES, "base")
    assert scored.in_range is None


def test_the_range_is_restated_with_the_line() -> None:
    ranges = {("eps_diluted", 2020, "FY"): (D("8"), D("12"))}
    lines = {("eps_diluted", 2020, "FY"): D("2.5")}
    row = line("10", "eps_diluted")
    [scored] = score_run([row], lines, {}, UNITS, CREATED, [SPLIT], ranges, "base")
    assert scored.in_range is True  # 2 <= 2.5 <= 3 in today's shares


def test_a_driver_band_is_restated_with_the_driver() -> None:
    row = driver("10", "8", "12", code="eps_diluted")
    [scored] = score_run([row], {}, {("eps_diluted", 2020): D("2.5")}, UNITS, CREATED, [SPLIT])
    assert scored.in_range is True


def item(
    pct: str | None,
    in_range: bool | None = None,
    code: str = "revenue",
    fp: str = "FY",
    horizon: int = 1,
) -> Scored:
    error = None if pct is None else D(pct)
    return Scored("line", code, 2020, fp, horizon, D(1), D(1), error, in_range)


def test_summarize_by_hand() -> None:
    rows = summarize(
        "ets",
        [item("0.1", True), item("-0.3", False), item(None, True), item("0.2", None)],
    )
    # MAPE (0.1 + 0.3 + 0.2) / 3 = 0.2, bias (0.1 - 0.3 + 0.2) / 3 = 0, hits 2 of the 3 with a range
    assert rows == [
        SummaryRow("line", "revenue", "ets", "annual", 1, 4, D("0.2"), D(0), D(2) / D(3), 3)
    ]


def test_summarize_keeps_annual_and_quarterly_apart() -> None:
    rows = summarize("ets", [item("0.1", fp="FY"), item("0.3", fp="Q1"), item("0.5", fp="Q2")])
    assert [(r.freq, r.n, r.mape) for r in rows] == [
        ("annual", 1, D("0.1")),
        ("quarterly", 2, D("0.4")),
    ]


def test_summarize_keeps_horizons_and_codes_apart() -> None:
    rows = summarize(
        "ets",
        [
            item("0.1", horizon=1),
            item("0.2", horizon=2),
            item("0.4", code="cash", horizon=1),
        ],
    )
    assert [(r.code, r.horizon, r.mape) for r in rows] == [
        ("cash", 1, D("0.4")),
        ("revenue", 1, D("0.1")),
        ("revenue", 2, D("0.2")),
    ]


def test_a_group_with_no_range_has_a_null_hit_rate() -> None:
    [row] = summarize("ets", [item("0.1")])
    assert row.n_range == 0
    assert row.hit_rate is None


def test_a_group_of_zero_actuals_has_no_mape_or_bias() -> None:
    [row] = summarize("ets", [item(None)])
    assert (row.n, row.mape, row.bias) == (1, None, None)


def test_summarize_of_nothing_is_nothing() -> None:
    assert summarize("ets", []) == []


@pytest.mark.parametrize(
    "errors",
    [
        ["0.1"],
        ["-0.1"],
        ["0.1", "-0.1"],
        ["0.3", "0.3", "-0.9", "2"],
        ["-10", "-0.0001", "0"],
        ["10", "10", "10"],
    ],
)
def test_mape_bounds_the_size_of_the_bias(errors: list[str]) -> None:
    [row] = summarize("ets", [item(e) for e in errors])
    assert row.mape is not None and row.bias is not None
    assert row.n == len(errors)
    assert abs(row.bias) <= row.mape
