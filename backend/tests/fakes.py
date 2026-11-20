"""Test doubles for the external sources, served from the recorded fixtures (no network)."""

import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from bedrock.analysis.consensus import (
    ConsensusRow,
    EpsHistoryRow,
    history_from_frame,
    rows_from_frames,
)
from bedrock.ingest.protocol import (
    CompanyProfile,
    CompanyRef,
    EdgarPayload,
    FilingRef,
    PricePayload,
    PriceRow,
    SeriesPayload,
    SourceUnavailable,
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


class FakeMarket:
    """Fixed market series: a 10-year yield of 4.25 %, an ERP of 4.41 % and five S&P 500
    month-ends. `fail` names the calls (`risk_free`, `erp`, `index`) that raise."""

    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise SourceUnavailable(f"{name} is down")

    def risk_free(self, today: date) -> SeriesPayload:
        self._call("risk_free")
        rows = [(date(2026, 10, 7), Decimal("4.2")), (date(2026, 10, 8), Decimal("4.25"))]
        return SeriesPayload("^TNX", "10-year Treasury yield", "daily", "yfinance", rows)

    def erp(self, today: date) -> SeriesPayload:
        self._call("erp")
        rows = [(date(2026, 10, 1), Decimal("4.41"))]
        return SeriesPayload("DAMODARAN_ERP", "Damodaran implied ERP", "monthly", "damodaran", rows)

    def index(self, today: date) -> SeriesPayload:
        self._call("index")
        rows = [(date(2026, m, 1), Decimal(6000 + 10 * m)) for m in range(6, 11)]
        return SeriesPayload("^GSPC", "S&P 500", "monthly", "yfinance", rows)


class FakeConsensus:
    """Yahoo's recorded AAPL consensus frames (tests/fixtures/consensus); other tickers have none.
    `raises` fails both calls; `rows` replaces what `fetch` serves (and empties the history)."""

    def __init__(
        self, raises: Exception | None = None, rows: list[ConsensusRow] | None = None
    ) -> None:
        self.raises = raises
        self.rows = rows  # served for every ticker instead of the recorded frames
        self.calls: list[str] = []

    def fetch(self, company: CompanyRef) -> list[ConsensusRow]:
        self.calls.append(company.ticker)
        if self.raises is not None:
            raise self.raises
        if self.rows is not None:
            return list(self.rows)
        revenue = FIXTURES / "consensus" / f"{company.ticker}_revenue_estimate.csv"
        earnings = FIXTURES / "consensus" / f"{company.ticker}_earnings_estimate.csv"
        if not revenue.is_file() or not earnings.is_file():
            return []
        return rows_from_frames(
            pd.read_csv(revenue, index_col="period"), pd.read_csv(earnings, index_col="period")
        )

    def history(self, company: CompanyRef) -> list[EpsHistoryRow]:
        if self.raises is not None:
            raise self.raises
        path = FIXTURES / "consensus" / f"{company.ticker}_earnings_history.csv"
        if self.rows is not None or not path.is_file():
            return []
        return history_from_frame(pd.read_csv(path, index_col="quarter"))


class FakeFilings:
    """The EDGAR filing archive from the recorded filings (`fixtures/edgar/filings/<TICKER>/
    <accession>/`); any other accession has no XBRL instance (`{}`), like a filing from before
    XBRL. `fail` maps an accession to the exception its fetch raises; `broken` accessions return
    an unreadable instance. `calls` lists every accession fetched."""

    def __init__(
        self, fail: dict[str, Exception] | None = None, broken: set[str] | None = None
    ) -> None:
        self.fail = dict(fail or {})
        self.broken = set(broken or ())
        self.raises: Exception | None = None  # set to fail every fetch
        self.calls: list[str] = []

    def fetch(self, company: CompanyRef, accession_no: str) -> dict[str, bytes]:
        self.calls.append(accession_no)
        if self.raises is not None:
            raise self.raises
        if accession_no in self.fail:
            raise self.fail[accession_no]
        if accession_no in self.broken:
            return {"broken_htm.xml": b"<xbrli:xbrl"}
        return dict(_recorded_filing(company.ticker, accession_no))


@cache
def _recorded_filing(ticker: str, accession_no: str) -> tuple[tuple[str, bytes], ...]:
    folder = FIXTURES / "edgar" / "filings" / ticker / accession_no
    if not folder.is_dir():
        return ()
    return tuple(
        (path.name.removesuffix(".gz"), gzip.decompress(path.read_bytes()))
        for path in sorted(folder.iterdir())
    )


class FakeSubmissions:
    """EDGAR's filing index: `rows` maps a ticker to the refs it lists (none for any other
    ticker). Set `raises` (also after construction) to fail every call. `calls` lists the ticker
    of every call, failing ones too."""

    def __init__(
        self, rows: dict[str, list[FilingRef]] | None = None, raises: Exception | None = None
    ) -> None:
        self.rows = dict(rows or {})
        self.raises = raises
        self.calls: list[str] = []

    def recent_filings(self, company: CompanyRef) -> list[FilingRef]:
        self.calls.append(company.ticker)
        if self.raises is not None:
            raise self.raises
        return list(self.rows.get(company.ticker, []))
