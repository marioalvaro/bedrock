"""Scenarios of a followed company, their three cases and the drivers of each case (FR-FCST-02..05;
docs/erd/forecasting.md "Scenarios and cases", "API")."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bedrock.forecast.driver_io import (
    DriverChange,
    DriverFileError,
    export_csv,
    export_xlsx,
    parse_driver_file,
    plan_import,
)
from bedrock.forecast.drivers import (
    METHODS,
    QUARTERS,
    DriverDef,
    RevenueMethod,
    UnknownDriver,
    check_bounds,
    driver_def,
    segment_code,
)
from bedrock.forecast.engines.driver import FORECAST_HORIZON, DriverModel, forecast_quarters
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.grid import DriverGrid, GridPeriod, GridRow, YearMode
from bedrock.forecast.history import (
    FLAT,
    ForecastHistory,
    ScenarioSettings,
    SeriesHistory,
    default_drivers,
    forecast_years,
    historical_drivers,
    historical_quarter_drivers,
    history_quarters,
    history_years,
    scenario_drivers,
)
from bedrock.forecast.modes import fill_quarters
from bedrock.forecast.resolve import DriverRow, ResolvedDrivers, resolve_drivers
from bedrock.forecast.rollup import rollup
from bedrock.models.company import Company
from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import (
    CASES,
    SEGMENT_DIMENSIONS,
    YEAR_MODES,
    Scenario,
    ScenarioCase,
)
from bedrock.repositories import scenarios as repo
from bedrock.repositories import segments as segments_repo
from bedrock.services.errors import (
    InvalidDriverFile,
    InvalidDrivers,
    InvalidScenario,
    ScenarioConflict,
    ScenarioNotFound,
)
from bedrock.services.statements import statement_tables
from bedrock.statements.build import Freq

__all__ = [
    "DriverGrid",
    "DriverImportResult",
    "DriverRowInput",
    "GridPeriod",
    "GridRow",
    "ScenarioDrivers",
    "SettingsInput",
    "YearMode",
    "built_from_quarters",
    "create_scenario",
    "delete_scenario",
    "driver_grid",
    "ensure_defaults",
    "export_drivers",
    "get_case",
    "get_scenario",
    "import_drivers",
    "list_scenarios",
    "load_history",
    "put_drivers",
    "reset_case",
    "resolve_case",
    "set_year_mode",
    "update_scenario",
    "year_modes",
]

NAME_LIMIT = 60
DEFAULT_NAME = "Main"
# The sign of a case's default offsets (docs "Scenarios and cases" → Defaults): Bull and Bear
# override their scenario's Base; Base has no rows.
CASE_SIGNS = {"bull": 1, "bear": -1}
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


@dataclass(frozen=True)
class DriverRowInput:
    """One driver's own rows of a PUT: (fiscal year, value) pairs, or for a `quarterly` row
    (fiscal year, quarter, value) triples in `quarters`; a None value is not stored. `values` is
    for an annual row and `quarters` for a quarterly one: a row that fills the other is refused."""

    driver_code: str
    kind: str
    values: Sequence[tuple[int, Decimal | None]] = ()
    freq: str = "annual"
    quarters: Sequence[tuple[int, str, Decimal | None]] = ()


@dataclass(frozen=True)
class DriverImportResult:
    """What a driver file changes; `grid` is the new grid after a confirmed import, None for a
    dry run."""

    changes: list[DriverChange]
    grid: DriverGrid | None


@dataclass(frozen=True)
class ScenarioDrivers:
    """What a scenario's forecast runs on: its settings and its resolved drivers."""

    settings: ScenarioSettings
    resolved: ResolvedDrivers
    own: list[DriverValue]  # the case's stored rows, every year


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
    quarter_values: dict[int, dict[tuple[int, str], Decimal]] = {s.id: {} for s in series}
    for v in segments_repo.list_values(session, list(fy_values)):
        if v.fiscal_period == "FY":
            fy_values[v.series_id][v.fiscal_year] = v.value
        else:
            quarter_values[v.series_id][(v.fiscal_year, v.fiscal_period)] = v.value
    annual_periods = tables[("IS", "annual")].periods
    return ForecastHistory(
        annual={s: tables[(s, "annual")] for s in STATEMENTS},
        quarterly={s: tables[(s, "quarterly")] for s in STATEMENTS},
        segment_series=tuple(
            SeriesHistory(
                s.id, s.dimension, s.name, s.metric, s.unit, fy_values[s.id], quarter_values[s.id]
            )
            for s in series
        ),
        latest_fy_end=annual_periods[-1].end if annual_periods else None,
    )


def ensure_defaults(session: Session, company: Company, now: datetime) -> None:
    """Creates the default scenario "Main" with its three cases (and their default offsets) when
    the company has no scenario; otherwise does nothing. One transaction."""
    if repo.list_for(session, company.id):
        return
    history = load_history(session, company)  # before the first write: no lock held
    stamp = _naive_utc(now)
    try:
        main = repo.add(
            session,
            Scenario(
                company_id=company.id,
                name=DEFAULT_NAME,
                is_default=True,
                created_at=stamp,
                updated_at=stamp,
            ),
        )
        _add_cases(session, main, history, stamp)
        session.commit()
    except IntegrityError:
        # Another request created the defaults between the check and this write.
        session.rollback()


def list_scenarios(session: Session, company: Company, now: datetime) -> list[Scenario]:
    """The company's scenarios, the default first, then by id; creates the default on the first
    call."""
    ensure_defaults(session, company, now)
    return repo.list_for(session, company.id)


def get_scenario(session: Session, company: Company, scenario_id: int) -> Scenario:
    """Raises ScenarioNotFound for an unknown id (or another company's)."""
    stored = repo.get(session, company.id, scenario_id)
    if stored is None:
        raise ScenarioNotFound(str(scenario_id))
    return stored


def get_case(
    session: Session, company: Company, scenario_id: int, case: str
) -> tuple[Scenario, ScenarioCase]:
    """The scenario and one of its cases. Raises ScenarioNotFound, and InvalidScenario for a case
    other than base, bull or bear."""
    scenario = get_scenario(session, company, scenario_id)
    if case not in CASES:
        raise InvalidScenario(f"case must be one of {', '.join(CASES)}")
    kase = repo.cases_of(session, scenario.id).get(case)
    if kase is None:  # the scenario was deleted after the lookup
        raise ScenarioNotFound(str(scenario_id))
    return scenario, kase


def create_scenario(
    session: Session, company: Company, data: SettingsInput, now: datetime
) -> Scenario:
    """A new scenario with three cases holding their default offsets (no copy of another
    scenario); the settings it does not give are the default scenario's. Raises InvalidScenario
    (name, settings) and ScenarioConflict (a duplicate name)."""
    ensure_defaults(session, company, now)
    default = _default_scenario(session, company)
    name = _check_name(session, company, data.name or "", None)
    stamp = _naive_utc(now)
    scenario = _copy(default, name, stamp)
    _apply(scenario, data)
    _check_settings(session, company, scenario)
    history = load_history(session, company)  # before the first write: no lock held
    repo.add(session, scenario)
    _add_cases(session, scenario, history, stamp)
    session.commit()
    return scenario


def update_scenario(
    session: Session, company: Company, scenario_id: int, data: SettingsInput, now: datetime
) -> Scenario:
    """Renames the scenario and changes the settings `data` gives, under the rules of
    `create_scenario`; the settings apply to all three cases. A switch to `segments`, or to
    another dimension, gives Bull and Bear their offset on each segment series of the dimension
    without own rows. Raises ScenarioNotFound."""
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
    """Deletes the scenario, its cases and their driver rows. Raises ScenarioNotFound, and
    ScenarioConflict for the default scenario."""
    scenario = get_scenario(session, company, scenario_id)
    if scenario.is_default:
        raise ScenarioConflict("The default scenario cannot be deleted")
    repo.delete_scenario(session, scenario)
    session.commit()


def reset_case(
    session: Session, company: Company, scenario_id: int, case: str, now: datetime
) -> DriverGrid:
    """Deletes every row of the case, then writes its defaults (`base`: none, so every driver
    goes back to its default), and returns the case's grid. Raises ScenarioNotFound,
    InvalidScenario (case) and ForecastUnavailable (no opening; nothing is written)."""
    scenario, kase = get_case(session, company, scenario_id, case)
    history = load_history(session, company)
    forecast_years(history, FORECAST_HORIZON.years)
    stamp = _naive_utc(now)
    repo.delete_all_rows(session, kase.id)
    repo.add_rows(
        session, _case_rows(kase, _default_rows(case, settings_of(scenario), history), stamp)
    )
    for year in sorted(repo.quarterly_years(session, scenario.id)):
        repo.add_rows(session, _fill_year(session, scenario, case, kase, history, year, stamp))
    kase.updated_at = scenario.updated_at = stamp
    session.commit()
    return _grid(session, scenario, case, history)


def year_modes(session: Session, company: Company, scenario_id: int) -> list[YearMode]:
    """How each forecast year of the scenario is set, in year order. Raises ScenarioNotFound and
    ForecastUnavailable (no opening balance sheet)."""
    scenario = get_scenario(session, company, scenario_id)
    return _year_modes(session, scenario, load_history(session, company))


def _year_modes(session: Session, scenario: Scenario, history: ForecastHistory) -> list[YearMode]:
    years = forecast_years(history, FORECAST_HORIZON.years)
    span = {y for y, _ in forecast_quarters(history)}
    quarterly = repo.quarterly_years(session, scenario.id)
    return [
        YearMode(
            y,
            f"FY{y % 100:02d}E",
            "quarterly" if y in quarterly and y in span else "annual",
            y in span,
        )
        for y in years
    ]


def set_year_mode(
    session: Session,
    company: Company,
    scenario_id: int,
    fiscal_year: int,
    mode: str,
    now: datetime,
) -> list[YearMode]:
    """Sets a year of the quarterly span annual or by quarter, for the scenario's three cases at
    once, and returns the scenario's modes. `quarterly` writes the year's quarter rows from what
    each case resolves to today (`forecast/modes.py::fill_quarters`), so no forecast number
    changes; `annual` deletes the year's quarter rows. Both are idempotent. Raises
    ScenarioNotFound, InvalidScenario (mode, a year outside the forecast years or the span) and
    ForecastUnavailable (no opening, or no quarterly history)."""
    scenario = get_scenario(session, company, scenario_id)
    if mode not in YEAR_MODES:
        raise InvalidScenario("mode must be annual or quarterly")
    history = load_history(session, company)
    years = forecast_years(history, FORECAST_HORIZON.years)
    if not history_quarters(history):
        raise ForecastUnavailable("No quarterly history")
    if fiscal_year not in years:
        raise InvalidScenario(
            f"FY{fiscal_year} is not a forecast year (FY{years[0]}-FY{years[-1]})"
        )
    if fiscal_year not in {y for y, _ in forecast_quarters(history)}:
        raise InvalidScenario(f"FY{fiscal_year} is not in the quarterly span")
    stamp = _naive_utc(now)
    cases = repo.cases_of(session, scenario.id)
    if mode == "quarterly":
        # every case is resolved before the first write: the fills read the rows as they are now
        fills = {
            case: _fill_year(session, scenario, case, kase, history, fiscal_year, stamp)
            for case, kase in cases.items()
        }
        for rows in fills.values():
            repo.add_rows(session, rows)
    else:
        repo.delete_year_quarters(session, [k.id for k in cases.values()], fiscal_year)
    repo.set_quarterly(session, scenario.id, fiscal_year, mode == "quarterly")
    scenario.updated_at = stamp
    for kase in cases.values():
        kase.updated_at = stamp
    session.commit()
    return _year_modes(session, scenario, history)


def built_from_quarters(
    session: Session, scenario: Scenario, history: ForecastHistory
) -> list[int]:
    """The forecast years the scenario sets by quarter, in year order."""
    return [m.fiscal_year for m in _year_modes(session, scenario, history) if m.mode == "quarterly"]


def _fill_year(
    session: Session,
    scenario: Scenario,
    case: str,
    kase: ScenarioCase,
    history: ForecastHistory,
    year: int,
    stamp: datetime,
) -> list[DriverValue]:
    """The quarter rows that fill the case's forecast quarters of `year` as it resolves now."""
    drivers = resolve_case(session, scenario, case, history)
    quarters = [q for y, q in forecast_quarters(history) if y == year]
    filled = fill_quarters(
        year, quarters, drivers.resolved, [_driver_row(r) for r in drivers.own], case == "base"
    )
    return [
        DriverValue(
            case_id=kase.id,
            driver_code=r.code,
            fiscal_year=r.fiscal_year,
            fiscal_period=r.fiscal_period,
            kind=r.kind,
            value=r.value,
            source="manual",
            created_at=stamp,
            updated_at=stamp,
        )
        for r in filled
    ]


def _default_scenario(session: Session, company: Company) -> Scenario:
    return next(s for s in repo.list_for(session, company.id) if s.is_default)


def _copy(default: Scenario, name: str, stamp: datetime) -> Scenario:
    return Scenario(
        company_id=default.company_id,
        name=name,
        is_default=False,
        revenue_method=default.revenue_method,
        segment_dimension=default.segment_dimension,
        volume_kpi=default.volume_kpi,
        price_kpi=default.price_kpi,
        created_at=stamp,
        updated_at=stamp,
    )


def _apply(scenario: Scenario, data: SettingsInput) -> None:
    for field in (
        "revenue_method",
        "segment_dimension",
        "volume_kpi",
        "price_kpi",
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
        return forecast_years(history, FORECAST_HORIZON.years)
    except ForecastUnavailable:  # no opening balance sheet: no forecast years to offset
        return []


def _add_cases(
    session: Session, scenario: Scenario, history: ForecastHistory, stamp: datetime
) -> None:
    """Gives the scenario its three cases, each with its default rows."""
    settings = settings_of(scenario)
    for case, kase in repo.add_cases(session, scenario, stamp).items():
        repo.add_rows(session, _case_rows(kase, _default_rows(case, settings, history), stamp))


def _default_rows(
    case: str, settings: ScenarioSettings, history: ForecastHistory
) -> list[tuple[str, int, Decimal]]:
    """The (driver code, fiscal year, offset) rows a case starts with: `base` none; `bull` and
    `bear` the revenue growth and gross margin offsets for the forecast years and, on `segments`,
    the revenue growth offset on each segment series of the dimension. The sign comes from the
    case."""
    sign = CASE_SIGNS.get(case)
    if sign is None:
        return []
    years = _offset_years(history)
    rows = [
        (code, year, sign * offset) for code, offset in DEFAULT_OFFSETS.items() for year in years
    ]
    if settings.revenue_method == "segments":
        rows += _segment_rows(sign, settings.segment_dimension, history, years, ())
    return rows


def _segment_rows(
    sign: int,
    dimension: str | None,
    history: ForecastHistory,
    years: Sequence[int],
    owned: Collection[str],
) -> list[tuple[str, int, Decimal]]:
    """The offset on each revenue series of `dimension` not in `owned`, for `years`."""
    codes = [
        segment_code(s.id)
        for s in history.segment_series
        if s.dimension == dimension and s.metric == "revenue"
    ]
    return [(c, y, sign * SEGMENT_OFFSET) for c in codes if c not in owned for y in years]


def _case_rows(
    case: ScenarioCase, rows: Sequence[tuple[str, int, Decimal]], stamp: datetime
) -> list[DriverValue]:
    return [
        DriverValue(
            case_id=case.id,
            driver_code=code,
            fiscal_year=year,
            fiscal_period="FY",
            kind="offset",
            value=value,
            source="manual",
            created_at=stamp,
            updated_at=stamp,
        )
        for code, year, value in rows
    ]


def _segment_offsets(
    session: Session, company: Company, scenario: Scenario, stamp: datetime
) -> None:
    """Gives Bull and Bear their offset on each segment series of the scenario's dimension that
    the case holds no rows for."""
    history = load_history(session, company)
    years = _offset_years(history)
    cases = repo.cases_of(session, scenario.id)
    stored = repo.list_rows(session, [cases[case].id for case in CASE_SIGNS])
    for case, sign in CASE_SIGNS.items():
        owned = {r.driver_code for r in stored if r.case_id == cases[case].id}
        rows = _segment_rows(sign, scenario.segment_dimension, history, years, owned)
        repo.add_rows(session, _case_rows(cases[case], rows, stamp))


def resolve_case(
    session: Session, scenario: Scenario, case: str, history: ForecastHistory
) -> ScenarioDrivers:
    """The case's drivers resolved for its scenario's forecast years (docs "Scenarios (M4)" →
    Resolution, with the scenario's `base` case as Base). Raises ForecastUnavailable when the
    history has no opening."""
    settings = settings_of(scenario)
    years = forecast_years(history, FORECAST_HORIZON.years)
    cases = repo.cases_of(session, scenario.id)
    is_base = case == "base"
    rows = repo.list_rows(session, [cases[case].id, cases["base"].id])
    own = [r for r in rows if r.case_id == cases[case].id]
    base = [] if is_base else [r for r in rows if r.case_id == cases["base"].id]
    resolved = resolve_drivers(
        [_driver_row(r) for r in base],
        [_driver_row(r) for r in own],
        default_drivers(history, settings),
        years,
        is_base,
    )
    return ScenarioDrivers(settings, resolved, own)


def settings_of(scenario: Scenario) -> ScenarioSettings:
    method: RevenueMethod = scenario.revenue_method  # type: ignore[assignment]  # checked on write
    return ScenarioSettings(
        method, scenario.segment_dimension, scenario.volume_kpi, scenario.price_kpi
    )


def driver_grid(
    session: Session,
    company: Company,
    scenario_id: int,
    case: str,
    freq: Literal["annual", "quarterly"] = "annual",
) -> DriverGrid:
    """The drivers of the scenario's revenue method in catalog order, each with its history and
    its resolved value and source per forecast period in the case: the last HISTORY_YEARS actual
    years and the forecast years (`annual`), or the last QUARTER_HISTORY actual quarters and the
    forecast quarters (`quarterly`; only the drivers that can be set per quarter). Raises
    ScenarioNotFound, InvalidScenario (case), and ForecastUnavailable when the company has no
    opening balance sheet, or no quarterly history for `quarterly`."""
    scenario, _ = get_case(session, company, scenario_id, case)
    return _grid(session, scenario, case, load_history(session, company), freq)


def _grid(
    session: Session,
    scenario: Scenario,
    case: str,
    history: ForecastHistory,
    freq: Literal["annual", "quarterly"] = "annual",
) -> DriverGrid:
    """`driver_grid` on an already built history (a driver write does not change it)."""
    drivers = resolve_case(session, scenario, case, history)
    years = list(drivers.resolved.years)
    past = history_years(history)
    if freq == "annual":
        columns = [(y, "FY") for y in years]
        history_periods = [GridPeriod(y, "FY", f"FY{y % 100:02d}A") for y in past]
        actual = historical_drivers(history, drivers.settings)
        past_keys = [f"FY{y}" for y in past]
        past_values = {(code, f"FY{y}"): v for (code, y), v in actual.items()}
    else:
        quarters = history_quarters(history)
        if not quarters:
            raise ForecastUnavailable("No quarterly history")
        columns = forecast_quarters(history)
        history_periods = [
            GridPeriod(
                p.fiscal_year, p.fiscal_period, _quarter_label(p.fiscal_year, p.fiscal_period, "A")
            )
            for p in quarters
        ]
        past_keys = [p.key for p in quarters]
        past_values = historical_quarter_drivers(history, drivers.settings)
    forecast_periods = [
        GridPeriod(y, q, f"FY{y % 100:02d}E" if q == "FY" else _quarter_label(y, q, "E"))
        for y, q in columns
    ]
    own = {(r.driver_code, r.fiscal_year, r.fiscal_period): r for r in drivers.own}
    kinds = {r.driver_code: r.kind for r in drivers.own}
    modes = _year_modes(session, scenario, history)
    figures = _rollup(history, drivers, [m.fiscal_year for m in modes if m.mode == "quarterly"])
    rows = []
    for d in scenario_drivers(history, drivers.settings):
        if freq == "quarterly" and not d.quarterly:
            continue
        resolved = [drivers.resolved.get(d.code, y, q) for y, q in columns]
        mine = [own.get((d.code, y, q)) for y, q in columns]
        rows.append(
            GridRow(
                code=d.code,
                label=d.label,
                group=d.group,
                unit=d.unit,
                history=[past_values[(d.code, key)] for key in past_keys],
                values=[None if r.value is FLAT else r.value for r in resolved],
                sources=[r.source for r in resolved],
                own=[None if r is None else r.value for r in mine],
                kind=kinds.get(d.code),  # type: ignore[arg-type]  # checked by the schema
                rollup=[figures.get((d.code, y)) for y in years],
            )
        )
    warnings = list(drivers.resolved.warnings)
    method = drivers.settings.revenue_method
    if method != "growth" and any(
        r.driver_code == "revenue_growth" and r.kind == "offset" for r in drivers.own
    ):
        warnings.append(f"Offsets on revenue_growth are not used by the {method} method")
    return DriverGrid(
        scenario.id,
        case,
        past,
        years,
        rows,
        warnings,
        freq,
        history_periods,
        forecast_periods,
        modes,
    )


def _rollup(
    history: ForecastHistory, drivers: ScenarioDrivers, years: Sequence[int]
) -> dict[tuple[str, int], Decimal | None]:
    """The annual figures of the years set by quarter (`forecast/rollup.py`), from the case's
    forecast; none when it cannot run (the forecast tab says why)."""
    if not years:
        return {}
    try:
        statements = DriverModel().run(
            history, drivers.resolved, FORECAST_HORIZON, drivers.settings
        )
    except ForecastUnavailable:
        return {}
    return rollup(history, drivers.settings, statements, drivers.resolved, years)


def _quarter_label(year: int, quarter: str, suffix: str) -> str:
    return f"{quarter} FY{year % 100:02d}{suffix}"


def put_drivers(
    session: Session,
    company: Company,
    scenario_id: int,
    case: str,
    rows: Sequence[DriverRowInput],
    now: datetime,
) -> DriverGrid:
    """Each row replaces the stored rows of its driver of its frequency (annual: every year,
    stale ones included; quarterly: every quarter); its None values are not stored. A row that
    stores a value of a kind other than the driver's other-frequency rows drops those (one kind
    per driver). A year the scenario sets by quarter takes quarter values only (its annual rows stay
    stored, untouched), a year it sets annually annual values only (docs "Year modes" → Write
    rules). All rows are checked before anything is written. Returns the case's grid, the
    quarterly one when every row is quarterly. Raises ScenarioNotFound, InvalidScenario (case),
    InvalidDrivers and ForecastUnavailable (no opening, or a quarterly row with no quarterly
    history)."""
    scenario, kase = get_case(session, company, scenario_id, case)
    history = load_history(session, company)
    settings = settings_of(scenario)
    years = forecast_years(history, FORECAST_HORIZON.years)
    span = forecast_quarters(history) if any(r.freq == "quarterly" for r in rows) else []
    if any(r.freq == "quarterly" for r in rows) and not history_quarters(history):
        raise ForecastUnavailable("No quarterly history")
    allowed = {d.code: d for d in scenario_drivers(history, settings)}
    stamp = _naive_utc(now)
    seen: set[tuple[str, str]] = set()
    new: list[DriverValue] = []
    stores: dict[int, bool] = {}
    for number, row in enumerate(rows):
        _check_row(row, case, settings, allowed, years, span, seen)
        values = _row_values(kase, row, stamp)
        stores[number] = bool(values)
        new.extend(values)
    stored = repo.list_rows(session, [kase.id])
    quarterly_years = repo.quarterly_years(session, scenario.id)
    _check_modes(rows, quarterly_years, span, stored)
    for number, row in enumerate(rows):
        _drop_replaced(session, kase, row, stored, stores[number], quarterly_years)
    _replace_rows(session, scenario, kase, set(), new, stamp)
    every_quarter = bool(rows) and all(r.freq == "quarterly" for r in rows)
    return _grid(session, scenario, case, history, "quarterly" if every_quarter else "annual")


def _check_modes(
    rows: Sequence[DriverRowInput],
    quarterly_years: Collection[int],
    span: Sequence[tuple[int, str]],
    stored: Sequence[DriverValue],
) -> None:
    """The write rules of the year modes: no annual value in a year set by quarter, no quarter
    value in a year set annually, and a quarterly row gives every forecast quarter of each year
    set by quarter a value (it replaces the driver's quarters, and a quarter cannot be cleared)."""
    for row in rows:
        code = row.driver_code
        for year, value in row.values:
            if value is not None and year in quarterly_years:
                raise InvalidDrivers(f"FY{year} is set by quarter")
        for year, _, value in row.quarters:
            if value is not None and year not in quarterly_years:
                raise InvalidDrivers(f"FY{year} is set annually; switch it to by quarter first")
        if row.freq == "quarterly":
            given = {(y, q): v for y, q, v in row.quarters}
            for year, period in span:
                if year not in quarterly_years:
                    continue
                if (year, period) not in given:
                    raise InvalidDrivers(
                        f"{period} FY{year} is missing for {code} (FY{year} is set by quarter)"
                    )
                if given[(year, period)] is None:
                    raise InvalidDrivers(
                        f"{period} FY{year} cannot be cleared (FY{year} is set by quarter)"
                    )
        elif any(v is not None for _, v in row.values):
            _check_kind_change(row, quarterly_years, stored, rows)


def _check_kind_change(
    row: DriverRowInput,
    quarterly_years: Collection[int],
    stored: Sequence[DriverValue],
    rows: Sequence[DriverRowInput],
) -> None:
    """An annual row of another kind than the driver's stored quarters drops them; in a year set
    by quarter that needs the new quarters in the same PUT."""
    code = row.driver_code
    if any(r.driver_code == code and r.freq == "quarterly" for r in rows):
        return
    for r in stored:
        if (
            r.driver_code == code
            and r.fiscal_period != "FY"
            and r.fiscal_year in quarterly_years
            and r.kind != row.kind
        ):
            raise InvalidDrivers(
                f"{code} is stored per quarter in FY{r.fiscal_year} (set by quarter): "
                "send its quarters with the new kind"
            )


def _row_values(kase: ScenarioCase, row: DriverRowInput, stamp: datetime) -> list[DriverValue]:
    """The rows a PUT row stores: its non-null values."""
    cells = [(y, "FY", v) for y, v in row.values] + [(y, q, v) for y, q, v in row.quarters]
    return [
        DriverValue(
            case_id=kase.id,
            driver_code=row.driver_code,
            fiscal_year=year,
            fiscal_period=period,
            kind=row.kind,
            value=value,
            source="manual",
            created_at=stamp,
            updated_at=stamp,
        )
        for year, period, value in cells
        if value is not None
    ]


def _drop_replaced(
    session: Session,
    kase: ScenarioCase,
    row: DriverRowInput,
    stored: Sequence[DriverValue],
    stores_values: bool,
    quarterly_years: Collection[int],
) -> None:
    """Deletes what `row` replaces: its driver's rows of its frequency, and, when it stores a
    value of another kind than the other frequency's rows, those too. The annual rows of a year
    set by quarter stay."""
    same = ("FY",) if row.freq == "annual" else QUARTERS
    other = QUARTERS if row.freq == "annual" else ("FY",)
    other_kinds = {
        r.kind for r in stored if r.driver_code == row.driver_code and r.fiscal_period in other
    }
    clash = stores_values and bool(other_kinds - {row.kind})
    # a change of kind starts the driver over: no annual row of a year set by quarter stays
    keep = () if clash else quarterly_years
    repo.delete_rows(session, kase.id, [row.driver_code], None if clash else same, keep)


def _replace_rows(
    session: Session,
    scenario: Scenario,
    kase: ScenarioCase,
    codes: set[str],
    rows: list[DriverValue],
    stamp: datetime,
) -> None:
    """Deletes every stored row of `codes` in the case and adds `rows`; one transaction."""
    repo.delete_rows(session, kase.id, codes)
    repo.add_rows(session, rows)
    kase.updated_at = scenario.updated_at = stamp
    session.commit()


def export_drivers(
    session: Session, company: Company, scenario_id: int, case: str, fmt: Literal["csv", "xlsx"]
) -> tuple[bytes, str]:
    """The case's driver file (years, then the quarters the forecast runs quarter by quarter) and
    its name `<TICKER>-<scenario name>-<Case>-drivers.<fmt>`. Raises ScenarioNotFound,
    InvalidScenario (case), and ForecastUnavailable when the company has no opening balance
    sheet."""
    scenario, _ = get_case(session, company, scenario_id, case)
    history = load_history(session, company)
    grid = _grid(session, scenario, case, history)
    quarterly = (
        _grid(session, scenario, case, history, "quarterly") if history_quarters(history) else None
    )
    content = export_csv(grid, quarterly) if fmt == "csv" else export_xlsx(grid, quarterly)
    return content, f"{company.ticker}-{scenario.name}-{case.capitalize()}-drivers.{fmt}"


def import_drivers(
    session: Session,
    company: Company,
    scenario_id: int,
    case: str,
    content: bytes,
    filename: str,
    dry_run: bool,
    now: datetime,
) -> DriverImportResult:
    """The changes a driver file makes to the case's own rows (`forecast/driver_io.py::
    plan_import`); unless `dry_run`, writes them in one transaction and returns the new grid.
    Raises ScenarioNotFound, InvalidScenario (case), InvalidDriverFile and ForecastUnavailable
    (no opening)."""
    scenario, kase = get_case(session, company, scenario_id, case)
    history = load_history(session, company)
    settings = settings_of(scenario)
    years = forecast_years(history, FORECAST_HORIZON.years)
    catalog = scenario_drivers(history, settings)
    span = forecast_quarters(history) if history_quarters(history) else []
    quarterly = set(built_from_quarters(session, scenario, history))
    try:
        plan = parse_driver_file(content, filename, catalog, years, case == "base", span, quarterly)
    except DriverFileError as error:
        raise InvalidDriverFile(error.issues) from error
    own = repo.list_rows(session, [kase.id])
    result = plan_import(plan, [_driver_row(r) for r in own], quarterly)
    if dry_run:
        return DriverImportResult(result.changes, None)
    if result.rows:
        stamp = _naive_utc(now)
        new = [
            DriverValue(
                case_id=kase.id,
                driver_code=r.code,
                fiscal_year=r.fiscal_year,
                fiscal_period=r.fiscal_period,
                kind=r.kind,
                value=r.value,
                source="manual",
                created_at=stamp,
                updated_at=stamp,
            )
            for rows in result.rows.values()
            for r in rows
        ]
        _replace_rows(session, scenario, kase, set(result.rows), new, stamp)
    return DriverImportResult(result.changes, _grid(session, scenario, case, history))


def _check_row(
    row: DriverRowInput,
    case: str,
    settings: ScenarioSettings,
    allowed: dict[str, DriverDef],
    years: list[int],
    span: Sequence[tuple[int, str]],
    seen: set[tuple[str, str]],
) -> None:
    """Checks one PUT row; `seen` holds the (driver, frequency) pairs of the rows before it."""
    code = row.driver_code
    try:
        driver_def(code)
    except UnknownDriver as error:
        raise InvalidDrivers(str(error)) from error
    if code not in allowed:
        raise InvalidDrivers(f"{code} is not a driver of the {settings.revenue_method} method")
    if (code, row.freq) in seen:
        raise InvalidDrivers(f"{code} is given twice")
    seen.add((code, row.freq))
    if row.kind not in ("value", "offset"):
        raise InvalidDrivers("kind must be value or offset")
    if row.kind == "offset" and case == "base":
        raise InvalidDrivers("Base cannot hold offsets")
    if row.freq == "annual":
        _check_years(row, years)
    elif row.freq == "quarterly":
        _check_quarters(row, allowed[code], span)
    else:
        raise InvalidDrivers("freq must be annual or quarterly")


def _check_years(row: DriverRowInput, years: list[int]) -> None:
    if row.quarters:
        raise InvalidDrivers(f"{row.driver_code}: a quarter value in an annual row")
    given: set[int] = set()
    for year, value in row.values:
        if year not in years:
            raise InvalidDrivers(f"FY{year} is not a forecast year (FY{years[0]}-FY{years[-1]})")
        if year in given:
            raise InvalidDrivers(f"FY{year} is given twice for {row.driver_code}")
        given.add(year)
        _check_value(row, value)


def _check_quarters(
    row: DriverRowInput, driver: DriverDef, span: Sequence[tuple[int, str]]
) -> None:
    code = row.driver_code
    if row.values:
        raise InvalidDrivers(f"{code}: an FY value in a quarterly row")
    if not driver.quarterly:
        raise InvalidDrivers(f"{code} cannot be set per quarter")
    given: set[tuple[int, str]] = set()
    for year, period, value in row.quarters:
        if (year, period) not in span:
            raise InvalidDrivers(f"{period} FY{year} is not a forecast quarter")
        if (year, period) in given:
            raise InvalidDrivers(f"{period} FY{year} is given twice for {code}")
        given.add((year, period))
        _check_value(row, value)


def _check_value(row: DriverRowInput, value: Decimal | None) -> None:
    if value is not None:
        message = check_bounds(row.driver_code, row.kind, value)  # type: ignore[arg-type]  # checked
        if message is not None:
            raise InvalidDrivers(message)


def _driver_row(row: DriverValue) -> DriverRow:
    return DriverRow(
        row.driver_code,
        row.fiscal_year,
        row.kind,  # type: ignore[arg-type]
        row.value,
        row.fiscal_period,
    )
