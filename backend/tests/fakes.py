"""Test doubles for the external sources, served from the recorded fixtures (no network)."""

import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from bedrock.ingest.protocol import (
    CompanyProfile,
    CompanyRef,
    EdgarPayload,
    PricePayload,
    PriceRow,
    SplitRow,
    UnknownTicker,
)

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@cache
def _companyfacts(ticker: str) -> dict[str, Any]:
    with gzip.open(FIXTURES / "edgar" / f"{ticker}.json.gz", "rt") as handle:
        doc: dict[str, Any] = json.load(handle)
    return doc


@cache
def _prices(ticker: str) -> tuple[PriceRow, ...]:
    if not (FIXTURES / "yfinance" / f"{ticker}.csv").is_file():
        return ()  # a ticker the source has no history for (a manual company's)
    frame = pd.read_csv(FIXTURES / "yfinance" / f"{ticker}.csv", index_col="Date")
    return tuple(
        PriceRow(
            date=date.fromisoformat(str(day)),
            close=Decimal(str(round(float(row["Close"]), 4))),
            adj_close=Decimal(str(round(float(row["Adj Close"]), 4))),
            volume=int(row["Volume"]),
        )
        for day, row in frame.iterrows()
    )


@cache
def _splits(ticker: str) -> tuple[SplitRow, ...]:
    path = FIXTURES / "yfinance" / f"{ticker}_splits.csv"
    if not path.is_file():
        return ()
    frame = pd.read_csv(path, dtype=str)
    return tuple(
        SplitRow(date.fromisoformat(row["date"]), Decimal(row["ratio"]))
        for _, row in frame.iterrows()
    )


class FakeEdgar:
    """EDGAR for the recorded tickers. Set `raises` (also after construction) to make every
    call fail with that exception, or `fetch_raises` to fail the companyfacts fetch only."""

    name: ClassVar[str] = "edgar"

    def __init__(
        self, raises: Exception | None = None, fetch_raises: Exception | None = None
    ) -> None:
        self.raises = raises
        self.fetch_raises = fetch_raises

    def resolve(self, ticker: str) -> CompanyProfile:
        if self.raises is not None:
            raise self.raises
        wanted = ticker.strip().upper()
        path = FIXTURES / "edgar" / "submissions" / f"{wanted}.json"
        if not path.is_file():
            raise UnknownTicker(ticker)
        submissions = json.loads(path.read_text())
        return CompanyProfile(
            cik=f"{int(submissions['cik']):010d}",
            ticker=wanted,
            name=submissions["name"],
            sic=submissions.get("sic") or None,
            fiscal_year_end_month=int(submissions["fiscalYearEnd"][:2]),
        )

    def fetch(self, company: CompanyRef, since: date | None) -> EdgarPayload:
        if self.raises is not None:
            raise self.raises
        if self.fetch_raises is not None:
            raise self.fetch_raises
        return EdgarPayload(companyfacts=_companyfacts(company.ticker), fetched_at=FETCHED_AT)


class FakePrices:
    """One year of recorded daily prices; like the real source, only rows after `since`, and the
    full recorded split history every time. `raises` fails the whole fetch (prices and splits)."""

    name: ClassVar[str] = "yfinance"

    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[date | None] = []  # the `since` of each fetch

    def fetch(self, company: CompanyRef, since: date | None) -> PricePayload:
        self.calls.append(since)
        if self.raises is not None:
            raise self.raises
        rows = _prices(company.ticker)
        return PricePayload(
            rows=[r for r in rows if since is None or r.date > since],
            splits=list(_splits(company.ticker)),
        )
