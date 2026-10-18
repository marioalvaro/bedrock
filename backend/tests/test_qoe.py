"""Quality-of-earnings flags (FR-ANL-05): rule values, severities, YAML validation, overrides."""

import functools
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from bedrock.analysis.formula import Formula, parse
from bedrock.analysis.qoe import (
    DEFAULT_RULES_PATH,
    Direction,
    FlagRow,
    FlagTable,
    Rule,
    RuleError,
    RuleUnit,
    Severity,
    Thresholds,
    effective_rules,
    evaluate_flags,
    formula_names,
    load_rules,
    validate_thresholds,
)
from bedrock.mapping.config import load_canonical_items
from bedrock.ratios.calculator import RatioInputs
from bedrock.statements.build import RATIO_PLACES, Row, StatementTable, build_statement
from bedrock.statements.periods import Period
from tests.statements_pipeline import run_pipeline

KINDS = {i.code: i.kind for i in load_canonical_items()}

Values = list[Decimal | int | str | None]


def D(value: Decimal | int | str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def fy(year: int) -> Period:
    return Period(
        f"FY{year}", f"FY{year % 100}", year, "FY", date(year - 1, 1, 1), date(year, 1, 1)
    )


def quarter(year: int, q: int) -> Period:
    return Period(
        f"FY{year}Q{q}", f"Q{q} FY{year % 100}", year, f"Q{q}", date(year, 1, 1), date(year, 3, q)
    )


def ttm(year: int, q: int) -> Period:
    return Period(
        f"TTM-FY{year}Q{q}", f"TTM Q{q}", year, f"Q{q}", date(year - 1, 1, 1), date(year, 3, q)
    )


def table(
    statement: str, freq: str, periods: list[Period], rows: dict[str, Values]
) -> StatementTable:
    built = []
    for code, vals in rows.items():
        assert len(vals) == len(periods), code
        n = len(vals)
        built.append(
            Row(
                code,
                code,
                "USD",
                KINDS[code],
                0,
                [D(v) for v in vals],
                [None] * n,
                [None] * n,
                [None] * n,
            )
        )
    return StatementTable(statement, freq, periods, built, None, [])


def annual_inputs(
    periods: list[Period],
    income: dict[str, Values] | None = None,
    cash_flow: dict[str, Values] | None = None,
    balance: dict[str, Values] | None = None,
) -> RatioInputs:
    return RatioInputs(
        income=table("IS", "annual", periods, income or {}),
        cash_flow=table("CF", "annual", periods, cash_flow or {}),
        balance=table("BS", "annual", periods, balance or {}),
    )


# The ERD rule table, in order: code, direction, unit, warn, alert.
ERD_TABLE: list[tuple[str, Direction, RuleUnit, str | None, str | None]] = [
    ("accruals_ratio", "above", "pct", "0.05", "0.10"),
    ("cfo_to_net_income", "below", "x", "0.8", "0"),
    ("receivables_vs_revenue", "above", "pct", "0.10", "0.20"),
    ("inventory_vs_revenue", "above", "pct", "0.10", "0.20"),
    ("goodwill_to_assets", "above", "pct", "0.30", "0.50"),
    ("goodwill_impairment", "above", "pct", "0", None),
    ("sbc_to_revenue", "above", "pct", "0.05", "0.10"),
    ("sbc_to_cfo", "above", "pct", "0.15", "0.30"),
]
CODES = [code for code, *_ in ERD_TABLE]


def rule(
    code: str,
    direction: Direction = "above",
    warn: str | None = None,
    alert: str | None = None,
    unit: RuleUnit = "pct",
) -> Rule:
    levels = Thresholds(D(warn), D(alert))
    return Rule(code, code, f"{code} formula", direction, unit, levels, levels)


def row_of(result: FlagTable, code: str) -> tuple[list[Decimal | None], list[Severity | None]]:
    found = next(r for r in result.rows if r.code == code)
    return found.values, found.severity


def flag_values(inputs: RatioInputs, code: str) -> dict[str, Decimal | None]:
    """The rule's values by period key, evaluated alone: a period where it is None is trimmed."""
    result = evaluate_flags(inputs, [rule(code)], "annual")
    return dict(zip([p.key for p in result.periods], row_of(result, code)[0], strict=True))


YEARS = [fy(2022), fy(2023), fy(2024)]

# --- rule values (annual) ------------------------------------------------------------------------


def test_accruals_ratio_is_accruals_over_average_assets() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"net_income": [100, 100, 100]},
        cash_flow={"cfo": [80, 80, 130]},
        balance={"total_assets": [400, 600, 400]},
    )
    # FY2022 has no FY2021 balance; FY2023: 20 / 500; FY2024: -30 / 500
    assert flag_values(inputs, "accruals_ratio") == {
        "FY2023": Decimal("0.04"),
        "FY2024": Decimal("-0.06"),
    }


def test_accruals_ratio_is_null_when_an_operand_is_missing() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"net_income": [100, None, 100]},
        cash_flow={"cfo": [80, 80, 80]},
        balance={"total_assets": [400, 600, 400]},
    )
    assert flag_values(inputs, "accruals_ratio") == {"FY2024": Decimal("0.04")}


def test_cfo_to_net_income() -> None:
    inputs = annual_inputs(
        YEARS, income={"net_income": [100, 0, -50]}, cash_flow={"cfo": [80, 80, 80]}
    )
    # null when net income is zero or negative
    assert flag_values(inputs, "cfo_to_net_income") == {"FY2022": Decimal("0.8")}


def test_cfo_to_net_income_is_null_when_cfo_is_missing() -> None:
    inputs = annual_inputs(YEARS, income={"net_income": [100, 100, 100]}, cash_flow={})
    assert flag_values(inputs, "cfo_to_net_income") == {}


def test_receivables_vs_revenue_is_the_difference_of_yoys() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [1000, 1000, 1100]},
        balance={"receivables": [100, 100, 130]},
    )
    # FY2022 has no prior year; FY2023: 0 - 0; FY2024: 0.3 - 0.1
    assert flag_values(inputs, "receivables_vs_revenue") == {
        "FY2023": Decimal(0),
        "FY2024": Decimal("0.2"),
    }


def test_receivables_vs_revenue_is_null_without_a_positive_prior() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [1000, 0, 1100]},
        balance={"receivables": [100, 100, 130]},
    )
    # FY2023: 0 - (-1); FY2024's revenue YoY has a zero prior
    assert flag_values(inputs, "receivables_vs_revenue") == {"FY2023": Decimal(1)}


def test_inventory_vs_revenue_is_the_difference_of_yoys() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [1000, 1200, 1200]},
        balance={"inventory": [50, 55, None]},
    )
    # FY2023: 0.1 - 0.2; FY2024 has no inventory
    assert flag_values(inputs, "inventory_vs_revenue") == {"FY2023": Decimal("-0.1")}


def test_goodwill_to_assets() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [1, 1, 1]},
        balance={"goodwill": [30, None, 30], "total_assets": [100, 100, 0]},
    )
    assert flag_values(inputs, "goodwill_to_assets") == {"FY2022": Decimal("0.3")}


def test_goodwill_impairment_is_over_the_prior_year_goodwill() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"goodwill_impairment": [None, 10, None]},
        balance={"goodwill": [200, 190, 190]},
    )
    # FY2022 has no prior goodwill; FY2023: 10 / 200; FY2024: nothing reported -> 0
    assert flag_values(inputs, "goodwill_impairment") == {
        "FY2023": Decimal("0.05"),
        "FY2024": Decimal(0),
    }


def test_goodwill_impairment_is_null_without_positive_prior_goodwill() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"goodwill_impairment": [None, None, 5]},
        balance={"goodwill": [0, None, 100]},
    )
    assert flag_values(inputs, "goodwill_impairment") == {}


def test_no_impairment_without_current_goodwill_is_null() -> None:
    periods = [fy(2021), *YEARS]
    inputs = annual_inputs(
        periods,
        income={"goodwill_impairment": [None, None, None, None]},
        balance={"goodwill": [100, None, 100, 0]},
    )
    # FY2022: current goodwill missing; FY2023: prior missing; FY2024: current goodwill is 0
    assert flag_values(inputs, "goodwill_impairment") == {}


def test_a_reported_impairment_ignores_the_current_goodwill() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"goodwill_impairment": [None, 200, 10]},
        balance={"goodwill": [200, 0, None]},
    )
    # FY2023: 200 / 200 with goodwill written off to 0; FY2024: prior goodwill is 0
    assert flag_values(inputs, "goodwill_impairment") == {"FY2023": Decimal(1)}


def test_a_trailing_empty_period_is_trimmed_not_shown_as_no_impairment() -> None:
    periods = [*YEARS, fy(2025)]
    inputs = annual_inputs(
        periods,
        income={"revenue": [100, 100, 100, None]},
        cash_flow={"sbc": [1, 1, 1, None]},
        balance={"goodwill": [50, 50, 50, None], "total_assets": [500, 500, 500, None]},
    )
    result = evaluate_flags(inputs, load_rules(), "annual")
    assert [p.key for p in result.periods] == ["FY2022", "FY2023", "FY2024"]
    assert row_of(result, "goodwill_impairment") == (
        [None, Decimal(0), Decimal(0)],
        [None, "none", "none"],
    )


def test_sbc_to_revenue() -> None:
    inputs = annual_inputs(
        YEARS, income={"revenue": [1000, 0, 1000]}, cash_flow={"sbc": [50, 50, None]}
    )
    assert flag_values(inputs, "sbc_to_revenue") == {"FY2022": Decimal("0.05")}


def test_sbc_to_cfo_is_null_unless_cfo_is_positive() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [1, 1, 1]},
        cash_flow={"sbc": [30, 30, 30], "cfo": [200, 0, -100]},
    )
    assert flag_values(inputs, "sbc_to_cfo") == {"FY2022": Decimal("0.15")}


def test_values_are_quantized_to_ratio_places() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [3, 3, 3]},
        balance={"goodwill": [1, 2, 1], "total_assets": [3] * 3},
    )
    assert list(flag_values(inputs, "goodwill_to_assets").values()) == [
        Decimal("0.333333"),
        Decimal("0.666667"),
        Decimal("0.333333"),
    ]


GRID_NUMERATORS = [None, "-5", "0", "7"]
GRID_DENOMINATORS = [None, "-10", "0", "3", "1000"]
# code -> (numerator line, its statement, denominator line, its statement)
GRID_RULES = {
    "sbc_to_revenue": ("sbc", "CF", "revenue", "IS"),
    "sbc_to_cfo": ("sbc", "CF", "cfo", "CF"),
    "goodwill_to_assets": ("goodwill", "BS", "total_assets", "BS"),
}


@pytest.mark.parametrize("code", list(GRID_RULES))
@pytest.mark.parametrize("numerator", GRID_NUMERATORS)
@pytest.mark.parametrize("denominator", GRID_DENOMINATORS)
def test_rule_values_match_their_inputs_over_grid(
    code: str, numerator: str | None, denominator: str | None
) -> None:
    num_line, num_stmt, den_line, den_stmt = GRID_RULES[code]
    lines: dict[str, dict[str, Values]] = {"IS": {}, "CF": {}, "BS": {}}
    lines[num_stmt][num_line] = [numerator]
    lines[den_stmt][den_line] = [denominator]
    inputs = annual_inputs([fy(2024)], lines["IS"], lines["CF"], lines["BS"])

    value = flag_values(inputs, code).get("FY2024")

    num, den = D(numerator), D(denominator)
    if num is None or den is None or den <= 0:
        assert value is None
    else:
        assert value is not None
        assert abs(value * den - num) <= Decimal("1e-6") * den


@pytest.mark.parametrize("code", ["receivables_vs_revenue", "inventory_vs_revenue"])
@pytest.mark.parametrize("prior", [0, -10])
def test_yoy_gap_is_null_when_the_line_prior_is_not_positive(code: str, prior: int) -> None:
    line = code.removesuffix("_vs_revenue")
    inputs = annual_inputs(
        [fy(2023), fy(2024)],
        income={"revenue": [100, 110]},
        balance={line: [prior, 100]},
    )
    assert flag_values(inputs, code) == {}


def test_inventory_growing_faster_than_revenue_warns_then_alerts() -> None:
    periods = [fy(2020), fy(2021), fy(2022), fy(2023)]
    inputs = annual_inputs(
        periods,
        income={"revenue": [100, 100, 100, 100]},
        # inventory YoY: 0.1, 0.15, 0.25 against flat revenue
        balance={"inventory": ["100", "110", "126.5", "158.125"]},
    )
    shipped = [r for r in load_rules() if r.code == "inventory_vs_revenue"]
    result = evaluate_flags(inputs, shipped, "annual")
    assert row_of(result, "inventory_vs_revenue") == (
        [Decimal("0.1"), Decimal("0.15"), Decimal("0.25")],
        ["none", "warn", "alert"],
    )


# --- severities ----------------------------------------------------------------------------------


def goodwill_share(*shares: str) -> RatioInputs:
    """One FY per share, goodwill / total_assets equal to it (total assets 1,000,000)."""
    periods = [fy(2000 + i) for i in range(len(shares))]
    million = Decimal(1_000_000)
    return annual_inputs(
        periods,
        balance={
            "goodwill": [Decimal(s) * million for s in shares],
            "total_assets": [million] * len(shares),
        },
    )


def test_above_flags_strictly_above_each_level() -> None:
    inputs = goodwill_share("0.299999", "0.3", "0.300001", "0.5", "0.500001")
    result = evaluate_flags(inputs, [rule("goodwill_to_assets", "above", "0.3", "0.5")], "annual")
    assert row_of(result, "goodwill_to_assets")[1] == ["none", "none", "warn", "warn", "alert"]


def test_below_flags_strictly_below_each_level() -> None:
    periods = [fy(2000 + i) for i in range(5)]
    million = 1_000_000
    inputs = annual_inputs(
        periods,
        income={"net_income": [million] * 5},
        cash_flow={"cfo": [800_001, 800_000, 799_999, 0, -1]},
    )
    result = evaluate_flags(inputs, [rule("cfo_to_net_income", "below", "0.8", "0", "x")], "annual")
    values, severity = row_of(result, "cfo_to_net_income")
    assert values == [
        Decimal("0.800001"),
        Decimal("0.8"),
        Decimal("0.799999"),
        Decimal(0),
        Decimal("-0.000001"),
    ]
    assert severity == ["none", "none", "warn", "warn", "alert"]


def test_alert_wins_when_warn_is_missing() -> None:
    inputs = goodwill_share("0.2", "0.6")
    result = evaluate_flags(inputs, [rule("goodwill_to_assets", "above", None, "0.5")], "annual")
    assert row_of(result, "goodwill_to_assets")[1] == ["none", "alert"]


def test_a_rule_without_levels_never_flags() -> None:
    inputs = goodwill_share("0.9")
    result = evaluate_flags(inputs, [rule("goodwill_to_assets")], "annual")
    assert row_of(result, "goodwill_to_assets")[1] == ["none"]


def test_severity_is_judged_on_the_quantized_value() -> None:
    # 0.3000004 quantizes to 0.300000, which is not above 0.3
    inputs = goodwill_share("0.3000004", "0.3000006")
    result = evaluate_flags(inputs, [rule("goodwill_to_assets", "above", "0.3", None)], "annual")
    assert row_of(result, "goodwill_to_assets") == (
        [Decimal("0.3"), Decimal("0.300001")],
        ["none", "warn"],
    )


def test_a_null_value_has_a_null_severity() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [100, 100, 100]},
        cash_flow={"sbc": [1, 1, 1]},
        balance={"goodwill": [30, None, 60], "total_assets": [100, 100, 100]},
    )
    rules = [rule("goodwill_to_assets", "above", "0.3", "0.5"), rule("sbc_to_revenue")]
    result = evaluate_flags(inputs, rules, "annual")
    assert row_of(result, "goodwill_to_assets") == (
        [Decimal("0.3"), None, Decimal("0.6")],
        ["none", None, "alert"],
    )


def test_an_impairment_warns_and_no_impairment_does_not() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"goodwill_impairment": [None, 10, None]},
        balance={"goodwill": [200, 190, 190]},
    )
    shipped = [r for r in load_rules() if r.code == "goodwill_impairment"]
    result = evaluate_flags(inputs, shipped, "annual")
    assert [p.key for p in result.periods] == ["FY2023", "FY2024"]
    assert row_of(result, "goodwill_impairment") == (
        [Decimal("0.05"), Decimal(0)],
        ["warn", "none"],
    )


SEVERITY_RANK = {"none": 0, "warn": 1, "alert": 2}
GRID = [Decimal(n) / 100 for n in range(-20, 121, 5)]


@pytest.mark.parametrize("direction", ["above", "below"])
@pytest.mark.parametrize(
    ("warn", "alert"),
    [("0.3", "0.6"), ("0.3", "0.3"), ("0.3", None), (None, "0.6"), (None, None)],
)
def test_severity_is_monotone_in_the_value(
    direction: Direction, warn: str | None, alert: str | None
) -> None:
    if direction == "below" and warn is not None and alert is not None:
        warn, alert = alert, warn  # below: alert <= warn
    shares = [str(v) for v in GRID]
    inputs = goodwill_share(*shares)
    result = evaluate_flags(inputs, [rule("goodwill_to_assets", direction, warn, alert)], "annual")
    values, severity = row_of(result, "goodwill_to_assets")
    ranks = [SEVERITY_RANK[s] for s in severity if s is not None]
    assert len(ranks) == len(GRID)
    expected = sorted(ranks) if direction == "above" else sorted(ranks, reverse=True)
    assert ranks == expected
    for value, sev in zip(values, severity, strict=True):
        assert value is not None
        if sev == "alert" and warn is not None:
            level = Decimal(warn)
            assert value > level if direction == "above" else value < level


# --- periods and frequency -----------------------------------------------------------------------


def test_rows_follow_the_rules_with_their_metadata() -> None:
    rules = load_rules()
    inputs = goodwill_share("0.1")
    result = evaluate_flags(inputs, rules, "annual")
    assert result.freq == "annual"
    assert [r.code for r in result.rows] == CODES
    for row, r in zip(result.rows, rules, strict=True):
        assert (row.label, row.rule, row.direction, row.unit, row.thresholds) == (
            r.label,
            r.rule,
            r.direction,
            r.unit,
            r.thresholds,
        )
        assert len(row.values) == len(row.severity) == len(result.periods)


def test_a_period_without_any_flag_value_is_left_out() -> None:
    periods = [fy(2021), fy(2022), fy(2023)]
    inputs = annual_inputs(
        periods,
        income={"revenue": [None, 100, 100]},
        cash_flow={"sbc": [None, 5, None]},
        balance={"goodwill": [None, None, 10], "total_assets": [None, None, 100]},
    )
    result = evaluate_flags(inputs, load_rules(), "annual")
    assert [p.key for p in result.periods] == ["FY2022", "FY2023"]
    assert row_of(result, "sbc_to_revenue")[0] == [Decimal("0.05"), None]
    assert row_of(result, "goodwill_to_assets")[0] == [None, Decimal("0.1")]


def test_ttm_without_the_quarterly_income_is_an_error() -> None:
    with pytest.raises(ValueError, match="quarterly"):
        evaluate_flags(annual_inputs(YEARS), load_rules(), "ttm")


def test_an_unknown_rule_code_is_a_rule_error() -> None:
    with pytest.raises(RuleError, match="no_such_rule"):
        evaluate_flags(annual_inputs(YEARS), [rule("no_such_rule")], "annual")


def ttm_inputs() -> RatioInputs:
    windows = [ttm(2023, 2), ttm(2023, 3), ttm(2024, 2)]
    quarters = [quarter(2023, 2), quarter(2023, 3), quarter(2024, 2)]
    return RatioInputs(
        income=table(
            "IS",
            "ttm",
            windows,
            {"revenue": [1000, 1050, 1100], "goodwill_impairment": [None, None, 20]},
        ),
        cash_flow=table("CF", "ttm", windows, {}),
        balance=table(
            "BS",
            "quarterly",
            quarters,
            {"receivables": [100, 500, 130], "goodwill": [400, 1, 300]},
        ),
        quarterly_income=table("IS", "quarterly", quarters, {"revenue": [250, 260, 275]}),
    )


def test_ttm_yoy_compares_the_same_quarter_a_year_earlier() -> None:
    result = evaluate_flags(ttm_inputs(), [rule("receivables_vs_revenue")], "ttm")
    assert result.freq == "ttm"
    # Q2 FY2024 against Q2 FY2023: receivables 0.3, revenue 0.1 (Q3 FY2023 is ignored)
    assert [p.key for p in result.periods] == ["TTM-FY2024Q2"]
    assert row_of(result, "receivables_vs_revenue")[0] == [Decimal("0.2")]


def test_ttm_impairment_is_over_goodwill_where_the_window_starts() -> None:
    result = evaluate_flags(ttm_inputs(), [rule("goodwill_impairment")], "ttm")
    # 20 / goodwill at Q2 FY2023 (400), not the quarter before (Q3 FY2023 is 1)
    assert row_of(result, "goodwill_impairment")[0] == [Decimal("0.05")]


def test_ttm_accruals_average_quarter_end_assets_a_year_apart() -> None:
    windows = [ttm(2023, 2), ttm(2024, 1), ttm(2024, 2)]
    quarters = [quarter(2023, 2), quarter(2024, 1), quarter(2024, 2)]
    inputs = RatioInputs(
        income=table("IS", "ttm", windows, {"net_income": [100, 100, 100]}),
        cash_flow=table("CF", "ttm", windows, {"cfo": [80, 80, 80]}),
        balance=table("BS", "quarterly", quarters, {"total_assets": [400, 9999, 600]}),
        quarterly_income=table("IS", "quarterly", quarters, {"net_income": [25, 25, 25]}),
    )
    result = evaluate_flags(inputs, [rule("accruals_ratio")], "ttm")
    # (100 - 80) / avg(Q2 FY2023 400, Q2 FY2024 600); Q1 FY2024 (9999) is not an end
    assert [p.key for p in result.periods] == ["TTM-FY2024Q2"]
    assert row_of(result, "accruals_ratio")[0] == [Decimal("0.04")]


# --- validate_thresholds -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "warn", "alert"),
    [
        ("above", "0.1", "0.2"),
        ("above", "0.1", "0.1"),
        ("below", "0.8", "0"),
        ("below", "0.8", "0.8"),
        ("above", None, "0.2"),
        ("above", "0.1", None),
        ("below", None, None),
    ],
)
def test_thresholds_in_order_are_valid(
    direction: Direction, warn: str | None, alert: str | None
) -> None:
    validate_thresholds("r", direction, Thresholds(D(warn), D(alert)))


@pytest.mark.parametrize(
    ("direction", "warn", "alert"),
    [
        ("above", "0.2", "0.1"),
        ("below", "0", "0.8"),
        ("above", "Infinity", None),
        ("below", None, "NaN"),
        ("above", "0.1", "-Infinity"),
    ],
)
def test_thresholds_out_of_order_or_not_finite_are_errors(
    direction: Direction, warn: str | None, alert: str | None
) -> None:
    with pytest.raises(RuleError, match="my_rule"):
        validate_thresholds("my_rule", direction, Thresholds(D(warn), D(alert)))


@pytest.mark.parametrize(
    "level",
    ["999999.9999999999", "-999999.9999999999", "0.0000000001", "0.1000000000", "1E+5"],
)
def test_levels_inside_the_storable_range_are_valid(level: str) -> None:
    validate_thresholds("r", "above", Thresholds(Decimal(level), None))
    validate_thresholds("r", "above", Thresholds(None, Decimal(level)))


@pytest.mark.parametrize(
    "level",
    ["1000000", "-1000000", "1000000.5", "1E+30", "-1E+30", "1E+400", "0.00000000001"],
)
def test_levels_out_of_the_storable_range_are_errors(level: str) -> None:
    # Gotcha G21: |level| >= 10**6, or more than 10 decimal places, cannot go in Numeric(28, 10)
    for levels in (Thresholds(Decimal(level), None), Thresholds(None, Decimal(level))):
        with pytest.raises(RuleError, match="my_rule"):
            validate_thresholds("my_rule", "below", levels)


# --- load_rules ----------------------------------------------------------------------------------


def test_the_shipped_rules_match_the_erd_table() -> None:
    rules = load_rules()
    assert DEFAULT_RULES_PATH.name == "qoe_rules.yaml"
    assert [(r.code, r.direction, r.unit, r.thresholds) for r in rules] == [
        (code, direction, unit, Thresholds(D(warn), D(alert)))
        for code, direction, unit, warn, alert in ERD_TABLE
    ]
    for r in rules:
        assert r.thresholds == r.default
        assert r.label and r.rule


def test_shipped_thresholds_are_exact_decimals() -> None:
    accruals = load_rules()[0]
    assert accruals.thresholds.warn == Decimal("0.05")
    assert str(accruals.thresholds.warn) == "0.05"


def valid_entries() -> list[dict[str, Any]]:
    return [
        {
            "code": code,
            "label": f"Label {code}",
            "rule": f"rule {code}",
            "direction": direction,
            "unit": unit,
            "warn": None if warn is None else float(warn),
            "alert": None if alert is None else float(alert),
        }
        for code, direction, unit, warn, alert in ERD_TABLE
    ]


def write(tmp_path: Path, content: Any) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(content, sort_keys=False))
    return path


def test_a_valid_file_loads_in_file_order(tmp_path: Path) -> None:
    entries = list(reversed(valid_entries()))
    rules = load_rules(write(tmp_path, entries))
    assert [r.code for r in rules] == list(reversed(CODES))
    assert rules[-1].label == "Label accruals_ratio"
    assert rules[-1].rule == "rule accruals_ratio"


def broken(mutate: str) -> list[dict[str, Any]] | dict[str, Any]:
    entries = valid_entries()
    first = entries[0]
    if mutate == "duplicate":
        entries.append(dict(first))
    elif mutate == "direction":
        first["direction"] = "sideways"
    elif mutate == "unit":
        first["unit"] = "days"
    elif mutate == "missing_key":
        del first["label"]
    elif mutate == "unknown_key":
        first["colour"] = "red"
    elif mutate == "above_order":
        first["warn"], first["alert"] = 0.2, 0.1
    elif mutate == "below_order":
        entries[1]["warn"], entries[1]["alert"] = 0, 0.8
    elif mutate == "no_value_function":
        first["code"] = "made_up_rule"
    elif mutate == "missing_rule":
        entries.pop(0)
    elif mutate == "non_numeric":
        first["warn"] = "lots"
    elif mutate == "boolean":
        first["alert"] = True
    elif mutate == "infinite":
        first["alert"] = float("inf")
    elif mutate == "mapping_file":
        return {"rules": entries}
    elif mutate == "entry_not_mapping":
        # deliberately not a mapping: the loader must reject it (the list type is the valid shape)
        entries[0] = "accruals_ratio"  # type: ignore[call-overload]
    return entries


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        ("duplicate", "accruals_ratio"),
        ("direction", "accruals_ratio"),
        ("unit", "accruals_ratio"),
        ("missing_key", "accruals_ratio"),
        ("unknown_key", "accruals_ratio"),
        ("above_order", "accruals_ratio"),
        ("below_order", "cfo_to_net_income"),
        ("no_value_function", "made_up_rule"),
        ("missing_rule", "accruals_ratio"),
        ("non_numeric", "accruals_ratio"),
        ("boolean", "accruals_ratio"),
        ("infinite", "accruals_ratio"),
        ("mapping_file", "list"),
        ("entry_not_mapping", "mapping"),
    ],
)
def test_an_invalid_file_is_a_rule_error(tmp_path: Path, mutate: str, message: str) -> None:
    with pytest.raises(RuleError, match=message):
        load_rules(write(tmp_path, broken(mutate)))


def test_an_empty_file_is_a_rule_error(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("")
    with pytest.raises(RuleError, match="list"):
        load_rules(path)


# --- effective_rules -----------------------------------------------------------------------------


def test_an_override_replaces_the_whole_pair() -> None:
    rules = load_rules()
    override = Thresholds(Decimal("0.07"), None)
    result = effective_rules(rules, {"accruals_ratio": override})
    assert result[0].thresholds == override
    assert result[0].default == Thresholds(Decimal("0.05"), Decimal("0.10"))
    assert result[1:] == rules[1:]


def test_an_override_of_an_unknown_code_is_ignored() -> None:
    rules = load_rules()
    assert effective_rules(rules, {"nope": Thresholds(None, None)}) == rules


def test_overridden_thresholds_drive_the_severity() -> None:
    inputs = goodwill_share("0.4")
    rules = [rule("goodwill_to_assets", "above", "0.3", "0.5")]
    result = evaluate_flags(
        inputs, effective_rules(rules, {"goodwill_to_assets": Thresholds(None, None)}), "annual"
    )
    found = result.rows[0]
    assert found.severity == ["none"]
    assert found.thresholds == Thresholds(None, None)


def test_values_are_on_the_ratio_grid() -> None:
    result = evaluate_flags(goodwill_share("0.123456789"), load_rules(), "annual")
    for row in result.rows:
        for value in row.values:
            assert value is None or value == value.quantize(RATIO_PLACES)


# --- custom rules and formula levels (FR-ANL-10) -------------------------------------------------


def custom(
    code: str,
    text: str,
    warn: str | None = None,
    alert: str | None = None,
    direction: Direction = "above",
    error: str | None = None,
) -> Rule:
    def level(raw: str | None) -> Decimal | Formula | None:
        if raw is None:
            return None
        try:
            return Decimal(raw)
        except ArithmeticError:
            return parse(raw, formula_names())

    levels = Thresholds(level(warn), level(alert))
    formula = None if error else parse(text, formula_names())
    return Rule(
        code,
        code,
        text,
        direction,
        "pct",
        levels,
        levels,
        formula=formula,
        custom=True,
        error=error,
    )


def full_row(result: FlagTable, code: str) -> FlagRow:
    return next(r for r in result.rows if r.code == code)


def test_a_custom_rule_value_is_its_formula_quantized() -> None:
    inputs = annual_inputs(YEARS, income={"revenue": [3, 3, 3]}, balance={"goodwill": [1, 2, 1]})
    result = evaluate_flags(inputs, [custom("custom_1", "goodwill / revenue")], "annual")
    row = full_row(result, "custom_1")
    assert row.values == [Decimal("0.333333"), Decimal("0.666667"), Decimal("0.333333")]
    assert (row.custom, row.error) == (True, None)
    assert row.severity == ["none"] * 3


def test_rows_follow_the_given_rules_order_with_customs_mixed_in() -> None:
    inputs = goodwill_share("0.1")
    rules = [custom("custom_2", "revenue"), rule("goodwill_to_assets"), custom("custom_1", "1")]
    result = evaluate_flags(inputs, rules, "annual")
    assert [r.code for r in result.rows] == ["custom_2", "goodwill_to_assets", "custom_1"]
    assert [r.custom for r in result.rows] == [True, False, True]


def test_a_period_only_a_custom_rule_has_a_value_for_is_kept() -> None:
    inputs = annual_inputs(
        YEARS, income={"revenue": [None, 5, 5]}, balance={"goodwill": [1, None, None]}
    )
    builtin = rule("goodwill_to_assets")
    assert [p.key for p in evaluate_flags(inputs, [builtin], "annual").periods] == []
    result = evaluate_flags(inputs, [builtin, custom("custom_1", "revenue")], "annual")
    assert [p.key for p in result.periods] == ["FY2023", "FY2024"]
    assert full_row(result, "custom_1").values == [Decimal(5), Decimal(5)]


def test_a_rule_with_an_error_has_only_nulls_and_keeps_no_period_alive() -> None:
    inputs = goodwill_share("0.1", "0.2")
    broken_rule = custom("custom_1", "bad", "0.1", "0.2", error="Unknown name 'bad' at 0")
    result = evaluate_flags(inputs, [broken_rule], "annual")
    assert result.periods == []
    both = evaluate_flags(inputs, [rule("goodwill_to_assets"), broken_rule], "annual")
    row = full_row(both, "custom_1")
    assert row.values == row.severity == row.warn_levels == row.alert_levels == [None, None]
    assert row.error == "Unknown name 'bad' at 0"
    assert row.thresholds == broken_rule.thresholds


def test_a_built_in_rule_with_an_error_has_only_nulls() -> None:
    healthy = rule("sbc_to_revenue", warn="0.05", alert="0.1")
    keep_alive = custom("custom_1", "revenue")
    inputs = sbc_inputs()
    ok = full_row(evaluate_flags(inputs, [healthy, keep_alive], "annual"), "sbc_to_revenue")
    assert any(v is not None for v in ok.values)  # non-vacuity: the error is what nulls it

    broken_rule = replace(healthy, error="x")
    row = full_row(evaluate_flags(inputs, [broken_rule, keep_alive], "annual"), "sbc_to_revenue")

    assert len(row.values) == len(ok.values)
    assert all(v is None for v in row.values + row.severity + row.warn_levels + row.alert_levels)
    assert row.error == "x"


def test_a_custom_rule_with_neither_formula_nor_error_is_a_rule_error() -> None:
    bare = Rule(
        "custom_1",
        "x",
        "x",
        "above",
        "pct",
        Thresholds(None, None),
        Thresholds(None, None),
        custom=True,
    )
    with pytest.raises(RuleError, match="custom_1"):
        evaluate_flags(annual_inputs(YEARS), [bare], "annual")


def test_number_levels_are_repeated_per_period() -> None:
    result = evaluate_flags(
        goodwill_share("0.1", "0.4"), [rule("goodwill_to_assets", "above", "0.3", "0.5")], "annual"
    )
    row = full_row(result, "goodwill_to_assets")
    assert row.warn_levels == [Decimal("0.3")] * 2
    assert row.alert_levels == [Decimal("0.5")] * 2
    assert row.severity == ["none", "warn"]


def test_a_missing_level_is_none_in_every_period() -> None:
    result = evaluate_flags(goodwill_share("0.1"), [rule("goodwill_to_assets")], "annual")
    row = full_row(result, "goodwill_to_assets")
    assert row.warn_levels == row.alert_levels == [None]


def test_levels_are_none_where_the_value_is_none() -> None:
    inputs = annual_inputs(
        YEARS,
        income={"revenue": [100, 100, 100]},
        balance={"goodwill": [30, None, 60], "total_assets": [100, 100, 100]},
    )
    keep_alive = custom("custom_1", "revenue")
    rules = [rule("goodwill_to_assets", "above", "0.3", "0.5"), keep_alive]
    row = full_row(evaluate_flags(inputs, rules, "annual"), "goodwill_to_assets")
    assert row.warn_levels == [Decimal("0.3"), None, Decimal("0.3")]
    assert row.alert_levels == [Decimal("0.5"), None, Decimal("0.5")]


def sbc_inputs() -> RatioInputs:
    return annual_inputs(
        [fy(2022), fy(2023), fy(2024), fy(2025)],
        income={"revenue": [100, 100, 100, 100]},
        cash_flow={"sbc": [5, 5, 8, 20]},
    )


def test_a_formula_level_is_judged_per_period() -> None:
    # the level is last year's sbc_to_revenue + 1 point; FY2022 has no previous year
    rules = [
        Rule(
            "sbc_to_revenue",
            "sbc",
            "sbc / revenue",
            "above",
            "pct",
            Thresholds(parse("prev(sbc / revenue) + 1%", formula_names()), None),
            Thresholds(None, None),
        )
    ]
    result = evaluate_flags(sbc_inputs(), rules, "annual")
    row = full_row(result, "sbc_to_revenue")
    assert row.values == [Decimal("0.05"), Decimal("0.05"), Decimal("0.08"), Decimal("0.2")]
    assert row.warn_levels == [None, Decimal("0.06"), Decimal("0.06"), Decimal("0.09")]
    assert row.alert_levels == [None] * 4
    assert row.severity == ["none", "none", "warn", "warn"]


def test_an_alert_formula_wins_over_the_warn_formula() -> None:
    f = functools.partial(parse, known_names=formula_names())
    levels = Thresholds(f("prev(sbc / revenue) + 1%"), f("prev(sbc / revenue) + 5%"))
    rules = [Rule("sbc_to_revenue", "s", "s", "above", "pct", levels, levels)]
    row = full_row(evaluate_flags(sbc_inputs(), rules, "annual"), "sbc_to_revenue")
    assert row.alert_levels == [None, Decimal("0.10"), Decimal("0.10"), Decimal("0.13")]
    assert row.severity == ["none", "none", "warn", "alert"]


def test_a_formula_level_is_quantized() -> None:
    levels = Thresholds(parse("1 / 3", formula_names()), None)
    rules = [Rule("sbc_to_revenue", "s", "s", "above", "pct", levels, levels)]
    row = full_row(evaluate_flags(sbc_inputs(), rules, "annual"), "sbc_to_revenue")
    assert row.warn_levels == [Decimal("0.333333")] * 4


def test_a_below_rule_with_a_formula_level() -> None:
    levels = Thresholds(parse("sbc / revenue + 1%", formula_names()), None)
    rules = [Rule("sbc_to_revenue", "s", "s", "below", "pct", levels, levels)]
    row = full_row(evaluate_flags(sbc_inputs(), rules, "annual"), "sbc_to_revenue")
    assert row.severity == ["warn"] * 4  # the value is below its own level plus 1 point


def test_a_value_too_large_to_quantize_is_none() -> None:
    inputs = annual_inputs(YEARS, income={"revenue": [10**12, 5, 10**12]})
    rules = [custom("custom_1", "revenue * revenue * revenue"), custom("custom_2", "revenue")]
    result = evaluate_flags(inputs, rules, "annual")
    row = full_row(result, "custom_1")
    assert row.values == [None, Decimal(125), None]
    assert row.severity == [None, "none", None]


def test_a_level_too_large_to_quantize_never_flags() -> None:
    levels = Thresholds(parse("revenue * revenue * revenue", formula_names()), None)
    rules = [Rule("sbc_to_revenue", "s", "s", "above", "pct", levels, levels)]
    inputs = annual_inputs([fy(2024)], income={"revenue": [10**12]}, cash_flow={"sbc": [1]})
    row = full_row(evaluate_flags(inputs, rules, "annual"), "sbc_to_revenue")
    assert row.warn_levels == [None]
    assert row.severity == ["none"]


def test_validate_thresholds_skips_formula_levels() -> None:
    f = parse("revenue", formula_names())
    validate_thresholds("r", "above", Thresholds(Decimal("0.9"), f))
    validate_thresholds("r", "above", Thresholds(f, Decimal("0.1")))
    validate_thresholds("r", "below", Thresholds(f, f))
    with pytest.raises(RuleError, match="r:"):
        validate_thresholds("r", "above", Thresholds(f, Decimal("1000000")))
    with pytest.raises(RuleError, match="r:"):
        validate_thresholds("r", "above", Thresholds(Decimal("1E+30"), f))


def test_formula_names_are_lines_metrics_and_ratios_but_not_rule_codes() -> None:
    names = formula_names()
    assert {"revenue", "ebitda", "roe", "sbc", "net_income"} <= names
    # goodwill_impairment is both a QoE rule code and a canonical line, so it is a name
    shipped = {r.code for r in load_rules()} - {"goodwill_impairment"}
    assert shipped & names == set(), shipped & names


# Golden invariant: a custom rule written as the built-in's formula gives the same values.
GOLDEN = {
    "accruals_ratio": "(net_income - cfo) / avg(total_assets)",
    "receivables_vs_revenue": "yoy(receivables) - yoy(revenue)",
    "sbc_to_revenue": "sbc / revenue",
}


@functools.cache
def pipeline_inputs(ticker: str, freq: str) -> RatioInputs:
    p = run_pipeline(ticker)
    if freq == "annual":
        return RatioInputs(p.annual["IS"], p.annual["CF"], p.annual["BS"])
    return RatioInputs(
        build_statement(p.canonical, p.items, "IS", "ttm"),
        build_statement(p.canonical, p.items, "CF", "ttm"),
        p.quarterly["BS"],
        p.quarterly["IS"],
    )


@pytest.mark.parametrize("freq", ["annual", "ttm"])
@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "COST", "DE"])
def test_custom_rules_equal_the_built_ins_on_recorded_fixtures(ticker: str, freq: str) -> None:
    shipped = {r.code: r for r in load_rules()}
    rules = [shipped[code] for code in GOLDEN]
    for code, text in GOLDEN.items():
        t = shipped[code].thresholds
        assert isinstance(t.warn, Decimal | None) and isinstance(t.alert, Decimal | None)
        rules.append(
            custom(
                f"custom_{code}",
                text,
                None if t.warn is None else str(t.warn),
                None if t.alert is None else str(t.alert),
                shipped[code].direction,
            )
        )
    result = evaluate_flags(
        pipeline_inputs(ticker, freq), rules, "annual" if freq == "annual" else "ttm"
    )
    assert result.periods
    for code in GOLDEN:
        mine, builtin = full_row(result, f"custom_{code}"), full_row(result, code)
        assert mine.values == builtin.values, code
        assert mine.severity == builtin.severity, code
        assert mine.warn_levels == builtin.warn_levels, code
        assert mine.alert_levels == builtin.alert_levels, code
        # non-vacuity: every code has a judged value on every recorded ticker and frequency
        assert any(v is not None for v in builtin.values), (ticker, freq, code)
