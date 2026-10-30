"""What a forecast starts from: the normalized history, its driver values and defaults, the
opening period and the forecast years (docs/erd/forecasting.md "Drivers (M4)", "Start and
periods"). Pure."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from bedrock.forecast.drivers import (
    Amount,
    Days,
    DriverDef,
    Follows,
    Growth,
    HistoryRule,
    Ratio,
    RevenueMethod,
    SeriesGrowth,
    driver_def,
    drivers_for,
    segment_id,
)
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.statements.build import StatementTable
from bedrock.statements.periods import Period

HISTORY_YEARS = 5  # shown beside the forecast years
DEFAULT_YEARS = 3  # the default is the mean of this many last years
OPENING_TOTALS = ("total_assets", "total_liabilities_and_equity", "total_equity", "revenue")


class _Flat(Enum):
    FLAT = "flat"


FLAT = _Flat.FLAT  # the line is held at its opening value
Flat = Literal[_Flat.FLAT]
# A driver's default for every forecast year: a value; None (required, nothing to default to);
# FLAT; or Follows(code, resolved=True), which `resolve.py` fills with that driver's resolved value.
Default = Decimal | None | Flat | Follows


@dataclass(frozen=True)
class SeriesHistory:
    """A segment or KPI series (M3) with its FY values."""

    id: int
    dimension: str  # business | geo | kpi
    name: str
    metric: str  # revenue | operating_income; the KPI code for kpi
    unit: str
    fy_values: Mapping[int, Decimal]


@dataclass(frozen=True)
class ForecastHistory:
    annual: Mapping[str, StatementTable]  # IS, BS, CF on the normalized basis, untrimmed
    quarterly: Mapping[str, StatementTable]
    segment_series: tuple[SeriesHistory, ...]
    latest_fy_end: date | None


@dataclass(frozen=True)
class ScenarioSettings:
    """The settings of a scenario the drivers depend on."""

    revenue_method: RevenueMethod
    segment_dimension: str | None = None
    volume_kpi: str | None = None
    price_kpi: str | None = None


class _Values:
    """Every value of one frequency's tables by (code, period key), and its periods in order."""

    def __init__(self, tables: Mapping[str, StatementTable]) -> None:
        self.cells: dict[tuple[str, str], Decimal | None] = {}
        self.periods: list[Period] = []
        for table in tables.values():
            if len(table.periods) > len(self.periods):
                self.periods = table.periods
            for row in table.rows:
                for period, value in zip(table.periods, row.values, strict=True):
                    self.cells[(row.code, period.key)] = value

    def get(self, code: str, key: str) -> Decimal | None:
        return self.cells.get((code, key))


def opening_period(history: ForecastHistory) -> Period:
    """The latest quarter (the latest FY for a company with no quarters) whose balance sheet has
    its totals and whose revenue is not null. Raises ForecastUnavailable."""
    values = _Values(history.quarterly)
    if not values.periods:
        values = _Values(history.annual)
    for period in reversed(values.periods):
        if all(values.get(code, period.key) is not None for code in OPENING_TOTALS):
            return period
    raise ForecastUnavailable("No complete balance sheet to start from")


def forecast_years(history: ForecastHistory, horizon_years: int) -> list[int]:
    """`horizon_years` fiscal years from the opening's year when it is Q1-Q3, else the next one.
    Raises ForecastUnavailable."""
    opening = opening_period(history)
    first = opening.fiscal_year + (0 if opening.fiscal_period in ("Q1", "Q2", "Q3") else 1)
    return list(range(first, first + horizon_years))


def history_years(history: ForecastHistory) -> list[int]:
    """The last HISTORY_YEARS actual fiscal years, oldest first."""
    return [p.fiscal_year for p in _Values(history.annual).periods][-HISTORY_YEARS:]


def scenario_drivers(history: ForecastHistory, settings: ScenarioSettings) -> list[DriverDef]:
    """The drivers of the scenario's revenue method; for `segments`, one per revenue series of its
    dimension, in the series' order."""
    segments = [
        (s.id, s.name)
        for s in history.segment_series
        if s.dimension == settings.segment_dimension and s.metric == "revenue"
    ]
    return drivers_for(settings.revenue_method, segments)


def historical_drivers(
    history: ForecastHistory, settings: ScenarioSettings
) -> dict[tuple[str, int], Decimal | None]:
    """Each driver of the scenario for each history year; None where an input is missing or a
    denominator is 0 (or the driver's own null rule applies)."""
    reader = _Reader(history, settings)
    return {
        (d.code, fy): reader.value(d, fy)
        for d in scenario_drivers(history, settings)
        for fy in history_years(history)
    }


def default_drivers(history: ForecastHistory, settings: ScenarioSettings) -> dict[str, Default]:
    """Each driver's default: the mean of its non-null values in the last DEFAULT_YEARS fiscal
    years, else its fallback (see `Default`)."""
    reader = _Reader(history, settings)
    return {d.code: reader.default(d) for d in scenario_drivers(history, settings)}


class _Reader:
    def __init__(self, history: ForecastHistory, settings: ScenarioSettings) -> None:
        self.history = history
        self.settings = settings
        self.annual = _Values(history.annual)
        self.by_year = {p.fiscal_year: p for p in self.annual.periods}
        self.series = {s.id: s for s in history.segment_series}

    def default(self, d: DriverDef) -> Default:
        last = [p.fiscal_year for p in self.annual.periods][-DEFAULT_YEARS:]
        found = [v for fy in last if (v := self.value(d, fy)) is not None]
        if found:
            return sum(found, Decimal(0)) / len(found)
        fallback = d.fallback
        if isinstance(fallback, Follows):
            return fallback if fallback.resolved else self.default(driver_def(fallback.code))
        if fallback == "zero":
            return Decimal(0)
        return FLAT if fallback == "flat" else None

    def value(self, d: DriverDef, fy: int) -> Decimal | None:
        return self._rule(d.history, d.code, fy)

    def _rule(self, rule: HistoryRule, code: str, fy: int) -> Decimal | None:
        line = self._line
        if isinstance(rule, Growth):
            return _growth(line(rule.code, fy), line(rule.code, fy - 1))
        if isinstance(rule, SeriesGrowth):
            series = self._series(rule.series, code)
            if series is None:
                return None
            return _growth(series.fy_values.get(fy), series.fy_values.get(fy - 1))
        if isinstance(rule, Ratio):
            numerator = line(rule.numerator, fy)
            denominator = line(rule.denominator, fy)
            if rule.mean_denominator:
                prior = line(rule.denominator, fy - 1)
                denominator = (
                    None if denominator is None or prior is None else ((denominator + prior) / 2)
                )
            if numerator is None or denominator is None or denominator == 0:
                return None
            if rule.positive_denominator and denominator <= 0:
                return None
            return rule.sign * numerator / denominator
        if isinstance(rule, Amount):
            amount = line(rule.code, fy)
            return None if amount is None else rule.sign * amount
        if isinstance(rule, Days):
            numerator, denominator = line(rule.numerator, fy), line(rule.denominator, fy)
            period = self.by_year.get(fy)
            if numerator is None or denominator is None or denominator == 0 or period is None:
                return None
            return numerator / denominator * days(period)
        return None  # a policy driver has no history

    def _line(self, code: str, fy: int) -> Decimal | None:
        return self.annual.get(code, f"FY{fy}")

    def _series(self, which: str, code: str) -> SeriesHistory | None:
        if which == "segment":
            series_id = segment_id(code)
            return None if series_id is None else self.series.get(series_id)
        kpi = self.settings.volume_kpi if which == "volume" else self.settings.price_kpi
        return next(
            (s for s in self.series.values() if s.dimension == "kpi" and s.metric == kpi), None
        )


def days(period: Period) -> int:
    """days(p) = (end - start).days + 1."""
    return (period.end - period.start).days + 1


def _growth(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    if current is None or prior is None or prior == 0:
        return None
    return current / prior - 1


__all__ = [
    "FLAT",
    "Default",
    "Flat",
    "ForecastHistory",
    "ScenarioSettings",
    "SeriesHistory",
    "days",
    "default_drivers",
    "forecast_years",
    "historical_drivers",
    "history_years",
    "opening_period",
    "scenario_drivers",
]
