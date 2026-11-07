"""What a forecast starts from: the normalized history, its driver values and defaults, the
opening period and the forecast years (docs/erd/forecasting.md "Drivers (M4)", "Start and
periods"). Pure."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
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
QUARTER_HISTORY = 8  # actual quarters shown beside the forecast quarters
YEAR_DAYS = Decimal(365)
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
    # (fiscal year, "Q1".."Q4") -> value, as entered (no Q4 derivation)
    quarter_values: Mapping[tuple[int, str], Decimal] = field(default_factory=dict)


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


class StatementValues:
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
    values = StatementValues(history.quarterly)
    if not values.periods:
        values = StatementValues(history.annual)
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
    return [p.fiscal_year for p in StatementValues(history.annual).periods][-HISTORY_YEARS:]


def history_quarters(history: ForecastHistory) -> list[Period]:
    """The last QUARTER_HISTORY actual quarters, up to the opening period, oldest first; none for
    a company with no quarterly statements."""
    quarters = StatementValues(history.quarterly).periods
    if not quarters:
        return []
    opening = opening_period(history)
    if opening.fiscal_period == "FY":
        return []
    actual = [p for p in quarters if p.end <= opening.end]
    return actual[-QUARTER_HISTORY:]


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
    return annual_driver_values(history, settings, history_years(history))


def annual_driver_values(
    history: ForecastHistory, settings: ScenarioSettings, years: Sequence[int]
) -> dict[tuple[str, int], Decimal | None]:
    """Each driver of the scenario for each of the given fiscal years of the history's annual
    tables, by the history rules (`historical_drivers` on the last actual years; the roll-up of a
    forecast year on tables that carry it)."""
    reader = _Reader(history, settings)
    return {
        (d.code, fy): reader.value(d, fy)
        for d in scenario_drivers(history, settings)
        for fy in years
    }


def historical_quarter_drivers(
    history: ForecastHistory, settings: ScenarioSettings
) -> dict[tuple[str, str], Decimal | None]:
    """Each driver of the scenario for each of the last QUARTER_HISTORY actual quarters, by (code,
    period key): the annual rules on the quarter (growth over the same quarter one year earlier,
    days over the quarter's days, `interest_rate` annualised, amounts as the quarter's); None
    where an input is missing, as the annual rules."""
    quarters = history_quarters(history)
    if not quarters:
        return {}
    reader = _Reader(history, settings, quarterly=True)
    return {
        (d.code, p.key): reader.value_at(d, p)
        for d in scenario_drivers(history, settings)
        for p in quarters
    }


def driver_values(
    history: ForecastHistory,
    settings: ScenarioSettings,
    code: str,
    freq: Literal["annual", "quarterly"],
) -> list[tuple[Period, Decimal | None]]:
    """A driver's value in every period of that frequency's tables, oldest first, by its history
    rule (a quarter as `historical_quarter_drivers` reads it); None where the rule gives none.
    Raises UnknownDriver."""
    d = driver_def(code)
    reader = _Reader(history, settings, quarterly=freq == "quarterly")
    return [(p, reader.value_at(d, p)) for p in reader.values.periods]


def default_drivers(history: ForecastHistory, settings: ScenarioSettings) -> dict[str, Default]:
    """Each driver's default: the mean of its non-null values in the last DEFAULT_YEARS fiscal
    years, else its fallback (see `Default`)."""
    reader = _Reader(history, settings)
    return {d.code: reader.default(d) for d in scenario_drivers(history, settings)}


class _Reader:
    """Reads a driver's value from one frequency's statements: the annual table (the default) or
    the quarterly one."""

    def __init__(
        self, history: ForecastHistory, settings: ScenarioSettings, quarterly: bool = False
    ) -> None:
        self.history = history
        self.settings = settings
        self.quarterly = quarterly
        self.values = StatementValues(history.quarterly if quarterly else history.annual)
        self.by_year = {p.fiscal_year: p for p in self.values.periods}
        self.order = {p.key: i for i, p in enumerate(self.values.periods)}
        self.series = {s.id: s for s in history.segment_series}

    def default(self, d: DriverDef) -> Default:
        last = [p for p in self.values.periods][-DEFAULT_YEARS:]
        found = [v for p in last if (v := self.value_at(d, p)) is not None]
        if found:
            return sum(found, Decimal(0)) / len(found)
        fallback = d.fallback
        if isinstance(fallback, Follows):
            return fallback if fallback.resolved else self.default(driver_def(fallback.code))
        if fallback == "zero":
            return Decimal(0)
        return FLAT if fallback == "flat" else None

    def value(self, d: DriverDef, fy: int) -> Decimal | None:
        period = self.by_year.get(fy)
        return None if period is None else self.value_at(d, period)

    def value_at(self, d: DriverDef, period: Period) -> Decimal | None:
        return self._rule(d.history, d.code, period)

    def _rule(self, rule: HistoryRule, code: str, period: Period) -> Decimal | None:
        line = self._line
        if isinstance(rule, Growth):
            return _growth(line(rule.code, period), line(rule.code, self._year_ago(period)))
        if isinstance(rule, SeriesGrowth):
            series = self._series(rule.series, code)
            if series is None:
                return None
            return _growth(
                self._series_value(series, period), self._series_value(series, period, 1)
            )
        if isinstance(rule, Ratio):
            numerator = line(rule.numerator, period)
            denominator = line(rule.denominator, period)
            if rule.mean_denominator:
                prior = line(rule.denominator, self._previous(period))
                denominator = (
                    None if denominator is None or prior is None else ((denominator + prior) / 2)
                )
            if numerator is None or denominator is None or denominator == 0:
                return None
            if rule.positive_denominator and denominator <= 0:
                return None
            ratio = rule.sign * numerator / denominator
            if rule.mean_denominator and self.quarterly:  # a rate per year, not per quarter
                ratio = ratio * YEAR_DAYS / days(period)
            return ratio
        if isinstance(rule, Amount):
            amount = line(rule.code, period)
            return None if amount is None else rule.sign * amount
        if isinstance(rule, Days):
            numerator, denominator = line(rule.numerator, period), line(rule.denominator, period)
            if numerator is None or denominator is None or denominator == 0:
                return None
            return numerator / denominator * days(period)
        return None  # a policy driver has no history

    def _line(self, code: str, period: Period | None) -> Decimal | None:
        return None if period is None else self.values.get(code, period.key)

    def _year_ago(self, period: Period) -> Period | None:
        """The same period one year earlier: the previous fiscal year, or the same quarter."""
        suffix = period.fiscal_period if self.quarterly else ""
        key = f"FY{period.fiscal_year - 1}{suffix}"
        return self._at(self.order.get(key))

    def _previous(self, period: Period) -> Period | None:
        """The period before: the previous fiscal year, or the previous quarter (None when a
        quarter is missing between them)."""
        if not self.quarterly:
            return self._year_ago(period)
        index = self.order.get(period.key)
        previous = None if not index else self._at(index - 1)
        if previous is None or (period.start - previous.end).days > 1:
            return None
        return previous

    def _at(self, index: int | None) -> Period | None:
        return None if index is None else self.values.periods[index]

    def _series_value(
        self, series: SeriesHistory, period: Period, years_back: int = 0
    ) -> Decimal | None:
        year = period.fiscal_year - years_back
        if self.quarterly:
            return series.quarter_values.get((year, period.fiscal_period))
        return series.fy_values.get(year)

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
    "StatementValues",
    "days",
    "default_drivers",
    "driver_values",
    "forecast_years",
    "historical_drivers",
    "historical_quarter_drivers",
    "history_quarters",
    "history_years",
    "opening_period",
    "scenario_drivers",
]
