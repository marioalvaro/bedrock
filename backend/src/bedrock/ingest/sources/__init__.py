import threading
from dataclasses import dataclass

from bedrock.core.config import Settings
from bedrock.ingest.cache import RawCache
from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import (
    ConsensusLike,
    EdgarLike,
    FilingsLike,
    MarketLike,
    PricesLike,
    SourceNotConfigured,
)
from bedrock.ingest.sources.edgar import EdgarSource
from bedrock.ingest.sources.edgar_filings import EdgarFilingsSource
from bedrock.ingest.sources.market import MarketSource
from bedrock.ingest.sources.yfinance import YFinanceConsensus, YFinanceSource


@dataclass(frozen=True)
class Sources:
    edgar: EdgarLike
    prices: PricesLike
    # The market series behind the valuation defaults; None (tests) fetches nothing.
    market: MarketLike | None = None
    # Yahoo's analyst consensus, logged as guidance; None (tests) fetches nothing.
    consensus: ConsensusLike | None = None
    # Each 10-K and 10-Q's own XBRL files (M7b S6); None (tests) fetches nothing.
    filings: FilingsLike | None = None


def build_sources(settings: Settings) -> Sources:
    """The app's external sources. Makes no network call, and never fails for missing config:
    `SourceNotConfigured` is raised on the first use of EDGAR instead."""
    user_agent = settings.sec_user_agent

    shared: list[RateLimitedClient] = []
    lock = threading.Lock()

    def edgar_client() -> RateLimitedClient:
        # One client for companyfacts and the filing archive, so both share SEC's rate limit.
        if not user_agent:
            raise SourceNotConfigured("SEC_USER_AGENT is not set")
        with lock:
            if not shared:
                shared.append(RateLimitedClient(user_agent))
            return shared[0]

    return Sources(
        edgar=EdgarSource(edgar_client, RawCache(settings.data_dir)),
        filings=EdgarFilingsSource(edgar_client, settings.data_dir),
        prices=YFinanceSource(),
        market=MarketSource(settings.fred_api_key),
        consensus=YFinanceConsensus(),
    )
