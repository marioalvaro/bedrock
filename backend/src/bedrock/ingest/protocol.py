from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypeVar

if TYPE_CHECKING:
    from bedrock.analysis.consensus import ConsensusRow, EpsHistoryRow

P = TypeVar("P", covariant=True)


class UnknownTicker(Exception):
    """The ticker is not known to the source."""


class SourceUnavailable(Exception):
    """A network or upstream failure."""


class SourceNotConfigured(Exception):
    """The source needs configuration that is missing (e.g. `SEC_USER_AGENT`)."""


@dataclass(frozen=True)
class CompanyRef:
    ticker: str
    cik: str | None  # None for a manual company, which has no SEC filer


@dataclass(frozen=True)
class CompanyProfile:
    cik: str
    ticker: str
    name: str
    sic: str | None
    fiscal_year_end_month: int


@dataclass(frozen=True)
class EdgarPayload:
    companyfacts: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class PriceRow:
    date: date
    close: Decimal
    adj_close: Decimal
    volume: int


@dataclass(frozen=True)
class SplitRow:
    effective_date: date
    ratio: Decimal  # new shares per old share: 4 for a 4-for-1 split, 0.1 for a 1-for-10 reverse


@dataclass(frozen=True)
class PricePayload:
    rows: list[PriceRow]
    # The full split history, whatever `since` was: it is a handful of rows.
    splits: list[SplitRow] = field(default_factory=list)


class DataSource(Protocol[P]):
    name: ClassVar[str]

    def fetch(self, company: CompanyRef, since: date | None) -> P: ...


class EdgarLike(DataSource[EdgarPayload], Protocol):
    """What the services need from EDGAR: `EdgarSource`, or a test double."""

    def resolve(self, ticker: str) -> CompanyProfile: ...


class FilingsLike(Protocol):
    """What the services need from the EDGAR filing archive: `EdgarFilingsSource`, or a test
    double. `fetch` gives one filing's XBRL files by name, {} when it has no XBRL instance, and
    raises SourceUnavailable."""

    def fetch(self, company: CompanyRef, accession_no: str) -> dict[str, bytes]: ...


@dataclass(frozen=True)
class FilingRef:
    """One 10-K or 10-Q as EDGAR's filing index lists it (M7c, FR-DATA-23)."""

    accession_no: str
    form: str  # 10-K | 10-Q
    filed_at: date
    period_end: date | None  # EDGAR's `reportDate`; None when blank


class SubmissionsLike(Protocol):
    """What the services need from EDGAR's filing index: `EdgarSource`, or a test double.
    `recent_filings` gives the 10-K and 10-Q rows, newest first, and raises SourceUnavailable."""

    def recent_filings(self, company: CompanyRef) -> list[FilingRef]: ...


class PricesLike(DataSource[PricePayload], Protocol):
    """What the services need from the price source: `YFinanceSource`, or a test double."""


@dataclass(frozen=True)
class SeriesPayload:
    """One market series as fetched: `(date, value)` rows oldest first, values as published."""

    series_id: str
    title: str
    frequency: str  # daily | monthly
    source: str  # fred | yfinance | damodaran
    rows: list[tuple[date, Decimal]]


class MarketLike(Protocol):
    """What the services need for the market defaults: `MarketSource`, or a test double. Each
    call raises SourceUnavailable on its own failure."""

    def risk_free(self, today: date) -> SeriesPayload: ...

    def erp(self, today: date) -> SeriesPayload: ...

    def index(self, today: date) -> SeriesPayload: ...


class ConsensusLike(Protocol):
    """What the services need for the analyst consensus: `YFinanceConsensus`, or a test double.
    Raises SourceUnavailable."""

    def fetch(self, company: CompanyRef) -> "list[ConsensusRow]": ...

    def history(self, company: CompanyRef) -> "list[EpsHistoryRow]": ...
