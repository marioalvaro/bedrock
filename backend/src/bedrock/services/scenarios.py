"""Scenarios of a followed company and their drivers (FR-FCST-02..04; docs/erd/forecasting.md
"Scenarios (M4)", "API")."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bedrock.forecast.drivers import (
    METHODS,
    DriverKind,
    RevenueMethod,
    Unit,
    UnknownDriver,
    check_bounds,
    driver_def,
    segment_code,
)
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import (
    FLAT,
    ForecastHistory,
    ScenarioSettings,
    SeriesHistory,
    default_drivers,
    forecast_years,
    historical_drivers,
    history_years,
    scenario_drivers,
)
from bedrock.forecast.resolve import DriverRow, ResolvedDrivers, Source, resolve_drivers
from bedrock.models.company import Company
from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import HORIZON_QUARTERS, HORIZON_YEARS, SEGMENT_DIMENSIONS, Scenario
from bedrock.repositories import scenarios as repo
from bedrock.repositories import segments as segments_repo
from bedrock.services.errors import (
    InvalidDrivers,
    InvalidScenario,
    ScenarioConflict,
    ScenarioNotFound,
)
from bedrock.services.statements import statement_tables
from bedrock.statements.build import Freq

__all__ = [
    "DriverGrid",
    "DriverRowInput",
    "GridRow",
    "ScenarioDrivers",
    "SettingsInput",
    "create_scenario",
    "delete_scenario",
    "driver_grid",
    "ensure_defaults",
    "get_scenario",
    "list_scenarios",
    "load_history",
    "put_drivers",
    "resolve_scenario",
    "update_scenario",
]

NAME_LIMIT = 60
OFFSET_YEARS = 10  # the default offsets cover this many years from the first forecast year
# The default Bull and Bear: their sign, and their offsets at creation (docs "Scenarios" →
# Defaults). A segment's growth takes the revenue growth offset.
DEFAULT_SIGNS = {"Bull": 1, "Bear": -1}
DEFAULT_OFFSETS = {"revenue_growth": Decimal("0.03"), "gross_margin": Decimal("0.01")}
SEGMENT_OFFSET = DEFAULT_OFFSETS["revenue_growth"]
STATEMENTS = ("IS", "BS", "CF")
KPI_UNITS = {"volume_kpi": "count", "price_kpi": "USD_per_unit"}


@dataclass(frozen=True)
class SettingsInput:
    """A scenario's name and settings; None leaves a setting as it is (on create: Base's)."""

    name: str | None = None
    revenue_method: str | None = None
    segment_dimension: str | None = None
    volume_kpi: str | None = None
    price_kpi: str | None = None
    horizon_years: int | None = None
    horizon_quarters: int | None = None


@dataclass(frozen=True)
class DriverRowInput:
    """One driver's own rows of a PUT: (fiscal year, value) pairs; a None value is not stored."""

    driver_code: str
    kind: str
    values: Sequence[tuple[int, Decimal | None]]


@dataclass(frozen=True)
class GridRow:
    """One driver of the grid. `history` is aligned with the grid's history years; `values`,
    `sources` and `own` with its forecast years. A value held flat is None with source
    `default`; a required driver nothing sets is None with source None. `own` is the scenario's
    stored value or offset (as stored), `kind` the stored kind of its own rows."""

    code: str
    label: str
    group: str
    unit: Unit
    history: list[Decimal | None]
    values: list[Decimal | None]
    sources: list[Source | None]
    own: list[Decimal | None]
    kind: DriverKind | None


@dataclass(frozen=True)
class DriverGrid:
    scenario_id: int
    history_years: list[int]
    forecast_years: list[int]
    rows: list[GridRow]
    warnings: list[str]


@dataclass(frozen=True)
class ScenarioDrivers:
    """What a scenario's forecast runs on: its settings and its resolved drivers."""

    settings: ScenarioSettings
    resolved: ResolvedDrivers
    own: list[DriverValue]  # the scenario's stored rows, every year


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def load_history(session: Session, company: Company) -> ForecastHistory:
    """The company's normalized annual and quarterly IS/BS/CF tables (untrimmed, one load), its
    segment and KPI series with their FY values, and its latest fiscal year end."""
    freqs: tuple[Freq, ...] = ("annual", "quarterly")
    wanted = [(s, f) for f in freqs for s in STATEMENTS]
    tables = statement_tables(session, company, wanted, "normalized")
    series = segments_repo.list_series(session, company.id)
    fy_values: dict[int, dict[int, Decimal]] = {s.id: {} for s in series}
    for v in segments_repo.list_values(session, list(fy_values)):
        if v.fiscal_period == "FY":
            fy_values[v.series_id][v.fiscal_year] = v.value
    annual_periods = tables[("IS", "annual")].periods
    return ForecastHistory(
        annual={s: tables[(s, "annual")] for s in STATEMENTS},
        quarterly={s: tables[(s, "quarterly")] for s in STATEMENTS},
        segment_series=tuple(
            SeriesHistory(s.id, s.dimension, s.name, s.metric, s.unit, fy_values[s.id])
            for s in series
        ),
        latest_fy_end=annual_periods[-1].end if annual_periods else None,
    )


def ensure_defaults(session: Session, company: Company, now: datetime) -> None:
    """Creates Base, Bull and Bear (with their default offsets) when the company has no scenario;
    otherwise does nothing. One transaction."""
    if repo.list_for(session, company.id):
        return
    years = _offset_years(load_history(session, company))  # before the first write: no lock held
    stamp = _naive_utc(now)
    try:
        base = repo.add(
            session,
            Scenario(
                company_id=company.id,
                name="Base",
                is_default=True,
                created_at=stamp,
                updated_at=stamp,
            ),
        )
        for name, sign in DEFAULT_SIGNS.items():
            scenario = repo.add(session, _copy(base, name, stamp))
            repo.add_rows(
                session,
                (
                    _offset_row(scenario, code, year, sign * offset, stamp)
                    for code, offset in DEFAULT_OFFSETS.items()
                    for year in years
                ),
            )
        session.commit()
    except IntegrityError:
        # Another request created the defaults between the check and this write.
        session.rollback()


def list_scenarios(session: Session, company: Company, now: datetime) -> list[Scenario]:
    """The company's scenarios, Base first, then by id; creates the defaults on the first call."""
    ensure_defaults(session, company, now)
    return repo.list_for(session, company.id)


def get_scenario(session: Session, company: Company, scenario_id: int) -> Scenario:
    """Raises ScenarioNotFound for an unknown id (or another company's)."""
    stored = repo.get(session, company.id, scenario_id)
    if stored is None:
        raise ScenarioNotFound(str(scenario_id))
    return stored


def create_scenario(
    session: Session, company: Company, data: SettingsInput, now: datetime
) -> Scenario:
    """A new scenario on Base; the settings it does not give are Base's. Raises InvalidScenario
    (name, settings) and ScenarioConflict (a duplicate name)."""
    ensure_defaults(session, company, now)
    base = _base(session, company)
    name = _check_name(session, company, data.name or "", None)
    stamp = _naive_utc(now)
    scenario = _copy(base, name, stamp)
    _apply(scenario, data)
    _check_settings(session, company, scenario)
    repo.add(session, scenario)
    session.commit()
    return scenario


def update_scenario(
    session: Session, company: Company, scenario_id: int, data: SettingsInput, now: datetime
) -> Scenario:
    """Renames the scenario and changes the settings `data` gives, under the rules of
    `create_scenario`. A default Bull or Bear that moves to `segments`, or to another dimension,
    gets its offset on each segment series of the dimension without own rows. Raises
    ScenarioNotFound."""
    scenario = get_scenario(session, company, scenario_id)
    before = (scenario.revenue_method, scenario.segment_dimension)
    if data.name is not None:
        scenario.name = _check_name(session, company, data.name, scenario.id)
    try:
        _apply(scenario, data)
        _check_settings(session, company, scenario)
    except InvalidScenario:
        session.rollback()
        raise
    stamp = _naive_utc(now)
    scenario.updated_at = stamp
    after = (scenario.revenue_method, scenario.segment_dimension)
    if after[0] == "segments" and after != before:
        _segment_offsets(session, company, scenario, stamp)
    session.commit()
    return scenario


def delete_scenario(session: Session, company: Company, scenario_id: int) -> None:
    """Deletes the scenario and its driver rows. Raises ScenarioNotFound, and ScenarioConflict
    for Base."""
    scenario = get_scenario(session, company, scenario_id)
    if scenario.is_default:
        raise ScenarioConflict("Base cannot be deleted")
    repo.delete_scenario(session, scenario)
    session.commit()


def _base(session: Session, company: Company) -> Scenario:
    return next(s for s in repo.list_for(session, company.id) if s.is_default)


def _copy(base: Scenario, name: str, stamp: datetime) -> Scenario:
    return Scenario(
        company_id=base.company_id,
        name=name,
        is_default=False,
        base_id=base.id,
        revenue_method=base.revenue_method,
        segment_dimension=base.segment_dimension,
        volume_kpi=base.volume_kpi,
        price_kpi=base.price_kpi,
        horizon_years=base.horizon_years,
        horizon_quarters=base.horizon_quarters,
        created_at=stamp,
        updated_at=stamp,
    )


def _apply(scenario: Scenario, data: SettingsInput) -> None:
    for field in (
        "revenue_method",
        "segment_dimension",
        "volume_kpi",
        "price_kpi",
        "horizon_years",
        "horizon_quarters",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(scenario, field, value)


def _check_name(session: Session, company: Company, name: str, own_id: int | None) -> str:
    clean = name.strip()
    if not clean:
        raise InvalidScenario("The name must not be blank")
    if len(clean) > NAME_LIMIT:
        raise InvalidScenario(f"The name must be at most {NAME_LIMIT} characters")
    if any(s.name == clean and s.id != own_id for s in repo.list_for(session, company.id)):
        raise ScenarioConflict(f"The company already has a scenario named {clean!r}")
    return clean


def _check_settings(session: Session, company: Company, scenario: Scenario) -> None:
    method = scenario.revenue_method
    if method not in METHODS:
        raise InvalidScenario(f"revenue_method must be one of {', '.join(METHODS)}")
    dimension = scenario.segment_dimension
    if dimension is not None and dimension not in SEGMENT_DIMENSIONS:
        raise InvalidScenario(f"segment_dimension must be one of {', '.join(SEGMENT_DIMENSIONS)}")
    if method == "segments" and dimension is None:
        raise InvalidScenario("The segments method needs a segment_dimension")
    for low, high, field in (
        (*HORIZON_YEARS, "horizon_years"),
        (*HORIZON_QUARTERS, "horizon_quarters"),
    ):
        if not low <= getattr(scenario, field) <= high:
            raise InvalidScenario(f"{field} must be between {low} and {high}")
    if method != "volume_price":  # a KPI kept from an earlier method is not used, nor checked
        return
    kpis = {
        s.metric: s.unit
        for s in segments_repo.list_series(session, company.id)
        if s.dimension == "kpi"
    }
    for field, unit in KPI_UNITS.items():
        code = getattr(scenario, field)
        if code is None:
            raise InvalidScenario(f"The volume_price method needs a {field}")
        if kpis.get(code) != unit:
            raise InvalidScenario(
                f"{field} {code!r} is not a KPI of {company.ticker} with unit {unit}"
            )


def _offset_years(history: ForecastHistory) -> list[int]:
    try:
        return forecast_years(history, OFFSET_YEARS)
    except ForecastUnavailable:  # no opening balance sheet: no forecast years to offset
        return []


def _segment_offsets(
    session: Session, company: Company, scenario: Scenario, stamp: datetime
) -> None:
    sign = DEFAULT_SIGNS.get(scenario.name)
    if scenario.is_default or sign is None:
        return
    history = load_history(session, company)
    owned = {r.driver_code for r in repo.list_rows(session, [scenario.id])}
    codes = [
        segment_code(s.id)
        for s in history.segment_series
        if s.dimension == scenario.segment_dimension and s.metric == "revenue"
    ]
    years = _offset_years(history)
    repo.add_rows(
        session,
        (
            _offset_row(scenario, code, year, sign * SEGMENT_OFFSET, stamp)
            for code in codes
            if code not in owned
            for year in years
        ),
    )


def _offset_row(
    scenario: Scenario, code: str, year: int, value: Decimal, stamp: datetime
) -> DriverValue:
    return DriverValue(
        scenario_id=scenario.id,
        driver_code=code,
        fiscal_year=year,
        fiscal_period="FY",
        kind="offset",
        value=value,
        source="manual",
        created_at=stamp,
        updated_at=stamp,
    )


def resolve_scenario(
    session: Session, scenario: Scenario, history: ForecastHistory
) -> ScenarioDrivers:
    """The scenario's drivers resolved for its forecast years (docs "Scenarios" → Resolution).
    Raises ForecastUnavailable when the history has no opening."""
    settings = settings_of(scenario)
    years = forecast_years(history, scenario.horizon_years)
    ids = [scenario.id] if scenario.base_id is None else [scenario.id, scenario.base_id]
    rows = repo.list_rows(session, ids)
    own = [r for r in rows if r.scenario_id == scenario.id]
    base = [r for r in rows if r.scenario_id == scenario.base_id]
    resolved = resolve_drivers(
        [_driver_row(r) for r in base],
        [_driver_row(r) for r in own],
        default_drivers(history, settings),
        years,
        scenario.is_default,
    )
    return ScenarioDrivers(settings, resolved, own)


def settings_of(scenario: Scenario) -> ScenarioSettings:
    method: RevenueMethod = scenario.revenue_method  # type: ignore[assignment]  # checked on write
    return ScenarioSettings(
        method, scenario.segment_dimension, scenario.volume_kpi, scenario.price_kpi
    )


def driver_grid(session: Session, company: Company, scenario_id: int) -> DriverGrid:
    """The drivers of the scenario's revenue method in catalog order, each with its last
    HISTORY_YEARS actual values and its resolved value and source per forecast year. Raises
    ScenarioNotFound, and ForecastUnavailable when the company has no opening balance sheet."""
    scenario = get_scenario(session, company, scenario_id)
    history = load_history(session, company)
    drivers = resolve_scenario(session, scenario, history)
    past = history_years(history)
    actual = historical_drivers(history, drivers.settings)
    years = list(drivers.resolved.years)
    own = {(r.driver_code, r.fiscal_year): r for r in drivers.own}
    kinds = {r.driver_code: r.kind for r in drivers.own}
    rows = []
    for d in scenario_drivers(history, drivers.settings):
        resolved = [drivers.resolved.get(d.code, y) for y in years]
        stored = [own.get((d.code, y)) for y in years]
        rows.append(
            GridRow(
                code=d.code,
                label=d.label,
                group=d.group,
                unit=d.unit,
                history=[actual[(d.code, y)] for y in past],
                values=[None if r.value is FLAT else r.value for r in resolved],
                sources=[r.source for r in resolved],
                own=[None if r is None else r.value for r in stored],
                kind=kinds.get(d.code),  # type: ignore[arg-type]  # checked by the schema
            )
        )
    warnings = list(drivers.resolved.warnings)
    method = drivers.settings.revenue_method
    if method != "growth" and any(
        r.driver_code == "revenue_growth" and r.kind == "offset" for r in drivers.own
    ):
        warnings.append(f"Offsets on revenue_growth are not used by the {method} method")
    return DriverGrid(scenario.id, past, years, rows, warnings)


def put_drivers(
    session: Session,
    company: Company,
    scenario_id: int,
    rows: Sequence[DriverRowInput],
    now: datetime,
) -> DriverGrid:
    """Each row replaces every stored row of its driver in the scenario (every year, stale ones
    included); its None values are not stored. All rows are checked before anything is written.
    Raises ScenarioNotFound, InvalidDrivers and ForecastUnavailable (no opening)."""
    scenario = get_scenario(session, company, scenario_id)
    history = load_history(session, company)
    settings = settings_of(scenario)
    years = forecast_years(history, scenario.horizon_years)
    allowed = {d.code for d in scenario_drivers(history, settings)}
    stamp = _naive_utc(now)
    seen: set[str] = set()
    new: list[DriverValue] = []
    for row in rows:
        _check_row(row, scenario, settings, allowed, years, seen)
        new.extend(
            DriverValue(
                scenario_id=scenario.id,
                driver_code=row.driver_code,
                fiscal_year=year,
                fiscal_period="FY",
                kind=row.kind,
                value=value,
                source="manual",
                created_at=stamp,
                updated_at=stamp,
            )
            for year, value in row.values
            if value is not None
        )
    repo.delete_rows(session, scenario.id, seen)
    repo.add_rows(session, new)
    scenario.updated_at = stamp
    session.commit()
    return driver_grid(session, company, scenario.id)


def _check_row(
    row: DriverRowInput,
    scenario: Scenario,
    settings: ScenarioSettings,
    allowed: set[str],
    years: list[int],
    seen: set[str],
) -> None:
    code = row.driver_code
    try:
        driver_def(code)
    except UnknownDriver as error:
        raise InvalidDrivers(str(error)) from error
    if code not in allowed:
        raise InvalidDrivers(f"{code} is not a driver of the {settings.revenue_method} method")
    if code in seen:
        raise InvalidDrivers(f"{code} is given twice")
    seen.add(code)
    if row.kind not in ("value", "offset"):
        raise InvalidDrivers("kind must be value or offset")
    if row.kind == "offset" and scenario.is_default:
        raise InvalidDrivers("Base cannot hold offsets")
    given: set[int] = set()
    for year, value in row.values:
        if year not in years:
            raise InvalidDrivers(f"FY{year} is not a forecast year (FY{years[0]}-FY{years[-1]})")
        if year in given:
            raise InvalidDrivers(f"FY{year} is given twice for {code}")
        given.add(year)
        if value is not None:
            message = check_bounds(code, row.kind, value)  # type: ignore[arg-type]  # checked
            if message is not None:
                raise InvalidDrivers(message)


def _driver_row(row: DriverValue) -> DriverRow:
    return DriverRow(row.driver_code, row.fiscal_year, row.kind, row.value)  # type: ignore[arg-type]
