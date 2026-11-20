"""Point-in-time backtests, stored and scored against the latest actuals (FR-ACC-02, -03;
docs/erd/accountability.md "Backtest"). A run is what the user asks for, about 15 seconds."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from bedrock.backtest.pit import origins, run_method
from bedrock.backtest.scoring import Scored, summarize
from bedrock.core.clock import naive_utc
from bedrock.forecast.engine_defaults import ENGINE_CODES
from bedrock.models.company import Company
from bedrock.models.forecast_run import ForecastRun
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import runs as repo
from bedrock.repositories.runs import StoredRun
from bedrock.services.engines import memo_fit
from bedrock.services.errors import InvalidBacktest
from bedrock.services.run_scores import ScoreRow, labelled, load_actuals, score
from bedrock.services.scenarios import load_history

__all__ = ["BacktestView", "backtest_view", "run_backtest"]


@dataclass(frozen=True)
class MethodOutcome:
    method: str
    error: str | None


@dataclass(frozen=True)
class OriginView:
    as_of_date: date
    runs: list[MethodOutcome]  # in ENGINE_CODES order


@dataclass(frozen=True)
class BacktestView:
    ran_at: datetime | None  # None before the first run
    stale: bool  # a newer 10-K exists than the run's origins imply
    origins: list[OriginView]  # oldest first
    summary: list[ScoreRow]


def run_backtest(session: Session, company: Company, now: datetime) -> BacktestView:
    """Runs every method from each origin and replaces the company's stored backtest. Raises
    InvalidBacktest when there is no 10-K to start from."""
    dates = origins(facts_repo.annual_filing_dates(session, company.id))
    if not dates:
        raise InvalidBacktest("No 10-K filings to back-test")
    stamp = naive_utc(now)
    # All reads and fits first, with no write lock held.
    runs: list[StoredRun] = []
    for origin in dates:
        history = load_history(session, company, as_of=origin)
        for method in ENGINE_CODES:
            result = run_method(history, method, memo_fit)
            runs.append(
                StoredRun(
                    ForecastRun(
                        company_id=company.id,
                        kind="backtest",
                        method=method,
                        as_of_date=origin,
                        created_at=stamp,
                        engines_json=result.meta,
                        error=result.error,
                    ),
                    result.rows,
                )
            )
    repo.replace_backtest(session, company.id, runs)
    session.commit()
    return backtest_view(session, company)


def backtest_view(session: Session, company: Company) -> BacktestView:
    """The stored backtest scored against the latest actuals: errors by metric, engine and horizon
    over every origin. Empty before the first run."""
    runs = repo.backtest_runs(session, company.id)
    if not runs:
        return BacktestView(None, False, [], [])
    actuals = load_actuals(session, company)
    values = repo.values_of(session, [r.id for r in runs])
    scored: dict[str, list[Scored]] = {}
    for run in runs:
        scored.setdefault(run.method or "", []).extend(score(run, values[run.id], actuals))
    summary = [row for method in ENGINE_CODES for row in summarize(method, scored.get(method, []))]
    return BacktestView(
        ran_at=max(r.created_at for r in runs),
        stale=_stale(session, company, runs),
        origins=_origins(runs),
        summary=labelled(summary, actuals.history),
    )


def _stale(session: Session, company: Company, runs: Sequence[ForecastRun]) -> bool:
    now = origins(facts_repo.annual_filing_dates(session, company.id))
    return bool(now) and now[-1] > max(r.as_of_date for r in runs)


def _origins(runs: Sequence[ForecastRun]) -> list[OriginView]:
    by_date: dict[date, list[ForecastRun]] = {}
    for run in runs:
        by_date.setdefault(run.as_of_date, []).append(run)
    return [
        OriginView(
            as_of_date=day,
            runs=[
                MethodOutcome(r.method or "", r.error)
                for r in sorted(by_date[day], key=lambda r: ENGINE_CODES.index(r.method))
            ],
        )
        for day in sorted(by_date)
    ]
