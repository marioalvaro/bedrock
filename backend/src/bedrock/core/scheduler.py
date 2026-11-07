"""The scheduled refresh (docs/erd/data.md "Scheduled refresh"): every followed company's prices
hourly in US market hours and once after the close, and the market series once a day. Never
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

from sqlalchemy.orm import Session

from bedrock.ingest.sources import Sources
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


@dataclass
class ScheduledRun:
    new_prices: dict[str, int] = field(default_factory=dict)
    market_refreshed: bool = False
    warnings: list[str] = field(default_factory=list)


def run_scheduled_refresh(
    session_factory: Callable[[], Session], sources: Sources, now: datetime
) -> ScheduledRun:
    """One run: every company's prices, then the market series when a day has passed."""
    with session_factory() as session:
        prices = refresh_all_prices(session, sources, now)
        run = ScheduledRun(new_prices=prices.new_prices, warnings=list(prices.warnings))
        if sources.market is not None and market_service.market_due(session, now):
            run.warnings += market_service.refresh_market(session, sources, now)
            run.market_refreshed = True
    return run


async def refresh_loop(
    session_factory: Callable[[], Session],
    sources: Sources,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Run once at startup (prices may be days old), then at each `next_run`. A failing run is
    logged and the loop goes on."""
    while True:
        try:
            run = await asyncio.to_thread(run_scheduled_refresh, session_factory, sources, clock())
            for warning in run.warnings:
                log.warning("scheduled refresh: %s", warning)
        except Exception:
            log.exception("scheduled refresh failed")
        delay = (next_run(clock()) - clock()).total_seconds()
        await asyncio.sleep(max(delay, 1.0))
