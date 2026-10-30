from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol, TypeVar

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


class PricesLike(DataSource[PricePayload], Protocol):
    """What the services need from the price source: `YFinanceSource`, or a test double."""
