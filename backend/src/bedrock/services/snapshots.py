"""Frozen scenarios and their scores against the latest actuals (FR-ACC-01, -02;
docs/erd/accountability.md "Snapshots", "Scoring", "API")."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.backtest.scoring import (
    CASES,
    SCORED_CODES,
    Scored,
    in_todays_shares,
    line_ranges,
    summarize,
)
from bedrock.backtest.snapshot import RowKind, ValueRow, read_meta, run_meta, value_rows
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.models.company import Company
from bedrock.models.forecast_run import ForecastRun, ForecastSnapshot, ValuationRun
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import runs as repo
from bedrock.repositories.numeric import plain
from bedrock.repositories.runs import StoredRun
from bedrock.schemas.valuation import ValuationResultOut
from bedrock.services.errors import InvalidSnapshot, SnapshotNotFound
from bedrock.services.forecasts import CaseRun, run_case
from bedrock.services.run_scores import (
    Actuals,
    ScoreRow,
    actuals_from,
    describe,
    labelled,
    load_actuals,
    score,
)
from bedrock.services.scenarios import get_scenario, load_history, naive_utc, settings_of
from bedrock.services.valuation import CaseValuation, case_valuation
from bedrock.statements.splits import split_factor
from bedrock.valuation.inputs import format_input

__all__ = [
    "SnapshotDetail",
    "SnapshotList",
    "SnapshotView",
    "create_snapshot",
    "detail",
    "list_view",
]

NOTE_LIMIT = 500


@dataclass(frozen=True)
class SnapshotView:
    id: int
    scenario_id: int | None
    scenario_name: str
    note: str | None
    created_at: datetime
    data_as_of: date | None
    failed_cases: list[str]
    scored_periods: int  # Base's FY revenue rows with an actual
    revenue_mape: Decimal | None  # over them
    # M7d S4: the company's classification mode when the snapshot was taken; None before 0022
    classification_mode: str | None


@dataclass(frozen=True)
class SnapshotList:
    snapshots: list[SnapshotView]  # newest first
    summary: list[ScoreRow]


@dataclass(frozen=True)
class SnapshotCell:
    fiscal_year: int
    fiscal_period: str
    label: str
    horizon: int
    forecast: Decimal  # in today's shares
    actual: Decimal | None
    pct_error: Decimal | None
    in_range: bool | None
    source: str | None
    p05: Decimal | None
    p95: Decimal | None


@dataclass(frozen=True)
class SnapshotSeries:
    code: str
    label: str
    unit: str
    cells: list[SnapshotCell]


@dataclass(frozen=True)
class SnapshotValuation:
    key: str
    label: str
    value_per_share: Decimal | None
    equity_value: Decimal | None
    enterprise_value: Decimal | None
    upside: Decimal | None
    error: str | None


@dataclass(frozen=True)
class SnapshotCase:
    case: str
    error: str | None
    warnings: list[str]
    lines: list[SnapshotSeries]
    drivers: list[SnapshotSeries]
    valuation: list[SnapshotValuation]


@dataclass(frozen=True)
class SnapshotDetail:
    id: int
    scenario_id: int | None
    scenario_name: str
    note: str | None
    created_at: datetime
    data_as_of: date | None
    failed_cases: list[str]
    scored_periods: int
    revenue_mape: Decimal | None
    classification_mode: str | None
    cases: list[SnapshotCase]


def create_snapshot(
    session: Session, company: Company, scenario_id: int, note: str | None, now: datetime
) -> SnapshotView:
    """Freezes the scenario's three cases and their valuations. A case that cannot run is stored
    with its error. Raises ScenarioNotFound, InvalidSnapshot, and ForecastUnavailable when no case
    can run (nothing is written)."""
    cleaned = _clean_note(note)
    scenario = get_scenario(session, company, scenario_id)
    # All reads first, with no write lock held.
    history = load_history(session, company)
    data_as_of = facts_repo.latest_filing_date(session, company.id)
    settings = settings_of(scenario)
    stamp = naive_utc(now)
    runs: list[StoredRun] = []
    last_error: ForecastUnavailable | None = None
    for case in CASES:
        try:
            run = run_case(session, scenario, case, history)
            valuation = case_valuation(session, company, scenario.id, case)
        except ForecastUnavailable as unavailable:
            last_error = unavailable
            runs.append(
                StoredRun(
                    ForecastRun(
                        company_id=company.id,
                        kind="snapshot",
                        case=case,
                        as_of_date=stamp.date(),
                        created_at=stamp,
                        engines_json=run_meta(settings, {}, ()),
                        error=unavailable.detail,
                    ),
                    [],
                )
            )
            continue
        runs.append(_stored_case(company, case, stamp, run, valuation))
    if last_error is not None and all(r.run.error is not None for r in runs):
        raise last_error
    snapshot = repo.add_snapshot(
        session,
        ForecastSnapshot(
            company_id=company.id,
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            note=cleaned,
            data_as_of=data_as_of,
            created_at=stamp,
            classification_mode=company.classification_mode,
        ),
        runs,
    )
    session.commit()
    views, _ = _views(session, [snapshot], actuals_from(session, company, history))
    return views[0]


def list_view(session: Session, company: Company) -> SnapshotList:
    """Every snapshot, newest first, and the errors by metric, case and horizon over all of them.
    Only the comparison lines and the drivers are loaded."""
    snapshots = repo.list_snapshots(session, company.id)
    if not snapshots:
        return SnapshotList([], [])
    actuals = load_actuals(session, company)
    views, scored = _views(session, snapshots, actuals)
    summary = [row for case in CASES for row in summarize(case, scored.get(case, []))]
    return SnapshotList(views, labelled(summary, actuals.history))


def detail(session: Session, company: Company, snapshot_id: int) -> SnapshotDetail:
    """The snapshot's three cases, every stored line and driver against the latest actuals. Raises
    SnapshotNotFound."""
    snapshot = repo.get_snapshot(session, company.id, snapshot_id)
    if snapshot is None:
        raise SnapshotNotFound(str(snapshot_id))
    actuals = load_actuals(session, company)
    runs = _in_case_order(repo.runs_of(session, [snapshot.id]))
    run_ids = [r.id for r in runs]
    values = repo.values_of(session, run_ids)
    valuations = repo.valuations_of(session, run_ids)
    ranges = _ranges(runs, values)
    scored = {r.id: score(r, values[r.id], actuals, ranges) for r in runs}
    view = _view(snapshot, runs, scored)
    return SnapshotDetail(
        **vars(view),
        cases=[_case(r, values[r.id], scored[r.id], valuations[r.id], actuals) for r in runs],
    )


def _clean_note(note: str | None) -> str | None:
    cleaned = (note or "").strip()
    if len(cleaned) > NOTE_LIMIT:
        raise InvalidSnapshot(f"A note is at most {NOTE_LIMIT} characters")
    return cleaned or None


def _stored_case(
    company: Company, case: str, stamp: datetime, run: CaseRun, valuation: CaseValuation
) -> StoredRun:
    engines = run.drivers.engines.rows
    inputs_json = json.dumps(
        {
            "market": asdict(valuation.market),
            "inputs": {
                r.code: None if r.value is None else format_input(r.value)
                for r in valuation.inputs.rows
            },
        },
        default=str,
        sort_keys=True,
    )
    return StoredRun(
        ForecastRun(
            company_id=company.id,
            kind="snapshot",
            case=case,
            as_of_date=stamp.date(),
            created_at=stamp,
            engines_json=run_meta(run.drivers.settings, engines, run.warnings),
        ),
        value_rows(run.statements, run.drivers.resolved, engines),
        [
            ValuationRun(
                method_code=result.key,
                label=result.label,
                inputs_json=inputs_json,
                value_per_share=result.value_per_share,
                equity_value=result.equity_value,
                enterprise_value=result.enterprise_value,
                upside=result.upside,
                details_json=ValuationResultOut.from_result(
                    result, valuation.caveats.get(result.key)
                ).model_dump_json(),
                error=result.error,
            )
            for result in valuation.results
        ],
    )


def _in_case_order(runs: Sequence[ForecastRun]) -> list[ForecastRun]:
    return sorted(runs, key=lambda r: CASES.index(r.case or ""))


def _ranges(
    runs: Sequence[ForecastRun], values: Mapping[int, Sequence[ValueRow]]
) -> dict[tuple[str, int, str], tuple[Decimal, Decimal]]:
    """The Bull–Bear envelope; a case that could not run leaves no range."""
    return line_ranges({r.case or "": values[r.id] for r in runs if r.error is None})


def _views(
    session: Session, snapshots: Sequence[ForecastSnapshot], actuals: Actuals
) -> tuple[list[SnapshotView], dict[str, list[Scored]]]:
    """Each snapshot's view, and every scored row by case."""
    runs = repo.runs_of(session, [s.id for s in snapshots])
    values = repo.values_of(session, [r.id for r in runs], SCORED_CODES)
    by_snapshot: dict[int, list[ForecastRun]] = {s.id: [] for s in snapshots}
    for run in runs:
        assert run.snapshot_id is not None
        by_snapshot[run.snapshot_id].append(run)
    views = []
    by_case: dict[str, list[Scored]] = {}
    for snapshot in snapshots:
        own = _in_case_order(by_snapshot[snapshot.id])
        ranges = _ranges(own, values)
        scored = {r.id: score(r, values[r.id], actuals, ranges) for r in own}
        views.append(_view(snapshot, own, scored))
        for run in own:
            by_case.setdefault(run.case or "", []).extend(scored[run.id])
    return views, by_case


def _view(
    snapshot: ForecastSnapshot, runs: Sequence[ForecastRun], scored: Mapping[int, Sequence[Scored]]
) -> SnapshotView:
    base = next((scored[r.id] for r in runs if r.case == "base"), [])
    revenue = [
        s for s in base if s.kind == "line" and s.code == "revenue" and s.fiscal_period == "FY"
    ]
    errors = [abs(s.pct_error) for s in revenue if s.pct_error is not None]
    return SnapshotView(
        id=snapshot.id,
        scenario_id=snapshot.scenario_id,
        scenario_name=snapshot.scenario_name,
        note=snapshot.note,
        created_at=snapshot.created_at,
        data_as_of=snapshot.data_as_of,
        failed_cases=[r.case or "" for r in runs if r.error is not None],
        scored_periods=len(revenue),
        revenue_mape=sum(errors, Decimal(0)) / len(errors) if errors else None,
        classification_mode=snapshot.classification_mode,
    )


def _case(
    run: ForecastRun,
    rows: Sequence[ValueRow],
    scored: Sequence[Scored],
    valuations: Sequence[ValuationRun],
    actuals: Actuals,
) -> SnapshotCase:
    results = {(s.kind, s.code, s.fiscal_year, s.fiscal_period): s for s in scored}
    factor = split_factor(run.created_at.date(), actuals.actions)
    return SnapshotCase(
        case=run.case or "",
        error=run.error,
        warnings=read_meta(run.engines_json).warnings,
        lines=_series("line", rows, results, factor, actuals),
        drivers=_series("driver", rows, results, factor, actuals),
        valuation=[_valuation(v) for v in valuations],
    )


def _series(
    kind: RowKind,
    rows: Sequence[ValueRow],
    results: Mapping[tuple[RowKind, str, int, str], Scored],
    factor: Decimal,
    actuals: Actuals,
) -> list[SnapshotSeries]:
    """One entry per code of `kind`, its cells years first and then quarters."""
    by_code: dict[str, list[ValueRow]] = {}
    for row in rows:
        if row.kind == kind:
            by_code.setdefault(row.code, []).append(row)
    series = []
    for code, own in by_code.items():
        label, unit = describe(kind, code, actuals.history)
        ordered = sorted(
            own, key=lambda r: (r.fiscal_period != "FY", r.fiscal_year, r.fiscal_period)
        )
        series.append(
            SnapshotSeries(
                code, label, unit, [_cell(r, results.get(_key(r)), unit, factor) for r in ordered]
            )
        )
    return series


def _key(row: ValueRow) -> tuple[RowKind, str, int, str]:
    return (row.kind, row.code, row.fiscal_year, row.fiscal_period)


def _cell(row: ValueRow, scored: Scored | None, unit: str, factor: Decimal) -> SnapshotCell:
    def today(value: Decimal | None) -> Decimal | None:
        return None if value is None else in_todays_shares(value, unit, factor)

    return SnapshotCell(
        fiscal_year=row.fiscal_year,
        fiscal_period=row.fiscal_period,
        label=_period_label(row.fiscal_year, row.fiscal_period),
        horizon=row.horizon,
        forecast=in_todays_shares(row.point, unit, factor),
        actual=None if scored is None else scored.actual,
        pct_error=None if scored is None else scored.pct_error,
        in_range=None if scored is None else scored.in_range,
        source=row.source,
        p05=today(row.p05),
        p95=today(row.p95),
    )


def _period_label(fiscal_year: int, fiscal_period: str) -> str:
    year = f"FY{fiscal_year % 100:02d}"
    return year if fiscal_period == "FY" else f"{fiscal_period} {year}"


def _valuation(stored: ValuationRun) -> SnapshotValuation:
    return SnapshotValuation(
        key=stored.method_code,
        label=stored.label,
        value_per_share=_plain(stored.value_per_share),
        equity_value=_plain(stored.equity_value),
        enterprise_value=_plain(stored.enterprise_value),
        upside=_plain(stored.upside),
        error=stored.error,
    )


def _plain(value: Decimal | None) -> Decimal | None:
    return None if value is None else plain(value)
