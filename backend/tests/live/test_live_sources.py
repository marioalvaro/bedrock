"""Smoke tests against the real APIs. Opt-in: `uv run pytest -m live` (needs SEC_USER_AGENT)."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from bedrock.core.config import load_settings
from bedrock.ingest.protocol import CompanyRef
from bedrock.ingest.sources import Sources, build_sources

pytestmark = pytest.mark.live


@pytest.fixture
def sources(tmp_path: Path) -> Sources:
    settings = load_settings().model_copy(update={"data_dir": tmp_path})
    return build_sources(settings)


def test_edgar_resolves_aapl(sources: Sources) -> None:
    profile = sources.edgar.resolve("AAPL")

    assert profile.cik == "0000320193"
    assert profile.name == "Apple Inc."
    assert profile.fiscal_year_end_month == 9


def test_edgar_companyfacts_has_us_gaap_and_is_cached(sources: Sources, tmp_path: Path) -> None:
    payload = sources.edgar.fetch(CompanyRef("AAPL", "0000320193"), None)

    assert "us-gaap" in payload.companyfacts["facts"]
    assert len(list((tmp_path / "raw" / "edgar" / "0000320193").glob("*.json"))) == 1


def test_yfinance_returns_recent_prices(sources: Sources) -> None:
    payload = sources.prices.fetch(
        CompanyRef("AAPL", "0000320193"), date.today() - timedelta(days=14)
    )

    assert len(payload.rows) >= 1
    assert all(row.close > 0 for row in payload.rows)
