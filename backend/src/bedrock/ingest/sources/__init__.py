from dataclasses import dataclass

from bedrock.core.config import Settings
from bedrock.ingest.cache import RawCache
from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import (
    EdgarLike,
    MarketLike,
    PricesLike,
    SourceNotConfigured,
)
from bedrock.ingest.sources.edgar import EdgarSource
from bedrock.ingest.sources.market import MarketSource
from bedrock.ingest.sources.yfinance import YFinanceSource


@dataclass(frozen=True)
class Sources:
    edgar: EdgarLike
    prices: PricesLike
    # The market series behind the valuation defaults; None (tests) fetches nothing.
    market: MarketLike | None = None


def build_sources(settings: Settings) -> Sources:
    """The app's external sources. Makes no network call, and never fails for missing config:
    `SourceNotConfigured` is raised on the first use of EDGAR instead."""
    user_agent = settings.sec_user_agent

    def edgar_client() -> RateLimitedClient:
        if not user_agent:
            raise SourceNotConfigured("SEC_USER_AGENT is not set")
        return RateLimitedClient(user_agent)

    return Sources(
        edgar=EdgarSource(edgar_client, RawCache(settings.data_dir)),
        prices=YFinanceSource(),
        market=MarketSource(settings.fred_api_key),
    )
