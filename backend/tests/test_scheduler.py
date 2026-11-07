"""The scheduled refresh (docs/erd/data.md "Scheduled refresh"): when it runs, and what a run
does. The asyncio loop that sleeps between runs is a thin shell around these two."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from bedrock.core.scheduler import acquire_scheduler_lock, next_run, run_scheduled_refresh
from bedrock.ingest.sources import Sources
from bedrock.repositories import macro

from .fakes import FakeEdgar, FakeMarket, FakePrices
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


def test_only_one_process_holds_the_scheduler_lock(tmp_path: Path) -> None:
    # The prod image runs three uvicorn workers: only the lock holder runs the loop.
    first = acquire_scheduler_lock(tmp_path)
    assert first is not None
    assert acquire_scheduler_lock(tmp_path) is None
    first.close()
    again = acquire_scheduler_lock(tmp_path)
    assert again is not None
    again.close()
