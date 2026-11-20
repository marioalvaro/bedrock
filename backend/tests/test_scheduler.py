"""The scheduled refresh (docs/erd/data.md "Scheduled refresh"): when it runs, and what a run
does. The asyncio loop that sleeps between runs is a thin shell around these two."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from bedrock.core import scheduler
from bedrock.core.scheduler import (
    ScheduledRun,
    acquire_scheduler_lock,
    next_run,
    read_last_run,
    refresh_loop,
    run_scheduled_refresh,
    startup_due,
    write_last_run,
)
from bedrock.ingest.parse import parse_recent_filings
from bedrock.ingest.protocol import SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.consensus_estimate import ConsensusEstimate
from bedrock.models.filing import Filing
from bedrock.models.guidance import Guidance
from bedrock.models.pending_filing import PendingFiling
from bedrock.models.raw_fact import RawFact
from bedrock.repositories import macro

from .fakes import FIXTURES, FakeConsensus, FakeEdgar, FakeMarket, FakePrices, FakeSubmissions
from .seed import follow

NY = ZoneInfo("America/New_York")


def ny(*args: int) -> datetime:
    return datetime(*args, tzinfo=NY)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (ny(2026, 11, 9, 8, 0), ny(2026, 11, 9, 9, 30)),  # Monday before the open
        (ny(2026, 11, 9, 9, 30), ny(2026, 11, 9, 10, 30)),  # strictly after now
        (ny(2026, 11, 9, 10, 45), ny(2026, 11, 9, 11, 30)),  # hourly in the session
        (ny(2026, 11, 9, 15, 30), ny(2026, 11, 9, 16, 15)),  # then the close
        (ny(2026, 11, 9, 16, 15), ny(2026, 11, 10, 9, 30)),  # then the next morning
        (ny(2026, 11, 13, 17, 0), ny(2026, 11, 16, 9, 30)),  # Friday evening → Monday
        (ny(2026, 11, 14, 12, 0), ny(2026, 11, 16, 9, 30)),  # Saturday
    ],
)
def test_runs_hourly_in_us_market_hours_and_once_after_the_close(
    now: datetime, expected: datetime
) -> None:
    assert next_run(now) == expected


def test_next_run_accepts_any_time_zone() -> None:
    # 13:00 UTC on 9 November is 08:00 in New York (EST).
    assert next_run(datetime(2026, 11, 9, 13, 0, tzinfo=UTC)) == ny(2026, 11, 9, 9, 30)


def test_a_run_refreshes_every_company_s_prices_and_the_market_once_a_day(
    app: FastAPI, db_session: Session
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    market = FakeMarket()
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), market=market)
    now = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)

    first = run_scheduled_refresh(app.state.session_factory, sources, now)
    second = run_scheduled_refresh(app.state.session_factory, sources, now.replace(hour=15))

    assert first.new_prices["AAPL"] > 0 and first.market_refreshed
    assert not second.market_refreshed
    assert market.calls == ["risk_free", "erp", "index"]
    db_session.expire_all()
    assert macro.latest(db_session, "^TNX") is not None


def _stored_consensus(session: Session) -> int:
    session.expire_all()
    return int(session.execute(select(func.count()).select_from(ConsensusEstimate)).scalar_one())


def test_a_run_refreshes_the_analyst_consensus_once_a_day_with_the_market(
    seed_db: Any, app: FastAPI, db_session: Session
) -> None:
    seed_db("AAPL")  # with its filings: the estimates are placed on the reported revenue
    consensus = FakeConsensus()
    sources = Sources(
        edgar=FakeEdgar(), prices=FakePrices(), market=FakeMarket(), consensus=consensus
    )
    now = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)

    run_scheduled_refresh(app.state.session_factory, sources, now)
    run_scheduled_refresh(app.state.session_factory, sources, now.replace(hour=15))

    assert consensus.calls == ["AAPL"]  # the second run is within the day
    assert _stored_consensus(db_session) == 8  # 0q, +1q, 0y, +1y × revenue, EPS
    logged = select(func.count()).select_from(Guidance).where(Guidance.source == "consensus")
    # each placed estimate, plus FY26 Q1..Q3 EPS backfilled from the earnings history
    assert db_session.execute(logged).scalar_one() == 11


def test_a_failing_consensus_fetch_is_a_warning_and_keeps_the_rest_of_the_run(
    app: FastAPI, db_session: Session
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    sources = Sources(
        edgar=FakeEdgar(),
        prices=FakePrices(),
        market=FakeMarket(),
        consensus=FakeConsensus(raises=SourceUnavailable("yahoo is down")),
    )

    run = run_scheduled_refresh(
        app.state.session_factory, sources, datetime(2026, 10, 8, 14, 30, tzinfo=UTC)
    )

    assert run.market_refreshed and run.new_prices["AAPL"] > 0
    assert any(w.startswith("AAPL: consensus not updated: ") for w in run.warnings)
    assert _stored_consensus(db_session) == 0


# --- the new-filing check (M7c, FR-DATA-23) -----------------------------------------------------


def _aapl_index() -> FakeSubmissions:
    doc = json.loads((FIXTURES / "edgar" / "recent_filings" / "AAPL.json").read_text())
    return FakeSubmissions({"AAPL": parse_recent_filings(doc)})


def _count(session: Session, model: Any) -> int:
    session.expire_all()
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def test_a_run_checks_the_filing_index_even_when_the_market_is_not_due(
    seed_db: Any, app: FastAPI, db_session: Session
) -> None:
    seed_db("AAPL")
    now = datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
    market = Sources(edgar=FakeEdgar(), prices=FakePrices(), market=FakeMarket())
    run_scheduled_refresh(app.state.session_factory, market, now)  # the market is now fresh
    submissions = _aapl_index()
    sources = Sources(
        edgar=FakeEdgar(), prices=FakePrices(), market=FakeMarket(), submissions=submissions
    )

    run = run_scheduled_refresh(app.state.session_factory, sources, now.replace(hour=15))

    assert run.filings_checked and not run.market_refreshed
    assert submissions.calls == ["AAPL"]
    db_session.expire_all()
    marked = db_session.execute(select(PendingFiling)).scalars().all()
    assert [(row.accession_no, row.form) for row in marked] == [("0000320193-26-000029", "10-K")]


def test_a_run_without_an_index_source_checks_no_filing(
    seed_db: Any, app: FastAPI, db_session: Session
) -> None:
    seed_db("AAPL")
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices())

    run = run_scheduled_refresh(
        app.state.session_factory, sources, datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
    )

    assert not run.filings_checked
    assert _count(db_session, PendingFiling) == 0


def test_a_scheduled_run_ingests_no_filing_and_no_fact(
    seed_db: Any, app: FastAPI, db_session: Session
) -> None:
    seed_db("AAPL")
    filings, facts = _count(db_session, Filing), _count(db_session, RawFact)
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), submissions=_aapl_index())

    run_scheduled_refresh(
        app.state.session_factory, sources, datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
    )

    assert (_count(db_session, Filing), _count(db_session, RawFact)) == (filings, facts)
    assert _count(db_session, PendingFiling) == 1


def test_a_failing_index_is_a_warning_and_the_market_still_refreshes(
    app: FastAPI, db_session: Session
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    sources = Sources(
        edgar=FakeEdgar(),
        prices=FakePrices(),
        market=FakeMarket(),
        submissions=FakeSubmissions(raises=SourceUnavailable("edgar is down")),
    )

    run = run_scheduled_refresh(
        app.state.session_factory, sources, datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
    )

    assert run.filings_checked and run.market_refreshed
    assert "AAPL: filings not checked: edgar is down" in run.warnings


def test_only_one_process_holds_the_scheduler_lock(tmp_path: Path) -> None:
    # The prod image runs three uvicorn workers: only the lock holder runs the loop.
    first = acquire_scheduler_lock(tmp_path)
    assert first is not None
    assert acquire_scheduler_lock(tmp_path) is None
    first.close()
    again = acquire_scheduler_lock(tmp_path)
    assert again is not None
    again.close()


# --- the startup run (a dev reload or a restart re-pulls nothing a run already has) ----------


@pytest.mark.parametrize(
    ("last_run", "now", "due"),
    [
        (None, ny(2026, 11, 9, 10, 50), True),  # never run
        (ny(2026, 11, 9, 10, 30), ny(2026, 11, 9, 10, 50), False),  # no slot since the last run
        (ny(2026, 11, 9, 10, 30), ny(2026, 11, 9, 11, 30), True),  # the 11:30 slot has come
        (ny(2026, 11, 13, 16, 15), ny(2026, 11, 14, 12, 0), False),  # Friday close → Saturday
        (ny(2026, 11, 13, 16, 15), ny(2026, 11, 16, 9, 45), True),  # missed Monday's open
    ],
)
def test_the_startup_run_is_due_once_a_slot_has_passed_since_the_last_run(
    last_run: datetime | None, now: datetime, due: bool
) -> None:
    assert startup_due(last_run, now) is due


def test_the_last_run_round_trips_and_a_missing_or_bad_file_is_none(tmp_path: Path) -> None:
    assert read_last_run(tmp_path) is None
    when = datetime(2026, 11, 9, 15, 30, tzinfo=UTC)

    write_last_run(tmp_path, when)

    assert read_last_run(tmp_path) == when
    (tmp_path / "scheduler.last_run").write_text("not a time")
    assert read_last_run(tmp_path) is None


class _Stop(Exception):
    """Ends the loop at its first sleep."""


def _run_loop_once(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, now: datetime
) -> list[datetime]:
    runs: list[datetime] = []

    def fake_run(session_factory: Any, sources: Any, at: datetime) -> ScheduledRun:
        runs.append(at)
        return ScheduledRun()

    async def stop(delay: float) -> None:
        raise _Stop

    monkeypatch.setattr(scheduler, "run_scheduled_refresh", fake_run)
    monkeypatch.setattr(scheduler.asyncio, "sleep", stop)
    with pytest.raises(_Stop):
        asyncio.run(refresh_loop(lambda: None, None, lambda: now, data_dir))  # type: ignore[arg-type]
    return runs


def test_the_loop_skips_the_startup_run_when_no_slot_has_passed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_last_run(tmp_path, ny(2026, 11, 9, 10, 30))

    assert _run_loop_once(monkeypatch, tmp_path, ny(2026, 11, 9, 10, 50)) == []
    assert read_last_run(tmp_path) == ny(2026, 11, 9, 10, 30)


def test_the_loop_runs_at_startup_when_a_slot_has_passed_and_records_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_last_run(tmp_path, ny(2026, 11, 9, 10, 30))
    now = ny(2026, 11, 9, 11, 40)

    assert _run_loop_once(monkeypatch, tmp_path, now) == [now]
    assert read_last_run(tmp_path) == now


# --- archived companies (M7c S6, FR-WS-07) ------------------------------------------------------


def test_a_run_leaves_an_archived_company_alone(
    seed_db: Any, app: FastAPI, db_session: Session
) -> None:
    seed_db("AAPL", "MSFT")
    db_session.execute(
        text("UPDATE company SET archived_at = '2026-10-01 00:00:00' WHERE ticker = 'AAPL'")
    )
    db_session.commit()
    consensus, index = FakeConsensus(), FakeSubmissions()
    sources = Sources(
        edgar=FakeEdgar(),
        prices=FakePrices(),
        market=FakeMarket(),
        consensus=consensus,
        submissions=index,
    )

    run = run_scheduled_refresh(
        app.state.session_factory, sources, datetime(2026, 10, 8, 14, 30, tzinfo=UTC)
    )

    assert set(run.new_prices) == {"MSFT"}  # no prices for the archived one
    assert consensus.calls == ["MSFT"]
    assert index.calls == ["MSFT"]
    assert run.market_refreshed and run.filings_checked
