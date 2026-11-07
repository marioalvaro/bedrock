"""Driver resolution with engine defaults and seasonal quarters (docs/erd/forecasting.md
"Statistical engines (M6)" → Resolution). Pure."""

from collections.abc import Collection
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
    "tax_rate": None,
    "capex_pct_revenue": D("0.03"),
    "buybacks": D("400"),
}
ENGINE = {
    ("gross_margin", 2027): D("0.42"),
    ("gross_margin", 2028): D("0.43"),
    ("capex_pct_revenue", 2027): D("0.035"),
    ("revenue_growth", 2028): D("0.06"),
}
INDEX = {"Q1": D("0.02"), "Q2": D("-0.01"), "Q3": D("-0.005"), "Q4": D("-0.005")}
SEASONAL = {
    "gross_margin": INDEX,
    "receivable_days": {"Q1": D(5), "Q2": D(-5), "Q3": D(0), "Q4": D(0)},
    "tax_rate": INDEX,
}


def row(
    code: str, year: int, value: str, kind: DriverKind = "value", period: str = "FY"
) -> DriverRow:
    return DriverRow(code, year, kind, D(value), period)


def resolve(
    base: list[DriverRow],
    own: list[DriverRow] | None = None,
    quarterly_years: Collection[int] = frozenset(),
    seasonal: dict[str, dict[str, Decimal]] | None = None,
) -> ResolvedDrivers:
    """Base when `own` is None, else a case with those rows."""
    return resolve_drivers(
        base,
        base if own is None else own,
        DEFAULTS,
        YEARS,
        is_base=own is None,
        quarterly_years=quarterly_years,
        engine_values=ENGINE,
        seasonal=SEASONAL if seasonal is None else seasonal,
    )


# --- annual ---------------------------------------------------------------------------------


def test_an_engine_value_replaces_the_default_with_source_engine() -> None:
    out = resolve([])

    assert out.get("gross_margin", 2027) == Resolved(D("0.42"), "engine")
    assert out.get("gross_margin", 2028) == Resolved(D("0.43"), "engine")
    assert out.get("revenue_growth", 2027) == Resolved(D("0.05"), "default")  # no engine value
    assert out.get("revenue_growth", 2028) == Resolved(D("0.06"), "engine")


def test_set_values_beat_the_engine() -> None:
    base = [row("gross_margin", 2027, "0.50")]
    own = [row("gross_margin", 2028, "0.60"), row("capex_pct_revenue", 2027, "0.01", "offset")]

    base_out = resolve(base)
    bull = resolve(base, own)

    assert base_out.get("gross_margin", 2027) == Resolved(D("0.50"), "own")
    assert bull.get("gross_margin", 2027) == Resolved(D("0.50"), "base")
    assert bull.get("gross_margin", 2028) == Resolved(D("0.60"), "own")
    assert bull.get("capex_pct_revenue", 2027) == Resolved(D("0.045"), "offset")


def test_bulls_offset_sits_on_bases_engine_value() -> None:
    bull = resolve([], [row("gross_margin", 2027, "0.01", "offset")])

    assert bull.get("gross_margin", 2027) == Resolved(D("0.43"), "offset")
    assert bull.get("gross_margin", 2028) == Resolved(D("0.43"), "engine")  # inherits the engine


def test_a_following_default_follows_the_resolved_engine_value() -> None:
    out = resolve([])

    assert out.get("d_and_a_pct_revenue", 2027) == Resolved(D("0.035"), "default")
    assert out.get("d_and_a_pct_revenue", 2028) == Resolved(D("0.03"), "default")


def test_flat_and_missing_defaults_are_untouched() -> None:
    out = resolve([])

    assert out.get("receivable_days", 2027) == Resolved(FLAT, "default")
    assert out.get("tax_rate", 2027) == Resolved(None, None)
    assert out.missing_required() == ["tax_rate"]
    assert out.get("receivable_days", 2027, "Q1") == Resolved(FLAT, "default")
    assert out.get("tax_rate", 2027, "Q1") == Resolved(None, None)


def test_engine_values_of_codes_or_years_outside_the_resolution_are_ignored() -> None:
    values = {**ENGINE, ("sga_pct_revenue", 2027): D("0.2"), ("gross_margin", 2031): D("0.9")}

    out = resolve_drivers([], [], DEFAULTS, YEARS, True, engine_values=values)

    assert ("sga_pct_revenue", 2027) not in out.values
    assert out.years == (2027, 2028)


# --- quarters -------------------------------------------------------------------------------


def test_a_quarter_that_takes_its_years_value_adds_the_seasonal_index() -> None:
    out = resolve([])

    assert out.get("gross_margin", 2027, "Q1") == Resolved(D("0.44"), "seasonal")
    assert out.get("gross_margin", 2027, "Q2") == Resolved(D("0.41"), "seasonal")
    assert out.get("gross_margin", 2028, "Q4") == Resolved(D("0.425"), "seasonal")
    quarters = [out.get("gross_margin", 2027, q).value for q in ("Q1", "Q2", "Q3", "Q4")]
    assert sum(q for q in quarters if isinstance(q, Decimal)) / 4 == D("0.42")


def test_a_driver_without_a_seasonal_index_keeps_its_years_value() -> None:
    out = resolve([])

    assert out.get("revenue_growth", 2027, "Q1") == Resolved(D("0.05"), "year")
    assert out.get("capex_pct_revenue", 2027, "Q3") == Resolved(D("0.035"), "year")
    assert out.get("buybacks", 2027, "Q1") == Resolved(D("100"), "year")


def test_an_own_annual_value_carries_the_pattern_at_step_three() -> None:
    out = resolve([row("gross_margin", 2027, "0.50")])

    assert out.get("gross_margin", 2027, "Q1") == Resolved(D("0.52"), "seasonal")
    assert out.get("gross_margin", 2027) == Resolved(D("0.50"), "own")


def test_a_quarters_own_value_is_unchanged() -> None:
    out = resolve([row("gross_margin", 2027, "0.60", period="Q2")])

    assert out.get("gross_margin", 2027, "Q2") == Resolved(D("0.60"), "own")
    assert out.get("gross_margin", 2027, "Q1") == Resolved(D("0.44"), "seasonal")


def test_a_quarter_offset_sits_on_bases_seasonal_quarter() -> None:
    bull = resolve([], [row("gross_margin", 2027, "0.01", "offset", "Q1")])

    assert bull.get("gross_margin", 2027, "Q1") == Resolved(D("0.45"), "offset")


def test_an_annual_offset_sits_on_bases_seasonal_quarter() -> None:
    bull = resolve([], [row("gross_margin", 2027, "0.01", "offset")])

    assert bull.get("gross_margin", 2027, "Q1") == Resolved(D("0.45"), "offset")  # 0.44 + 0.01
    assert bull.get("gross_margin", 2027, "Q2") == Resolved(D("0.42"), "offset")  # 0.41 + 0.01


def test_bases_quarter_row_is_inherited_as_it_is() -> None:
    base = [row("gross_margin", 2027, "0.70", period="Q3")]

    bull = resolve(base, [])

    assert bull.get("gross_margin", 2027, "Q3") == Resolved(D("0.70"), "base")
    assert bull.get("gross_margin", 2027, "Q1") == Resolved(D("0.44"), "seasonal")


def test_bull_with_its_own_annual_value_adds_the_pattern_to_it() -> None:
    bull = resolve([], [row("gross_margin", 2027, "0.30")])

    assert bull.get("gross_margin", 2027, "Q1") == Resolved(D("0.32"), "seasonal")


def test_in_a_year_set_by_quarter_the_free_step_adds_the_pattern_to_the_quarter_free_year() -> None:
    base = [row("gross_margin", 2027, "0.50"), row("gross_margin", 2027, "0.60", period="Q2")]

    out = resolve(base, quarterly_years={2027})

    assert out.get("gross_margin", 2027, "Q1") == Resolved(D("0.44"), "seasonal")  # engine + Q1
    assert out.get("gross_margin", 2027, "Q2") == Resolved(D("0.60"), "own")
    assert out.get("gross_margin", 2027) == Resolved(D("0.50"), "own")
    assert out.get("gross_margin", 2028, "Q1") == Resolved(D("0.45"), "seasonal")


def test_in_a_year_set_by_quarter_bull_follows_bases_seasonal_quarter() -> None:
    bull = resolve([], [row("gross_margin", 2027, "0.01", "offset")], quarterly_years={2027})

    assert bull.get("gross_margin", 2027, "Q1") == Resolved(D("0.44"), "seasonal")


def test_a_seasonal_value_outside_the_bounds_is_clamped_with_a_warning() -> None:
    out = resolve([row("gross_margin", 2027, "0.99")])

    assert out.get("gross_margin", 2027, "Q1") == Resolved(D(1), "seasonal")
    assert out.get("gross_margin", 2027, "Q2") == Resolved(D("0.98"), "seasonal")
    assert out.warnings == ("gross_margin Q1 FY2027: the seasonal value is clamped to [-1, 1]",)
    assert out.out_of_bounds_quarters() == []


def test_a_clamped_baseline_warns_once() -> None:
    """Bull's quarter offset reads Base's seasonal quarter; the clamp is Base's, not repeated."""
    base = [row("gross_margin", 2027, "0.99")]

    bull = resolve(base, [row("gross_margin", 2027, "-0.01", "offset", "Q1")])

    assert bull.get("gross_margin", 2027, "Q1") == Resolved(D("0.99"), "offset")  # 1 - 0.01
    assert len([w for w in bull.warnings if "clamped" in w]) == 0  # Bull's own Q1 is not clamped


# --- the M4 call is unchanged ----------------------------------------------------------------

M4_INPUTS = [
    ([row("revenue_growth", 2027, "0.08")], None, frozenset()),
    (
        [row("revenue_growth", 2027, "0.08"), row("gross_margin", 2027, "0.50")],
        [
            row("revenue_growth", 2028, "0.20"),
            row("gross_margin", 2027, "0.01", "offset"),
            row("gross_margin", 2028, "0.02", "offset", "Q3"),
            row("buybacks", 2027, "40", "offset"),
        ],
        frozenset(),
    ),
    (
        [row("gross_margin", 2027, "0.45", period="Q1"), row("capex_pct_revenue", 2028, "0.04")],
        [row("gross_margin", 2027, "0.01", "offset"), row("receivable_days", 2027, "3", "offset")],
        frozenset({2027}),
    ),
]


@pytest.mark.parametrize(("base", "own", "quarterly"), M4_INPUTS)
def test_empty_maps_resolve_exactly_as_the_m4_call(
    base: list[DriverRow], own: list[DriverRow] | None, quarterly: frozenset[int]
) -> None:
    is_base = own is None
    rows = base if own is None else own
    m4 = resolve_drivers(base, rows, DEFAULTS, YEARS, is_base, quarterly_years=quarterly)

    empty = resolve_drivers(
        base, rows, DEFAULTS, YEARS, is_base, quarterly, engine_values={}, seasonal={}
    )

    assert empty == m4
    assert not any(r.source in ("engine", "seasonal") for r in m4.values.values())
    assert not any(r.source in ("engine", "seasonal") for r in m4.quarter_values.values())
