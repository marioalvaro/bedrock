"""Driver resolution (docs/erd/forecasting.md "Scenarios (M4)" → Resolution). Pure."""

from decimal import Decimal

import pytest

from bedrock.forecast.drivers import DriverKind, Follows
from bedrock.forecast.history import FLAT, Default
from bedrock.forecast.resolve import DriverRow, Resolved, resolve_drivers

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


def row(code: str, year: int, value: str, kind: DriverKind = "value") -> DriverRow:
    return DriverRow(code, year, kind, D(value))


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
