"""The scheduled refresh (docs/erd/data.md "Scheduled refresh"): every followed company's prices
hourly in US market hours and once after the close, and the market series and the analyst
consensus once a day. Never
EDGAR: filings change a few times a year and stay behind the Refresh button."""

import asyncio
import fcntl
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.services import consensus as consensus_service
from bedrock.services import market as market_service
from bedrock.services.prices import refresh_all_prices

log = logging.getLogger(__name__)

NEW_YORK = ZoneInfo("America/New_York")
# 9:30 … 15:30 in the session, then 16:15 for the final close.
RUN_TIMES = (*(time(h, 30) for h in range(9, 16)), time(16, 15))


def acquire_scheduler_lock(data_dir: Path) -> IO[bytes] | None:
    """An exclusive lock on `<data_dir>/scheduler.lock`, held while the returned file stays open,
    or None when another process holds it: with several uvicorn workers only one runs the loop.
    The OS drops the lock when the holder exits."""
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = (data_dir / "scheduler.lock").open("wb")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def next_run(now: datetime) -> datetime:
    """The first run time strictly after `now`, on a weekday, in New York time. Exchange
    holidays are not skipped: a run then finds nothing new."""
    local = now.astimezone(NEW_YORK)
    day = local.date()
    while True:
        if day.weekday() < 5:
            for at in RUN_TIMES:
                candidate = datetime.combine(day, at, tzinfo=NEW_YORK)
                if candidate > local:
                    return candidate
        day += timedelta(days=1)


LAST_RUN_FILE = "scheduler.last_run"


def startup_due(last_run: datetime | None, now: datetime) -> bool:
    """Whether the run at startup is needed: never run, or a run time has come since the last
    run. A restart or a dev reload inside the same slot then re-pulls nothing."""
    return last_run is None or next_run(last_run) <= now


def read_last_run(data_dir: Path) -> datetime | None:
    """When the last run finished (`<data_dir>/scheduler.last_run`); None when the file is missing
    or unreadable, so the startup run happens."""
    try:
        when = datetime.fromisoformat((data_dir / LAST_RUN_FILE).read_text().strip())
    except (OSError, ValueError):
        return None
    return when if when.tzinfo is not None else None


def write_last_run(data_dir: Path, when: datetime) -> None:
    (data_dir / LAST_RUN_FILE).write_text(when.isoformat())


@dataclass
class ScheduledRun:
    new_prices: dict[str, int] = field(default_factory=dict)
    market_refreshed: bool = False
    warnings: list[str] = field(default_factory=list)


def run_scheduled_refresh(
    session_factory: Callable[[], Session], sources: Sources, now: datetime
) -> ScheduledRun:
    """One run: every company's prices, then, when a day has passed, the market series and every
    company's analyst consensus (a failing company is a warning; its stored rows are kept)."""
    with session_factory() as session:
        prices = refresh_all_prices(session, sources, now)
        run = ScheduledRun(new_prices=prices.new_prices, warnings=list(prices.warnings))
        if sources.market is None or not market_service.market_due(session, now):
            return run
        run.warnings += market_service.refresh_market(session, sources, now)
        run.market_refreshed = True
        if sources.consensus is not None:
            run.warnings += _refresh_all_consensus(session, sources, now)
    return run


def _refresh_all_consensus(session: Session, sources: Sources, now: datetime) -> list[str]:
    assert sources.consensus is not None
    warnings: list[str] = []
    for company in session.execute(select(Company).order_by(Company.ticker)).scalars().all():
        try:
            consensus_service.refresh_consensus(session, sources.consensus, company, now)
        except SourceUnavailable as error:
            session.rollback()
            warnings.append(f"{company.ticker}: consensus not updated: {error}")
    return warnings


async def refresh_loop(
    session_factory: Callable[[], Session],
    sources: Sources,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    data_dir: Path | None = None,
) -> None:
    """Run once at startup (prices may be days old) unless no run time has passed since the last
    run recorded in `data_dir`, then at each `next_run`. A run that finishes is recorded; a
    failing run is logged and the loop goes on."""
    first = True
    while True:
        if not first or data_dir is None or startup_due(read_last_run(data_dir), clock()):
            try:
                at = clock()
                run = await asyncio.to_thread(run_scheduled_refresh, session_factory, sources, at)
                for warning in run.warnings:
                    log.warning("scheduled refresh: %s", warning)
                if data_dir is not None:
                    write_last_run(data_dir, at)
            except Exception:
                log.exception("scheduled refresh failed")
        first = False
        delay = (next_run(clock()) - clock()).total_seconds()
        await asyncio.sleep(max(delay, 1.0))
