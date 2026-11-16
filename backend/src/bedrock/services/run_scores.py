"""Scoring stored runs against the latest actuals, shared by snapshots and backtests
(FR-ACC-02; docs/erd/accountability.md "Scoring"). Scores are computed on read."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache

from sqlalchemy.orm import Session

from bedrock.backtest.scoring import (
    Freq,
    Scored,
    SummaryRow,
    driver_actuals,
    line_actuals,
    score_run,
    units_of,
)
from bedrock.backtest.snapshot import RowKind, ValueRow, read_meta
from bedrock.forecast.drivers import driver_def, segment_id
from bedrock.forecast.history import ForecastHistory, ScenarioSettings
from bedrock.models.company import Company
from bedrock.models.corporate_action import CorporateAction
from bedrock.models.forecast_run import ForecastRun
from bedrock.repositories import corporate_actions as actions_repo
from bedrock.services.scenarios import load_history
from bedrock.services.statements import canonical_items

LineKey = tuple[str, int, str]


@dataclass(frozen=True)
class ScoreRow:
    """A `SummaryRow` with the label and unit of its line or driver."""

    kind: RowKind
    code: str
    label: str
    unit: str
    method: str
    freq: Freq
    horizon: int
    n: int
    mape: Decimal | None
    bias: Decimal | None
    hit_rate: Decimal | None
    n_range: int


@dataclass
class Actuals:
    """The latest history and splits, loaded once for a whole read."""

    history: ForecastHistory
    actions: list[CorporateAction]
    lines: Mapping[LineKey, Decimal]
    _drivers: dict[tuple[ScenarioSettings, tuple[int, ...]], dict[tuple[str, int], Decimal]] = (
        field(default_factory=dict)
    )
    _units: dict[ScenarioSettings, dict[str, str]] = field(default_factory=dict)

    def drivers(
        self, settings: ScenarioSettings, years: tuple[int, ...]
    ) -> dict[tuple[str, int], Decimal]:
        key = (settings, years)
        if key not in self._drivers:
            self._drivers[key] = driver_actuals(self.history, settings, years)
        return self._drivers[key]

    def units(self, settings: ScenarioSettings) -> dict[str, str]:
        if settings not in self._units:
            self._units[settings] = units_of(self.history, settings)
        return self._units[settings]


def load_actuals(session: Session, company: Company) -> Actuals:
    return actuals_from(session, company, load_history(session, company))


def actuals_from(session: Session, company: Company, history: ForecastHistory) -> Actuals:
    """The `Actuals` of an already loaded latest history."""
    return Actuals(history, actions_repo.list_for(session, company.id), line_actuals(history))


def score(
    run: ForecastRun,
    rows: Sequence[ValueRow],
    actuals: Actuals,
    ranges: Mapping[LineKey, tuple[Decimal, Decimal]] | None = None,
) -> list[Scored]:
    """The run's rows that have an actual. The split basis is the date the run was **made**, not
    its origin: a backtest's history is in the shares of the day it ran (a later split is not cut
    from it), so its origin would restate it twice."""
    settings = read_meta(run.engines_json).settings
    years = tuple(sorted({r.fiscal_year for r in rows if r.kind == "driver"}))
    return score_run(
        rows,
        actuals.lines,
        actuals.drivers(settings, years),
        actuals.units(settings),
        run.created_at.date(),
        actuals.actions,
        ranges,
        run.case,
    )


def describe(kind: RowKind, code: str, history: ForecastHistory) -> tuple[str, str]:
    """(label, unit) of a stored line or driver. A segment driver takes the series' name while the
    series exists, and the catalog's template label after it is deleted."""
    if kind == "line":
        return _line_items()[code]
    series = segment_id(code)
    name = next((s.name for s in history.segment_series if s.id == series), None)
    definition = driver_def(code, name)
    return definition.label, definition.unit


def labelled(rows: Sequence[SummaryRow], history: ForecastHistory) -> list[ScoreRow]:
    """`rows` with their labels and units."""
    described = []
    for row in rows:
        label, unit = describe(row.kind, row.code, history)
        described.append(
            ScoreRow(
                row.kind,
                row.code,
                label,
                unit,
                row.method,
                row.freq,
                row.horizon,
                row.n,
                row.mape,
                row.bias,
                row.hit_rate,
                row.n_range,
            )
        )
    return described


@cache
def _line_items() -> dict[str, tuple[str, str]]:
    return {item.code: (item.label, item.unit) for item in canonical_items()}
