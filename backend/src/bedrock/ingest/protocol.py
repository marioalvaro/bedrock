from dataclasses import dataclass
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
    cik: str


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
class PricePayload:
    rows: list[PriceRow]


class DataSource(Protocol[P]):
    name: ClassVar[str]

    def fetch(self, company: CompanyRef, since: date | None) -> P: ...
