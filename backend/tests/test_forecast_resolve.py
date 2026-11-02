"""Driver resolution (docs/erd/forecasting.md "Scenarios (M4)" → Resolution). Pure."""

import random
from decimal import Decimal

import pytest

from bedrock.forecast.drivers import DriverKind, Follows
from bedrock.forecast.history import FLAT, Default
from bedrock.forecast.resolve import DriverRow, Resolved, ResolvedDrivers, resolve_drivers

D = Decimal
YEARS = [2027, 2028]
DEFAULTS: dict[str, Default] = {
    "revenue_growth": D("0.05"),
    "gross_margin": D("0.40"),
    "d_and_a_pct_revenue": Follows("capex_pct_revenue", resolved=True),
    "receivable_days": FLAT,
    "capex_pct_revenue": D("0.03"),
    "segment_growth:7": D("0.10"),  # history.py already filled it from the revenue-growth default
}


def row(
    code: str, year: int, value: str, kind: DriverKind = "value", period: str = "FY"
) -> DriverRow:
    return DriverRow(code, year, kind, D(value), period)


def test_base_takes_its_own_values_then_the_defaults() -> None:
    base = [row("revenue_growth", 2027, "0.08")]
    resolved = resolve_drivers(base, base, DEFAULTS, YEARS, is_base=True)
    assert resolved.get("revenue_growth", 2027) == Resolved(D("0.08"), "own")
    assert resolved.get("revenue_growth", 2028) == Resolved(D("0.05"), "default")
    assert resolved.get("gross_margin", 2027) == Resolved(D("0.40"), "default")
    assert resolved.get("segment_growth:7", 2028) == Resolved(D("0.10"), "default")
    assert resolved.get("receivable_days", 2027) == Resolved(FLAT, "default")


def test_each_precedence_step_of_a_scenario() -> None:
    base = [row("revenue_growth", 2027, "0.08"), row("gross_margin", 2027, "0.50")]
    own = [
        row("revenue_growth", 2028, "0.20"),  # own value
        row("gross_margin", 2027, "0.01", "offset"),  # offset on Base's value
        row("gross_margin", 2028, "-0.02", "offset"),  # offset on Base's default
    ]
    resolved = resolve_drivers(base, own, DEFAULTS, YEARS, is_base=False)
    assert resolved.get("revenue_growth", 2027) == Resolved(D("0.08"), "base")  # Base's value
    assert resolved.get("revenue_growth", 2028) == Resolved(D("0.20"), "own")
    assert resolved.get("gross_margin", 2027) == Resolved(D("0.51"), "offset")  # 0.50 + 0.01
    assert resolved.get("gross_margin", 2028) == Resolved(D("0.38"), "offset")  # 0.40 - 0.02
    assert resolved.get("capex_pct_revenue", 2027) == Resolved(D("0.03"), "default")


def test_an_own_value_beats_base_and_default() -> None:
    base = [row("capex_pct_revenue", 2027, "0.04")]
    own = [row("capex_pct_revenue", 2027, "0.06")]
    resolved = resolve_drivers(base, own, DEFAULTS, YEARS, is_base=False)
    assert resolved.get("capex_pct_revenue", 2027) == Resolved(D("0.06"), "own")


def test_an_offset_on_base_is_rejected() -> None:
    rows = [row("revenue_growth", 2027, "0.03", "offset")]
    with pytest.raises(ValueError, match="offset"):
        resolve_drivers(rows, rows, DEFAULTS, YEARS, is_base=True)


def test_rows_of_years_that_are_no_longer_forecast_years_are_ignored() -> None:
    base = [row("revenue_growth", 2026, "0.50")]
    own = [row("gross_margin", 2026, "0.10", "offset"), row("revenue_growth", 2029, "0.9")]
    resolved = resolve_drivers(base, own, DEFAULTS, YEARS, is_base=False)
    assert resolved.years == (2027, 2028)
    assert resolved.get("revenue_growth", 2027) == Resolved(D("0.05"), "default")
    assert resolved.get("gross_margin", 2027) == Resolved(D("0.40"), "default")
    with pytest.raises(KeyError):
        resolved.get("revenue_growth", 2026)


def test_d_and_a_follows_the_scenarios_resolved_capex() -> None:
    base = [row("capex_pct_revenue", 2027, "0.04")]
    own = [row("capex_pct_revenue", 2028, "0.06")]
    resolved = resolve_drivers(base, own, DEFAULTS, YEARS, is_base=False)
    assert resolved.get("d_and_a_pct_revenue", 2027) == Resolved(D("0.04"), "default")  # Base's
    assert resolved.get("d_and_a_pct_revenue", 2028) == Resolved(D("0.06"), "default")  # own


def test_an_offset_on_a_followed_driver_adds_to_bases_resolved_value() -> None:
    base = [row("capex_pct_revenue", 2027, "0.04")]
    own = [
        row("capex_pct_revenue", 2027, "0.09"),  # not what Base's D&A follows
        row("d_and_a_pct_revenue", 2027, "0.01", "offset"),
    ]
    resolved = resolve_drivers(base, own, DEFAULTS, YEARS, is_base=False)
    # Base's D&A follows Base's capex (0.04); the offset goes on top of that.
    assert resolved.get("d_and_a_pct_revenue", 2027) == Resolved(D("0.05"), "offset")


def test_missing_required_lists_each_unset_driver_once_in_catalog_order() -> None:
    defaults: dict[str, Default] = {
        **DEFAULTS,
        "revenue_growth": None,
        "gross_margin": None,
        "capex_pct_revenue": None,
    }
    resolved = resolve_drivers([], [], defaults, YEARS, is_base=True)
    # D&A follows capex: setting capex fixes it, so it is not listed.
    assert resolved.missing_required() == ["revenue_growth", "gross_margin", "capex_pct_revenue"]
    assert resolved.get("gross_margin", 2027) == Resolved(None, None)
    assert resolved.get("d_and_a_pct_revenue", 2027) == Resolved(None, None)

    # Set for one year only: still missing.
    base = [row("gross_margin", 2027, "0.25"), row("revenue_growth", 2027, "0.1")]
    base += [row("revenue_growth", 2028, "0.1")]
    base += [row("capex_pct_revenue", y, "0.02") for y in YEARS]
    resolved = resolve_drivers(base, base, defaults, YEARS, is_base=True)
    assert resolved.missing_required() == ["gross_margin"]
    assert resolved.get("d_and_a_pct_revenue", 2028) == Resolved(D("0.02"), "default")


def test_a_scenario_inherits_a_set_driver_from_base() -> None:
    defaults: dict[str, Default] = {**DEFAULTS, "gross_margin": None}
    base = [row("gross_margin", y, "0.25") for y in YEARS]
    resolved = resolve_drivers(base, [], defaults, YEARS, is_base=False)
    assert resolved.missing_required() == []
    assert resolved.get("gross_margin", 2028) == Resolved(D("0.25"), "base")


def test_an_offset_on_a_missing_base_value_is_still_missing() -> None:
    defaults: dict[str, Default] = {**DEFAULTS, "gross_margin": None}
    own = [row("gross_margin", y, "0.01", "offset") for y in YEARS]
    resolved = resolve_drivers([], own, defaults, YEARS, is_base=False)
    assert resolved.missing_required() == ["gross_margin"]


def test_an_offset_on_a_flat_line_keeps_it_flat_with_a_warning() -> None:
    own = [row("receivable_days", 2027, "5", "offset")]
    resolved = resolve_drivers([], own, DEFAULTS, YEARS, is_base=False)
    assert resolved.get("receivable_days", 2027) == Resolved(FLAT, "default")
    assert resolved.warnings == (
        "receivable_days FY2027: the offset is ignored, Base holds the line flat",
    )


def test_out_of_bounds_after_an_offset() -> None:
    defaults: dict[str, Default] = {**DEFAULTS, "gross_margin": D("0.995")}
    own = [row("gross_margin", 2028, "0.01", "offset")]
    resolved = resolve_drivers([], own, defaults, YEARS, is_base=False)
    assert resolved.get("gross_margin", 2028).value == D("1.005")
    assert resolved.out_of_bounds() == [("gross_margin", 2028, "gross_margin must be in [-1, 1]")]
    assert resolve_drivers([], [], defaults, YEARS, is_base=True).out_of_bounds() == []


# --- quarter values (docs/erd/forecasting.md "Quarterly drivers" -> Resolution) -----------------

QUARTER_DEFAULTS: dict[str, Default] = {**DEFAULTS, "buybacks": D(400), "min_cash": D(50)}


def quarter(code: str, year: int, period: str, value: str, kind: DriverKind = "value") -> DriverRow:
    return row(code, year, value, kind, period)


def resolve_q(
    base: list[DriverRow], own: list[DriverRow], is_base: bool = False
) -> ResolvedDrivers:
    return resolve_drivers(base, own, QUARTER_DEFAULTS, YEARS, is_base)


def test_a_quarter_with_no_row_takes_its_years_value_with_source_year() -> None:
    base = resolve_q([], [], is_base=True)
    assert base.get("gross_margin", 2027, "Q2") == Resolved(D("0.40"), "year")  # the default
    own = [row("gross_margin", 2027, "0.33")]
    scenario = resolve_q([], own)
    assert scenario.get("gross_margin", 2027, "Q4") == Resolved(D("0.33"), "year")
    inherited = resolve_q([row("gross_margin", 2027, "0.25")], [])
    assert inherited.get("gross_margin", 2027, "Q1") == Resolved(D("0.25"), "year")
    # years are resolved as before
    assert inherited.get("gross_margin", 2027, "FY") == Resolved(D("0.25"), "base")


def test_a_quarters_own_value_beats_its_years_value() -> None:
    own = [row("gross_margin", 2027, "0.33"), quarter("gross_margin", 2027, "Q2", "0.50")]
    resolved = resolve_q([], own)
    assert resolved.get("gross_margin", 2027, "Q2") == Resolved(D("0.50"), "own")
    assert resolved.get("gross_margin", 2027, "Q1") == Resolved(D("0.33"), "year")
    assert resolved.get("gross_margin", 2027, "FY") == Resolved(D("0.33"), "own")


def test_base_takes_its_quarter_rows_too() -> None:
    base = [quarter("capex_pct_revenue", 2028, "Q3", "0.08")]
    resolved = resolve_q(base, base, is_base=True)
    assert resolved.get("capex_pct_revenue", 2028, "Q3") == Resolved(D("0.08"), "own")
    assert resolved.get("capex_pct_revenue", 2028, "Q4") == Resolved(D("0.03"), "year")


def test_a_quarter_offset_goes_on_bases_quarter_value() -> None:
    base = [quarter("gross_margin", 2027, "Q1", "0.45")]
    own = [quarter("gross_margin", 2027, "Q1", "0.01", "offset")]
    assert resolve_q(base, own).get("gross_margin", 2027, "Q1") == Resolved(D("0.46"), "offset")


def test_a_quarter_offset_without_a_base_quarter_goes_on_bases_year() -> None:
    base = [row("gross_margin", 2027, "0.50")]
    own = [quarter("gross_margin", 2027, "Q3", "-0.02", "offset")]
    resolved = resolve_q(base, own)
    assert resolved.get("gross_margin", 2027, "Q3") == Resolved(D("0.48"), "offset")
    assert resolved.get("gross_margin", 2027, "Q4") == Resolved(D("0.50"), "year")
    defaults_only = resolve_q([], own)  # Base's default 0.40
    assert defaults_only.get("gross_margin", 2027, "Q3") == Resolved(D("0.38"), "offset")


def test_an_annual_offset_keeps_bases_quarterly_pattern() -> None:
    base = [quarter("gross_margin", 2027, "Q1", "0.45")]  # Q2..Q4 take Base's default 0.40
    own = [row("gross_margin", 2027, "0.03", "offset")]
    resolved = resolve_q(base, own)
    assert resolved.get("gross_margin", 2027, "Q1") == Resolved(D("0.48"), "offset")
    assert resolved.get("gross_margin", 2027, "Q2") == Resolved(D("0.43"), "offset")
    assert resolved.get("gross_margin", 2027, "FY") == Resolved(D("0.43"), "offset")


def test_a_quarter_offset_beats_the_annual_offset_and_both_beat_bases_quarter() -> None:
    base = [
        quarter("gross_margin", 2027, "Q1", "0.45"),
        quarter("gross_margin", 2027, "Q2", "0.46"),
    ]
    annual = [row("gross_margin", 2027, "0.03", "offset")]
    assert resolve_q(base, annual).get("gross_margin", 2027, "Q2") == Resolved(D("0.49"), "offset")
    both = [*annual, quarter("gross_margin", 2027, "Q2", "0.10", "offset")]
    assert resolve_q(base, both).get("gross_margin", 2027, "Q2") == Resolved(D("0.56"), "offset")
    assert resolve_q(base, []).get("gross_margin", 2027, "Q2") == Resolved(D("0.46"), "base")


def test_an_own_annual_value_beats_bases_quarter_row() -> None:
    base = [quarter("gross_margin", 2027, "Q1", "0.45")]
    own = [row("gross_margin", 2027, "0.30")]
    # the scenario's own annual value is its answer for every quarter it has no row for
    assert resolve_q(base, own).get("gross_margin", 2027, "Q1") == Resolved(D("0.30"), "year")


def test_flow_amounts_are_quarter_amounts() -> None:
    year = [row("buybacks", 2027, "400")]
    assert resolve_q([], year).get("buybacks", 2027, "Q1") == Resolved(D("100"), "year")
    assert resolve_q([], []).get("buybacks", 2027, "Q1") == Resolved(D("100"), "year")  # default
    assert resolve_q([], year).get("buybacks", 2027, "FY") == Resolved(D("400"), "own")
    own_q = year + [quarter("buybacks", 2027, "Q2", "150")]
    resolved = resolve_q([], own_q)
    assert resolved.get("buybacks", 2027, "Q2") == Resolved(D("150"), "own")
    assert resolved.get("buybacks", 2027, "Q3") == Resolved(D("100"), "year")
    # an annual offset of 40 is 10 a quarter; a quarter offset of 25 is 25 on Base's 100
    annual_offset = [row("buybacks", 2027, "40", "offset")]
    assert resolve_q([], annual_offset).get("buybacks", 2027, "Q1") == Resolved(D("110"), "offset")
    quarter_offset = [quarter("buybacks", 2027, "Q1", "25", "offset")]
    assert resolve_q([], quarter_offset).get("buybacks", 2027, "Q1") == Resolved(D("125"), "offset")
    base_q = [quarter("buybacks", 2027, "Q1", "80")]
    assert resolve_q(base_q, annual_offset).get("buybacks", 2027, "Q1") == Resolved(
        D("90"), "offset"
    )


def test_a_floor_is_not_split_over_the_quarters() -> None:
    resolved = resolve_q([], [row("min_cash", 2027, "60")])
    assert resolved.get("min_cash", 2027, "Q1") == Resolved(D("60"), "year")


def test_a_flat_or_missing_year_gives_a_flat_or_missing_quarter() -> None:
    defaults: dict[str, Default] = {**QUARTER_DEFAULTS, "gross_margin": None}
    resolved = resolve_drivers([], [], defaults, YEARS, is_base=True)
    assert resolved.get("receivable_days", 2027, "Q1") == Resolved(FLAT, "default")
    assert resolved.get("gross_margin", 2027, "Q1") == Resolved(None, None)
    assert resolved.missing_required() == ["gross_margin"]  # named once, not per quarter


def test_a_quarter_outside_the_forecast_years_or_a_fifth_quarter_is_not_resolved() -> None:
    own = [quarter("gross_margin", 2026, "Q1", "0.9")]
    resolved = resolve_q([], own)
    with pytest.raises(KeyError):
        resolved.get("gross_margin", 2026, "Q1")
    with pytest.raises(KeyError):
        resolved.get("gross_margin", 2027, "Q5")


def test_an_offset_on_a_base_quarter_is_rejected() -> None:
    rows = [quarter("gross_margin", 2027, "Q1", "0.01", "offset")]
    with pytest.raises(ValueError, match="offset"):
        resolve_drivers(rows, rows, QUARTER_DEFAULTS, YEARS, is_base=True)


def test_a_quarter_value_out_of_bounds_is_reported_once_at_its_quarter() -> None:
    own = [quarter("gross_margin", 2028, "Q2", "1.5")]
    resolved = resolve_q([], own)
    assert resolved.out_of_bounds() == []  # the years are fine
    assert resolved.out_of_bounds_quarters() == [
        ("gross_margin", 2028, "Q2", "gross_margin must be in [-1, 1]")
    ]
    base = [quarter("gross_margin", 2027, "Q1", "0.995")]
    offset = [quarter("gross_margin", 2027, "Q1", "0.01", "offset")]
    assert resolve_q(base, offset).out_of_bounds_quarters() == [
        ("gross_margin", 2027, "Q1", "gross_margin must be in [-1, 1]")
    ]


def test_a_year_out_of_bounds_is_not_repeated_for_its_quarters() -> None:
    defaults: dict[str, Default] = {**QUARTER_DEFAULTS, "gross_margin": D("0.995")}
    own = [row("gross_margin", 2028, "0.01", "offset")]
    resolved = resolve_drivers([], own, defaults, YEARS, is_base=False)
    assert [e[:2] for e in resolved.out_of_bounds()] == [("gross_margin", 2028)]
    assert resolved.out_of_bounds_quarters() == []


def test_with_no_quarter_rows_every_quarter_is_its_years_value_over_random_rows() -> None:
    rng = random.Random(20261101)
    codes = ["gross_margin", "capex_pct_revenue", "buybacks", "revenue_growth"]
    for _ in range(200):
        base = [
            row(c, y, str(rng.randint(1, 90) / 100))
            for c in codes[:2]
            for y in YEARS
            if rng.random() < 0.5
        ]
        base += [row("buybacks", y, str(rng.randint(0, 1000))) for y in YEARS if rng.random() < 0.5]
        own = [
            row(c, y, str(rng.randint(1, 90) / 100))
            for c in codes[:2]
            for y in YEARS
            if rng.random() < 0.5
        ]
        is_base = rng.random() < 0.3
        resolved = resolve_q(base if not is_base else own, own, is_base)
        for code in codes:
            for year in YEARS:
                annual = resolved.get(code, year)
                share = D("0.25") if code == "buybacks" else D(1)
                for period in ("Q1", "Q2", "Q3", "Q4"):
                    got = resolved.get(code, year, period)
                    assert got.value == annual.value * share  # type: ignore[operator]
                    assert got.source == "year"
