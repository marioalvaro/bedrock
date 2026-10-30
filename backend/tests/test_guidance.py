"""The guidance engine (FR-ANL-09): verdicts, surprise, revisions and the hit/miss summary."""

from datetime import date
from decimal import Decimal

import pytest

from bedrock.analysis.guidance import (
    LOWER_IS_BETTER,
    QUARTER_RATIOS,
    ActualKey,
    Basis,
    Direction,
    GuidanceEntry,
    GuidanceResult,
    evaluate,
    quarter_margin,
    summarize,
)
from bedrock.ratios.registry import RATIOS
from bedrock.services.statements import canonical_items

D = Decimal


def entry(
    id: int = 1,
    low: int | str = 100,
    high: int | str = 110,
    *,
    metric: str = "revenue",
    year: int = 2024,
    period: str = "FY",
    basis: Basis = "reported",
    direction: Direction = "higher",
    given_on: date = date(2024, 1, 1),
) -> GuidanceEntry:
    return GuidanceEntry(
        id=id,
        metric=metric,
        fiscal_year=year,
        fiscal_period=period,
        low=D(low),
        high=D(high),
        basis=basis,
        direction=direction,
        given_on=given_on,
    )


def judged(e: GuidanceEntry, actual: float | str | None) -> GuidanceResult:
    key = (e.basis, e.metric, e.fiscal_year, e.fiscal_period)
    (result,) = evaluate([e], {key: None if actual is None else D(actual)})
    return result


# --- verdicts --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actual", "verdict"),
    [(111, "beat"), (110, "in_range"), (105, "in_range"), (100, "in_range"), (99, "miss")],
)
def test_higher_is_better_beats_above_the_range_and_misses_below_it(
    actual: int, verdict: str
) -> None:
    assert judged(entry(), actual).verdict == verdict


@pytest.mark.parametrize(
    ("actual", "verdict"),
    [(99, "beat"), (100, "in_range"), (105, "in_range"), (110, "in_range"), (111, "miss")],
)
def test_lower_is_better_flips_beat_and_miss(actual: int, verdict: str) -> None:
    assert judged(entry(direction="lower"), actual).verdict == verdict


def test_a_point_guidance_is_in_range_only_when_equal() -> None:
    point = entry(low=100, high=100)
    assert [judged(point, a).verdict for a in (99, 100, 101)] == ["miss", "in_range", "beat"]


def test_no_actual_is_pending_with_no_surprise() -> None:
    result = judged(entry(), None)
    assert (result.actual, result.verdict, result.surprise) == (None, "pending", None)


def test_negative_ranges_compare_by_value() -> None:
    capex = entry(low=-11, high=-10, metric="capex")
    assert [judged(capex, a).verdict for a in (-9, -10, -10.5, -11, -12)] == [
        "beat",
        "in_range",
        "in_range",
        "in_range",
        "miss",
    ]


def test_the_actual_is_read_on_the_entrys_own_basis() -> None:
    reported, normalized = entry(1, basis="reported"), entry(2, basis="normalized")
    actuals: dict[ActualKey, Decimal | None] = {
        ("reported", "revenue", 2024, "FY"): D(105),
        ("normalized", "revenue", 2024, "FY"): D(120),
    }
    first, second = evaluate([reported, normalized], actuals)
    assert (first.actual, first.verdict) == (D(105), "in_range")
    assert (second.actual, second.verdict) == (D(120), "beat")


def test_an_actual_missing_from_the_map_is_pending() -> None:
    assert evaluate([entry()], {})[0].verdict == "pending"


# --- surprise --------------------------------------------------------------------------------


def test_surprise_is_the_distance_from_the_midpoint_over_its_size() -> None:
    assert judged(entry(low=100, high=110), 120).surprise == D("0.142857")  # 15 / 105
    assert judged(entry(low=100, high=110), 90).surprise == D("-0.142857")


def test_surprise_of_a_negative_midpoint_uses_its_absolute_value() -> None:
    assert judged(entry(low=-11, high=-9, metric="capex"), -5).surprise == D("0.5")  # 5 / 10


def test_surprise_is_null_when_the_midpoint_is_zero() -> None:
    assert judged(entry(low=-5, high=5), 3).surprise is None


def test_surprise_is_not_flipped_for_lower_is_better() -> None:
    assert judged(entry(direction="lower"), "94.5").surprise == D("-0.1")


# --- revisions -------------------------------------------------------------------------------


def test_the_latest_given_on_of_a_key_is_the_latest_entry() -> None:
    old, new = entry(1, given_on=date(2024, 1, 1)), entry(2, given_on=date(2024, 4, 1))
    first, second = evaluate([old, new], {})
    assert (first.latest, second.latest) == (False, True)


def test_the_latest_does_not_depend_on_input_order() -> None:
    old, new = entry(1, given_on=date(2024, 1, 1)), entry(2, given_on=date(2024, 4, 1))
    first, second = evaluate([new, old], {})
    assert (first.latest, second.latest) == (True, False)


def test_a_tie_on_given_on_goes_to_the_highest_id() -> None:
    a, b = entry(5), entry(9)
    assert [r.latest for r in evaluate([a, b], {})] == [False, True]


def test_entries_of_different_keys_are_each_latest() -> None:
    entries = [
        entry(1),
        entry(2, metric="sga"),
        entry(3, year=2025),
        entry(4, period="Q1"),
        entry(5, basis="normalized"),
    ]
    assert all(r.latest for r in evaluate(entries, {}))


def test_results_keep_the_order_of_the_entries() -> None:
    entries = [entry(3), entry(1, metric="sga"), entry(2, year=2025)]
    assert [r.entry.id for r in evaluate(entries, {})] == [3, 1, 2]


# --- summary ---------------------------------------------------------------------------------


def results(*spec: tuple[GuidanceEntry, int | None]) -> list[GuidanceResult]:
    actuals: dict[ActualKey, Decimal | None] = {
        (e.basis, e.metric, e.fiscal_year, e.fiscal_period): D(a) for e, a in spec if a is not None
    }
    return evaluate([e for e, _ in spec], actuals)


def test_the_summary_counts_only_the_latest_entries() -> None:
    old_miss = entry(1, given_on=date(2024, 1, 1))  # revised below, so not counted
    new_beat = entry(2, given_on=date(2024, 4, 1))
    in_range = entry(3, metric="sga", direction="lower")
    miss = entry(4, metric="rnd", direction="lower")
    pending = entry(5, year=2025)
    summary = summarize(
        results((old_miss, 90), (new_beat, 120), (in_range, 105), (miss, 120), (pending, None))
    )
    # revenue FY2024 actual is 120 for both revenue entries, but only the latest counts
    assert (summary.beat, summary.in_range, summary.miss, summary.pending) == (1, 1, 1, 1)


def test_hit_rate_is_beats_and_in_range_over_the_decided_entries() -> None:
    summary = summarize(
        results(
            (entry(1, metric="a"), 120),
            (entry(2, metric="b"), 105),
            (entry(3, metric="c"), 90),
            (entry(4, metric="d"), None),
        )
    )
    assert summary.hit_rate == D("0.666667")


def test_hit_rate_is_null_without_a_decided_entry() -> None:
    assert summarize([]).hit_rate is None
    assert summarize(results((entry(), None))).hit_rate is None


def test_a_perfect_record_has_a_hit_rate_of_one() -> None:
    assert summarize(results((entry(), 105))).hit_rate == D(1)


def test_by_metric_groups_the_latest_entries_in_metric_order() -> None:
    summary = summarize(
        results(
            (entry(1, metric="sga", direction="lower"), 120),
            (entry(2, metric="revenue"), 120),
            (entry(3, metric="revenue", year=2023), 90),
            (entry(4, metric="revenue", year=2025), None),
        )
    )
    assert [m.metric for m in summary.by_metric] == ["revenue", "sga"]
    revenue, sga = summary.by_metric
    assert (revenue.beat, revenue.in_range, revenue.miss, revenue.pending) == (1, 0, 1, 1)
    assert revenue.hit_rate == D("0.5")
    assert (sga.miss, sga.hit_rate) == (1, D(0))


def test_by_metric_separates_nothing_across_basis() -> None:
    summary = summarize(results((entry(1), 120), (entry(2, basis="normalized"), 90)))
    (revenue,) = summary.by_metric
    assert (revenue.beat, revenue.miss) == (1, 1)


def test_the_empty_summary_is_all_zero() -> None:
    summary = summarize([])
    assert (summary.beat, summary.in_range, summary.miss, summary.pending) == (0, 0, 0, 0)
    assert summary.by_metric == []


# --- quarter margins -------------------------------------------------------------------------


def test_the_quarter_ratios_are_the_five_margins_and_are_registry_ratios() -> None:
    assert set(QUARTER_RATIOS) == {
        "gross_margin",
        "operating_margin",
        "ebitda_margin",
        "net_margin",
        "fcf_margin",
    }
    assert set(QUARTER_RATIOS) <= {r.code for r in RATIOS}


def test_every_quarter_margin_operand_is_a_canonical_line() -> None:
    codes = {i.code for i in canonical_items()}
    assert {c for operands in QUARTER_RATIOS.values() for c in operands} <= codes


def test_a_margin_is_the_quarters_numerator_over_its_revenue() -> None:
    values = {"revenue": D(200), "gross_profit": D(94), "operating_income": D(60)}
    assert quarter_margin("gross_margin", values) == D("0.47")
    assert quarter_margin("operating_margin", values) == D("0.3")


def test_the_ebitda_margin_adds_depreciation_to_operating_income() -> None:
    values = {"revenue": D(200), "operating_income": D(60), "d_and_a": D(10)}
    assert quarter_margin("ebitda_margin", values) == D("0.35")


def test_a_margin_is_quantized_to_six_places() -> None:
    assert quarter_margin("net_margin", {"revenue": D(3), "net_income_common": D(1)}) == D(
        "0.333333"
    )


def test_a_margin_is_null_when_revenue_is_not_positive() -> None:
    assert quarter_margin("gross_margin", {"revenue": D(0), "gross_profit": D(1)}) is None
    assert quarter_margin("gross_margin", {"revenue": D(-5), "gross_profit": D(1)}) is None
    assert quarter_margin("gross_margin", {"gross_profit": D(1)}) is None


def test_a_margin_is_null_when_a_numerator_operand_is_missing() -> None:
    assert quarter_margin("gross_margin", {"revenue": D(100)}) is None
    assert quarter_margin("ebitda_margin", {"revenue": D(100), "operating_income": D(5)}) is None
    assert quarter_margin("gross_margin", {"revenue": D(100), "gross_profit": None}) is None


def test_a_negative_margin_is_kept() -> None:
    assert quarter_margin("net_margin", {"revenue": D(100), "net_income_common": D(-5)}) == D(
        "-0.05"
    )


def test_a_ratio_that_is_not_a_quarter_margin_is_rejected() -> None:
    with pytest.raises(ValueError, match="roe"):
        quarter_margin("roe", {"revenue": D(1)})


# --- the direction table ---------------------------------------------------------------------


def test_lower_is_better_names_a_metric_that_exists() -> None:
    known = {i.code for i in canonical_items()} | {r.code for r in RATIOS}
    assert LOWER_IS_BETTER <= known
    assert LOWER_IS_BETTER == {
        "cost_of_revenue",
        "total_operating_costs",
        "rnd",
        "sga",
        "other_operating_expenses",
        "interest_expense",
        "income_tax",
        "dso",
        "dio",
        "ccc",
        "debt_to_ebitda",
        "net_debt_to_ebitda",
        "debt_to_equity",
    }
