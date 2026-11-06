"""The driver shift behind the sensitivity runs (docs/erd/valuation.md "Sensitivity" → Driver
shift). Pure."""

from decimal import Decimal

from bedrock.forecast.history import FLAT
from bedrock.forecast.perturb import shift
from bedrock.forecast.resolve import Resolved, ResolvedDrivers

D = Decimal
YEARS = (2026, 2027)


def _drivers(
    values: dict[tuple[str, int], Resolved],
    quarters: dict[tuple[str, int, str], Resolved] | None = None,
) -> ResolvedDrivers:
    codes = tuple(dict.fromkeys(code for code, _ in values))
    return ResolvedDrivers(codes, YEARS, values, (), frozenset(), quarters or {})


def _both(code: str, first: object, second: object) -> dict[tuple[str, int], Resolved]:
    def resolved(value: object) -> Resolved:
        if value is None:
            return Resolved(None, None)
        if value is FLAT:
            return Resolved(FLAT, "default")
        return Resolved(D(str(value)), "default")

    return {(code, 2026): resolved(first), (code, 2027): resolved(second)}


def test_add_moves_every_year_and_quarter_of_the_driver() -> None:
    drivers = _drivers(
        {**_both("gross_margin", "0.4", "0.42"), **_both("tax_rate", "0.2", "0.2")},
        {("gross_margin", 2026, "Q3"): Resolved(D("0.38"), "own")},
    )
    up = shift(drivers, "gross_margin", D("0.01"), "add", 1)
    assert up.get("gross_margin", 2026).value == D("0.41")
    assert up.get("gross_margin", 2027).value == D("0.43")
    assert up.get("gross_margin", 2026, "Q3") == Resolved(D("0.39"), "own")
    down = shift(drivers, "gross_margin", D("0.01"), "add", -1)
    assert down.get("gross_margin", 2026).value == D("0.39")
    # another driver does not move, and sources stay
    assert up.get("tax_rate", 2026) == Resolved(D("0.2"), "default")
    assert up.get("gross_margin", 2027).source == "default"


def test_a_quarter_with_no_entry_follows_its_shifted_year() -> None:
    drivers = _drivers(_both("gross_margin", "0.4", "0.4"))
    assert shift(drivers, "gross_margin", D("0.01"), "add", 1).get(
        "gross_margin", 2026, "Q2"
    ).value == D("0.41")


def test_scale_multiplies_by_one_plus_the_step() -> None:
    drivers = _drivers(
        _both("buybacks", 100, 200), {("buybacks", 2026, "Q1"): Resolved(D(25), "year")}
    )
    up = shift(drivers, "buybacks", D("0.1"), "scale", 1)
    assert (up.get("buybacks", 2026).value, up.get("buybacks", 2027).value) == (D(110), D(220))
    assert up.get("buybacks", 2026, "Q1").value == D("27.5")
    down = shift(drivers, "buybacks", D("0.1"), "scale", -1)
    assert down.get("buybacks", 2026).value == D(90)


def test_flat_and_missing_values_stay() -> None:
    drivers = _drivers(
        _both("receivable_days", FLAT, 40),
        {("receivable_days", 2027, "Q1"): Resolved(FLAT, "own")},
    )
    out = shift(drivers, "receivable_days", D(5), "add", 1)
    assert out.get("receivable_days", 2026) == Resolved(FLAT, "default")
    assert out.get("receivable_days", 2027).value == D(45)
    assert out.get("receivable_days", 2027, "Q1") == Resolved(FLAT, "own")
    missing = _drivers(_both("gross_margin", None, "0.3"))
    assert shift(missing, "gross_margin", D("0.01"), "add", 1).get(
        "gross_margin", 2026
    ) == Resolved(None, None)


def test_a_moved_value_is_clamped_to_a_closed_bound() -> None:
    drivers = _drivers({**_both("gross_margin", "0.995", "0.5"), **_both("tax_rate", "0.005", "0")})
    assert shift(drivers, "gross_margin", D("0.01"), "add", 1).get("gross_margin", 2026).value == 1
    assert shift(drivers, "tax_rate", D("0.01"), "add", -1).get("tax_rate", 2026).value == 0


def test_a_moved_value_is_clamped_inside_an_open_bound() -> None:
    drivers = _drivers(_both("revenue_growth", "-0.995", "0.1"))
    out = shift(drivers, "revenue_growth", D("0.01"), "add", -1)
    assert out.get("revenue_growth", 2026).value == D(-1) + D("1e-6")
    assert out.get("revenue_growth", 2027).value == D("0.09")
    amounts = _drivers(_both("buybacks", D(10) ** 15 - 1, 0))
    top = shift(amounts, "buybacks", D("0.1"), "scale", 1).get("buybacks", 2026).value
    assert top == D(10) ** 15 - D("1e-6")


def test_a_segment_driver_takes_the_segment_bounds() -> None:
    drivers = _drivers(_both("segment_growth:7", "0.05", "0.05"))
    out = shift(drivers, "segment_growth:7", D("0.01"), "add", 1)
    assert out.get("segment_growth:7", 2026).value == D("0.06")


def test_the_input_is_not_mutated() -> None:
    values = _both("gross_margin", "0.4", "0.4")
    quarters = {("gross_margin", 2026, "Q3"): Resolved(D("0.38"), "own")}
    drivers = _drivers(dict(values), dict(quarters))
    shift(drivers, "gross_margin", D("0.01"), "add", 1)
    assert dict(drivers.values) == values
    assert dict(drivers.quarter_values) == quarters
