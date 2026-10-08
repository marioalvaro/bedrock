import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import ClassVar

from bedrock.ingest.cache import RawCache
from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import CompanyProfile, CompanyRef, EdgarPayload, UnknownTicker

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EdgarSource:
    name: ClassVar[str] = "edgar"

    def __init__(
        self,
        client_factory: Callable[[], RateLimitedClient],
        cache: RawCache,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client_factory = client_factory
        self._cache = cache
        self._clock = clock
        self._client: RateLimitedClient | None = None

    def resolve(self, ticker: str) -> CompanyProfile:
        client = self._get_client()
        wanted = ticker.strip().upper()
        for entry in client.get_json(_TICKERS_URL).values():
            if entry["ticker"].upper() == wanted:
                cik = f"{int(entry['cik_str']):010d}"
                break
        else:
            raise UnknownTicker(ticker)
        submissions = client.get_json(_SUBMISSIONS_URL.format(cik=cik))
        return CompanyProfile(
            cik=cik,
            ticker=wanted,
            name=submissions["name"],
            sic=submissions.get("sic") or None,
            # "0928" is MMDD.
            fiscal_year_end_month=int(submissions["fiscalYearEnd"][:2]),
        )

    def fetch(self, company: CompanyRef, since: date | None) -> EdgarPayload:
        """Companyfacts is always the full history, so `since` is ignored."""
        body = self._get_client().get(_COMPANYFACTS_URL.format(cik=company.cik))
        fetched_at = self._clock()
        self._cache.write(company.cik, fetched_at.date(), body)
        return EdgarPayload(companyfacts=json.loads(body), fetched_at=fetched_at)

    def _get_client(self) -> RateLimitedClient:
        # Built on first use, so a missing SEC_USER_AGENT fails there and never at app start.
        if self._client is None:
            self._client = self._client_factory()
        return self._client
