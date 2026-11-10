"""Stored snapshots and backtest runs. Add, list and load only: nothing here updates a snapshot,
and only the company's cascade deletes one (docs/erd/accountability.md "Snapshots")."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, insert, or_, select
from sqlalchemy.orm import Session

from bedrock.backtest.snapshot import ValueRow
from bedrock.models.forecast_run import ForecastRun, ForecastSnapshot, ForecastValue, ValuationRun
from bedrock.repositories.numeric import plain


@dataclass(frozen=True)
class StoredRun:
    """A run to store with its value rows and (a snapshot's) valuations."""

    run: ForecastRun
    rows: list[ValueRow]
    valuations: list[ValuationRun] = field(default_factory=list)


def add_snapshot(
    session: Session, snapshot: ForecastSnapshot, runs: Sequence[StoredRun]
) -> ForecastSnapshot:
    """Adds the snapshot and its runs. Flushes (no commit)."""
    session.add(snapshot)
    session.flush()
    for stored in runs:
        stored.run.snapshot_id = snapshot.id
    _add_runs(session, runs)
    return snapshot


def list_snapshots(session: Session, company_id: int) -> list[ForecastSnapshot]:
    """The company's snapshots, newest first."""
    stmt = (
        select(ForecastSnapshot)
        .where(ForecastSnapshot.company_id == company_id)
        .order_by(ForecastSnapshot.created_at.desc(), ForecastSnapshot.id.desc())
    )
    return list(session.execute(stmt).scalars())


def get_snapshot(session: Session, company_id: int, snapshot_id: int) -> ForecastSnapshot | None:
    """The snapshot, if it is this company's."""
    stmt = select(ForecastSnapshot).where(
        ForecastSnapshot.id == snapshot_id, ForecastSnapshot.company_id == company_id
    )
    return session.execute(stmt).scalar_one_or_none()


def runs_of(session: Session, snapshot_ids: Sequence[int]) -> list[ForecastRun]:
    """The runs of these snapshots."""
    stmt = select(ForecastRun).where(ForecastRun.snapshot_id.in_(snapshot_ids))
    return list(session.execute(stmt).scalars())


def values_of(
    session: Session, run_ids: Sequence[int], codes: Sequence[str] | None = None
) -> dict[int, list[ValueRow]]:
    """Every run's rows by run id (a run with none has an empty list), in key order. `codes` limits
    the line rows; driver rows are always returned."""
    table = ForecastValue.__table__
    stmt = select(table).where(table.c.forecast_run_id.in_(run_ids))
    if codes is not None:
        stmt = stmt.where(or_(table.c.kind == "driver", table.c.code.in_(codes)))
    stmt = stmt.order_by(
        table.c.forecast_run_id,
        table.c.kind,
        table.c.code,
        table.c.fiscal_year,
        table.c.fiscal_period,
    )
    rows: dict[int, list[ValueRow]] = {run_id: [] for run_id in run_ids}
    for row in session.execute(stmt).mappings():
        rows[row["forecast_run_id"]].append(
            ValueRow(
                row["kind"],
                row["code"],
                row["fiscal_year"],
                row["fiscal_period"],
                row["horizon"],
                plain(row["point"]),
                _plain(row["p05"]),
                _plain(row["p25"]),
                _plain(row["p50"]),
                _plain(row["p75"]),
                _plain(row["p95"]),
                row["source"],
            )
        )
    return rows


def valuations_of(session: Session, run_ids: Sequence[int]) -> dict[int, list[ValuationRun]]:
    """Every run's valuations by run id (a run with none has an empty list), in stored order."""
    stmt = (
        select(ValuationRun)
        .where(ValuationRun.forecast_run_id.in_(run_ids))
        .order_by(ValuationRun.id)
    )
    found: dict[int, list[ValuationRun]] = {run_id: [] for run_id in run_ids}
    for valuation in session.execute(stmt).scalars():
        found[valuation.forecast_run_id].append(valuation)
    return found


def replace_backtest(session: Session, company_id: int, runs: Sequence[StoredRun]) -> None:
    """Deletes the company's backtest runs (their rows go by cascade) and adds these. Flushes (no
    commit). Snapshot runs are untouched."""
    session.execute(
        delete(ForecastRun).where(
            ForecastRun.company_id == company_id, ForecastRun.kind == "backtest"
        )
    )
    _add_runs(session, runs)


def backtest_runs(session: Session, company_id: int) -> list[ForecastRun]:
    """The company's backtest runs, oldest origin first."""
    stmt = (
        select(ForecastRun)
        .where(ForecastRun.company_id == company_id, ForecastRun.kind == "backtest")
        .order_by(ForecastRun.as_of_date, ForecastRun.id)
    )
    return list(session.execute(stmt).scalars())


def _add_runs(session: Session, runs: Sequence[StoredRun]) -> None:
    session.add_all(stored.run for stored in runs)
    session.flush()
    payload = [
        {"forecast_run_id": stored.run.id, **vars(row)} for stored in runs for row in stored.rows
    ]
    if payload:
        # Through the connection, one executemany: the ORM bulk path splits on NULLs (G42).
        session.connection().execute(insert(ForecastValue), payload)
    for stored in runs:
        for valuation in stored.valuations:
            valuation.forecast_run_id = stored.run.id
        session.add_all(stored.valuations)
    session.flush()


def _plain(value: Decimal | None) -> Decimal | None:
    return None if value is None else plain(value)
