"""Engine defaults: what each driver's default is when its engine, not the M4 mean, produces it
(docs/erd/forecasting.md "Statistical engines (M6)" → Engine choice, Defaults). Pure: the engines'
`fit` is injected (the service memoizes it; tests count its calls).

Statistics run in `float`; every value crosses back as a `Decimal` with the driver column's 10
decimals."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, cast

from bedrock.forecast import registry
from bedrock.forecast.drivers import SEASONAL, clamp, driver_def
from bedrock.forecast.engines.stl import MIN_QUARTERS, seasonal_index
from bedrock.forecast.errors import EngineFailed
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    StatementValues,
    default_drivers,
    driver_values,
    scenario_drivers,
)
from bedrock.forecast.interface import (
    ForecastResult,
    SeriesInput,
    annual_values,
    quarter_values,
)
from bedrock.statements.periods import Period

EngineCode = Literal["auto", "mean", "arima", "ets", "blend", "stl"]
ENGINE_CODES: tuple[EngineCode, ...] = ("auto", "mean", "arima", "ets", "blend", "stl")
UsedEngine = Literal["mean", "arima", "ets", "blend"]
Fit = Callable[[str, SeriesInput, int], ForecastResult]

MIN_POINTS = 8  # annual values to run a Tier 2 engine
HOLDOUT = 3  # actual years Auto scores the candidates on
TIE_ORDER = ("blend", "ets", "arima")  # Auto's preference among equal holdout errors
MEAN_NOTE = "3-year mean"


@dataclass(frozen=True)
class Band:
    """An engine's interval for one forecast year: the 90% (p05, p95) and 50% (p25, p75) ones."""

    p05: Decimal
    p25: Decimal
    p75: Decimal
    p95: Decimal


@dataclass(frozen=True)
class EngineRow:
    choice: EngineCode
    used: UsedEngine | None  # None: the driver has no numeric default (flat, missing, follows)
    note: str | None
    holdout: Mapping[str, Decimal] = field(default_factory=dict)  # engine code -> MAE
    band: Mapping[int, Band] = field(default_factory=dict)  # the cross-check band per year
    seasonal: bool = False  # `stl` is allowed (the driver is in SEASONAL)


@dataclass(frozen=True)
class EngineDefaults:
    values: Mapping[tuple[str, int], Decimal]  # (code, fiscal year) -> the engine's default
    seasonal: Mapping[str, Mapping[str, Decimal]]  # code -> Q1..Q4 -> the seasonal index
    rows: Mapping[str, EngineRow]  # every driver of the method, catalog order
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class EngineFit:
    """One Tier 2 engine fit on a driver's whole run, for the inspection payload."""

    code: str
    label: str
    values: Mapping[int, Decimal]  # fiscal year -> point (not clamped)
    band: Mapping[int, Band]
    meta: Mapping[str, Any]
    holdout_mae: Decimal | None  # None when the run is too short for a holdout or it failed
    error: str | None  # set when the engine could not forecast (values and band are then empty)


@dataclass(frozen=True)
class DriverEngines:
    code: str
    choice: EngineCode
    used: UsedEngine | None
    note: str | None
    run: list[tuple[int, Decimal]]  # the latest consecutive run of actual values
    engines: tuple[EngineFit, ...]  # registry order
    mean: Decimal | None  # the M4 default when it is a number
    seasonal: Mapping[str, Decimal] | None  # a seasonal driver with >= 12 quarters


def annual_series(
    history: ForecastHistory, settings: ScenarioSettings, code: str
) -> SeriesInput | None:
    """The driver's values in the latest consecutive run of actual fiscal years that ends at the
    last one; None when the last year's value is null. Raises UnknownDriver."""
    run = _annual_run(history, settings, code)
    if not run:
        return None
    first = run[0][0].fiscal_year
    return SeriesInput(annual_values(first, [float(v) for _, v in run]), meta=_meta(code))


def quarter_series(
    history: ForecastHistory, settings: ScenarioSettings, code: str
) -> SeriesInput | None:
    """As `annual_series`, over the quarterly table (Q4 as the table derives it)."""
    run = _run(driver_values(history, settings, code, "quarterly"), _quarter_number)
    if not run:
        return None
    start = run[0][0]
    values = quarter_values(
        start.fiscal_year, int(start.fiscal_period[1]), [float(v) for _, v in run]
    )
    return SeriesInput(values, meta=_meta(code))


def engine_defaults(
    history: ForecastHistory,
    settings: ScenarioSettings,
    choices: Mapping[str, EngineCode],
    years: Sequence[int],
    fit: Fit = registry.fit,
) -> EngineDefaults:
    """Each driver of the scenario's method by its choice (missing: `auto`). Engines run only for a
    driver whose M4 default is a number. Raises ValueError for `stl` on a driver outside
    SEASONAL."""
    context = _Context(history, settings, years, fit)
    defaults = default_drivers(history, settings)
    values: dict[tuple[str, int], Decimal] = {}
    seasonal: dict[str, Mapping[str, Decimal]] = {}
    rows: dict[str, EngineRow] = {}
    warnings: list[str] = []
    for d in scenario_drivers(history, settings):
        choice = choices.get(d.code, "auto")
        if choice == "stl" and d.code not in SEASONAL:
            raise ValueError(f"STL applies to ratio and days drivers only: {d.code}")
        if not isinstance(defaults[d.code], Decimal):
            rows[d.code] = EngineRow(choice, None, None, seasonal=d.code in SEASONAL)
            continue
        outcome = context.outcome(d.code, choice)
        rows[d.code] = outcome.row
        if outcome.point is not None:
            label = registry.ENGINES[outcome.point_engine].label
            for year, x in context.by_year(outcome.point).items():
                values[(d.code, year)] = _clamped(d.code, year, label, x, warnings)
        if outcome.seasonal is not None:
            seasonal[d.code] = outcome.seasonal
    return EngineDefaults(values, seasonal, rows, tuple(warnings))


def driver_engines(
    history: ForecastHistory,
    settings: ScenarioSettings,
    code: str,
    choice: EngineCode,
    years: Sequence[int],
    fit: Fit = registry.fit,
) -> DriverEngines:
    """One driver's run, every Tier 2 engine fit on it (with its holdout error when the run allows
    one), the M4 mean, the seasonal index and its row's note. Raises UnknownDriver."""
    driver_def(code)  # raises UnknownDriver for a code outside the catalog
    context = _Context(history, settings, years, fit)
    default = default_drivers(history, settings).get(code)
    run = context.run(code)
    numeric = isinstance(default, Decimal)
    outcome = context.outcome(code, choice) if numeric else None
    engines = tuple(context.inspect(c, run) for c in registry.ENGINES)
    return DriverEngines(
        code=code,
        choice=choice,
        used=None if outcome is None else outcome.row.used,
        note=None if outcome is None else outcome.row.note,
        run=[(p.fiscal_year, v) for p, v in _annual_run(history, settings, code)],
        engines=engines,
        mean=default if isinstance(default, Decimal) else None,
        seasonal=context.seasonal(code)[0] if code in SEASONAL else None,
    )


@dataclass(frozen=True)
class _Outcome:
    row: EngineRow
    point: ForecastResult | None  # the result whose point sets the values; None: the mean
    seasonal: Mapping[str, Decimal] | None
    point_engine: str = ""  # the engine code of `point`


class _Context:
    def __init__(
        self,
        history: ForecastHistory,
        settings: ScenarioSettings,
        years: Sequence[int],
        fit: Fit,
    ) -> None:
        self.history = history
        self.settings = settings
        self.fit = fit
        annual = StatementValues(history.annual).periods
        self.last_fy = annual[-1].fiscal_year if annual else None
        self.years = [y for y in years if self.last_fy is not None and y > self.last_fy]
        self.horizon = 0 if not self.years else max(self.years) - (self.last_fy or 0)

    def run(self, code: str) -> SeriesInput | None:
        return annual_series(self.history, self.settings, code)

    def by_year(self, result: ForecastResult) -> dict[int, float]:
        """Forecast year y takes the point at step y - last actual FY."""
        assert self.last_fy is not None  # a result exists only when a run does
        point = result.point.to_numpy(dtype=float)
        return {y: float(point[y - self.last_fy - 1]) for y in self.years}

    def bands(self, result: ForecastResult) -> dict[int, Band]:
        if result.quantiles is None or self.last_fy is None:
            return {}
        q = result.quantiles
        out = {}
        for y in self.years:
            i = y - self.last_fy - 1
            out[y] = Band(*(_decimal(float(q[c].iloc[i])) for c in ("p05", "p25", "p75", "p95")))
        return out

    def outcome(self, code: str, choice: EngineCode) -> _Outcome:
        run = self.run(code)
        n = 0 if run is None else len(run.values)
        seasonal_allowed = code in SEASONAL
        if choice in ("arima", "ets", "blend"):
            label = registry.ENGINES[choice].label
            result, note = None, None
            if run is None or n < MIN_POINTS:
                note = f"{label}: {n} years of history (needs {MIN_POINTS}); {MEAN_NOTE}"
            else:
                try:
                    result = self.fit(choice, run, self.horizon)
                except EngineFailed as exc:
                    note = f"{exc.message}; {MEAN_NOTE}"
            used: UsedEngine = choice if result is not None else "mean"
            band = {} if result is None else self.bands(result)
            row = EngineRow(choice, used, note, band=band, seasonal=seasonal_allowed)
            return _Outcome(row, result, None, choice)
        auto_used, result, note, holdout = self._auto(run)
        band = {} if result is None else self.bands(result)
        index = None
        if choice == "stl":
            index, stl_note = self.seasonal(code)
            if stl_note is not None:
                note = stl_note if note is None else f"{note}; {stl_note}"
        row = EngineRow(
            choice,
            "mean" if choice == "mean" else auto_used,
            None if choice == "mean" else note,
            holdout,
            band,
            seasonal_allowed,
        )
        return _Outcome(row, None if choice == "mean" else result, index, auto_used)

    def _auto(
        self, run: SeriesInput | None
    ) -> tuple[UsedEngine, ForecastResult | None, str | None, dict[str, Decimal]]:
        n = 0 if run is None else len(run.values)
        if run is None or n < MIN_POINTS:
            return "mean", None, f"Auto: {n} years of history (needs {MIN_POINTS}); {MEAN_NOTE}", {}
        if n < MIN_POINTS + HOLDOUT:
            note = f"Auto: {n} years of history, too few for a holdout; blend"
            try:
                return "blend", self.fit("blend", run, self.horizon), note, {}
            except EngineFailed:
                return "mean", None, f"Auto: no engine could fit; {MEAN_NOTE}", {}
        scores = {c: mae for c in registry.ENGINES if (mae := self.holdout(c, run)) is not None}
        holdout = {c: _decimal(mae) for c, mae in scores.items()}
        # the lowest error first, ties in TIE_ORDER; the first that refits on the whole run wins
        for code in sorted(scores, key=lambda c: (scores[c], TIE_ORDER.index(c))):
            try:
                result = self.fit(code, run, self.horizon)
            except EngineFailed:
                continue
            return cast(UsedEngine, code), result, None, holdout  # a Tier 2 registry code
        return "mean", None, f"Auto: no engine could fit; {MEAN_NOTE}", holdout

    def holdout(self, code: str, run: SeriesInput) -> float | None:
        """The engine's mean absolute error on the run's last HOLDOUT values, fit on the rest;
        None when it fails."""
        train = SeriesInput(run.values.iloc[:-HOLDOUT], run.exog, run.meta)
        actual = run.values.iloc[-HOLDOUT:].to_numpy(dtype=float)
        try:
            point = self.fit(code, train, HOLDOUT).point.to_numpy(dtype=float)
        except EngineFailed:
            return None
        return float(abs(point - actual).mean())

    def seasonal(self, code: str) -> tuple[dict[str, Decimal] | None, str | None]:
        """The seasonal index of the driver's quarter run, or the note saying why there is
        none."""
        run = quarter_series(self.history, self.settings, code)
        if run is None or len(run.values) < MIN_QUARTERS:
            return None, f"STL: fewer than {MIN_QUARTERS} consecutive quarters; no seasonal pattern"
        try:
            index = seasonal_index(run.values)
        except EngineFailed as exc:
            return None, f"{exc.message}; no seasonal pattern"
        return {q: _decimal(v) for q, v in index.items()}, None

    def inspect(self, code: str, run: SeriesInput | None) -> EngineFit:
        label = registry.ENGINES[code].label
        n = 0 if run is None else len(run.values)
        if run is None or n < MIN_POINTS:
            error = f"{label}: {n} years of history (needs {MIN_POINTS})"
            return EngineFit(code, label, {}, {}, {}, None, error)
        try:
            result = self.fit(code, run, self.horizon)
        except EngineFailed as exc:
            return EngineFit(code, label, {}, {}, {}, None, exc.message)
        score = self.holdout(code, run) if n >= MIN_POINTS + HOLDOUT else None
        mae = None if score is None else _decimal(score)
        values = {y: _decimal(x) for y, x in self.by_year(result).items()}
        return EngineFit(code, label, values, self.bands(result), dict(result.meta), mae, None)


def _annual_run(
    history: ForecastHistory, settings: ScenarioSettings, code: str
) -> list[tuple[Period, Decimal]]:
    return _run(driver_values(history, settings, code, "annual"), _year_number)


def _run(
    values: list[tuple[Period, Decimal | None]], number: Callable[[Period], int]
) -> list[tuple[Period, Decimal]]:
    """The latest consecutive (by `number`) non-null values ending at the last period."""
    run: list[tuple[Period, Decimal]] = []
    for period, value in reversed(values):
        if value is None or (run and number(run[-1][0]) - number(period) != 1):
            break
        run.append((period, value))
    return run[::-1]


def _year_number(period: Period) -> int:
    return period.fiscal_year


def _quarter_number(period: Period) -> int:
    return 4 * period.fiscal_year + int(period.fiscal_period[1]) - 1


def _meta(code: str) -> dict[str, str]:
    return {"code": code, "unit": driver_def(code).unit}


def _decimal(x: float) -> Decimal:
    return Decimal(f"{x:.10f}")


def _clamped(code: str, year: int, label: str, x: float, warnings: list[str]) -> Decimal:
    value = _decimal(x)
    inside = clamp(code, value)
    if inside != value:
        bounds = driver_def(code).bounds
        warnings.append(f"{code} FY{year}: the {label} value is clamped to {bounds}")
    return inside
