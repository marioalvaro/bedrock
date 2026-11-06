"""Synthetic `ForecastStatements` for the valuation tests: periods and line values stated
directly (no driver model), so a test hand-computes what it expects."""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from bedrock.forecast.engines.driver import ForecastStatements, Opening
from bedrock.forecast.resolve import Resolved, ResolvedDrivers
from bedrock.statements.fiscal_grid import period_dates
from bedrock.statements.periods import Period
from bedrock.valuation.interface import Bridge, MarketData, MultipleReference, ValuationForecast

FYE = date(2025, 12, 31)
YEARS = (2026, 2027, 2028, 2029, 2030)
Lines = Mapping[str, Decimal | int | str]


def period(key: str) -> Period:
    year, fiscal_period = int(key[2:6]), key[6:] or "FY"
    start, end = period_dates(FYE, year, fiscal_period)
    label = f"FY{year % 100:02d}E"
    return Period(
        key,
        label if fiscal_period == "FY" else f"{fiscal_period} {label}",
        year,
        fiscal_period,
        start,
        end,
    )


def statements(
    opening_key: str,
    keys: Sequence[str],
    values: Mapping[str, Lines],
    balance: Mapping[str, Decimal] | None = None,
) -> ForecastStatements:
    """Forecast periods `keys` (in order) with `values[key]` {code: value}; codes a period does not
    give are absent (null)."""
    out: dict[tuple[str, str], Decimal | None] = {}
    for key in keys:
        for code, value in values.get(key, {}).items():
            out[(code, key)] = Decimal(value)
    return ForecastStatements(
        tuple(period(k) for k in keys),
        out,
        (),
        Opening(period(opening_key), balance or {}, {}),
        frozenset(),
    )


def flows(
    operating_income: Decimal | int | str,
    d_and_a: Decimal | int | str = 0,
    capex: Decimal | int | str = 0,
    change_receivables: Decimal | int | str = 0,
    change_inventory: Decimal | int | str = 0,
    change_payables: Decimal | int | str = 0,
    **other: Decimal | int | str,
) -> dict[str, Decimal | int | str]:
    """The FCFF lines of a period (capex in its displayed, negative sign)."""
    return {
        "operating_income": operating_income,
        "d_and_a": d_and_a,
        "capex": capex,
        "change_receivables": change_receivables,
        "change_inventory": change_inventory,
        "change_payables": change_payables,
        **other,
    }


def annual_forecast(
    by_year: Mapping[int, Lines] | None = None, opening_key: str = "FY2025"
) -> ForecastStatements:
    """Five annual forecast years FY2026..FY2030 after an FY2025 opening; default lines give
    operating income 100 and nothing else."""
    by_year = by_year or {}
    return statements(
        opening_key,
        [f"FY{y}" for y in YEARS],
        {f"FY{y}": by_year.get(y, flows(100)) for y in YEARS},
    )


def quarter_forecast(
    values: Mapping[str, Lines] | None = None,
) -> ForecastStatements:
    """A company whose opening is Q2 FY2026: forecast quarters Q3 and Q4 FY2026, then the five
    years FY2026..FY2030 (FY2026 holding its actual quarters too)."""
    keys = ["FY2026Q3", "FY2026Q4", *[f"FY{y}" for y in YEARS]]
    return statements("FY2026Q2", keys, values or {})


def forecast(
    out: ForecastStatements, tax: Decimal | int | str = 0, years: Sequence[int] = YEARS
) -> ValuationForecast:
    """The valuation forecast of `out` with one tax rate for every period."""
    return ValuationForecast(out, tuple(years), {p.key: Decimal(tax) for p in out.periods})


def market(
    price: Decimal | int | str | None = 50,
    shares: Decimal | int | str | None = 10,
    price_date: date | None = FYE,
    bridge: Bridge | None = None,
    references: Mapping[str, MultipleReference] | None = None,
) -> MarketData:
    zero = Decimal(0)
    return MarketData(
        price=None if price is None else Decimal(price),
        price_date=price_date,
        shares=None if shares is None else Decimal(shares),
        bridge=bridge or Bridge(zero, zero, zero, zero, zero),
        references=references or {},
    )


def drivers(
    by_code: Mapping[str, Decimal | int | str], years: Sequence[int] = YEARS
) -> ResolvedDrivers:
    """A resolution with one value per driver for every year (source `own`)."""
    values = {
        (code, y): Resolved(Decimal(value), "own") for code, value in by_code.items() for y in years
    }
    return ResolvedDrivers(tuple(by_code), tuple(years), values, (), frozenset())
