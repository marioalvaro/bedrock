from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.analysis.comps import CompsCategory, CompsRow, Match, PeerSuggestion
from bedrock.ratios.registry import Unit
from bedrock.services.comps import Comparison, SetView


class CompsSetIn(BaseModel):
    """`members` are tickers of followed companies; a PUT replaces them all."""

    name: str
    members: list[str]


class CompsMemberOut(BaseModel):
    ticker: str
    name: str


class CompsSetOut(BaseModel):
    id: int
    name: str
    members: list[CompsMemberOut]  # by ticker

    @classmethod
    def from_view(cls, view: SetView) -> "CompsSetOut":
        return cls(
            id=view.id,
            name=view.name,
            members=[CompsMemberOut(ticker=m.ticker, name=m.name) for m in view.members],
        )


class PeerSuggestionOut(BaseModel):
    ticker: str
    name: str
    sic: str
    match: Match
    market_cap: Decimal | None
    in_set: bool

    @classmethod
    def from_suggestion(cls, s: PeerSuggestion) -> "PeerSuggestionOut":
        return cls(**s.__dict__)


class ComparedCompanyOut(BaseModel):
    ticker: str
    name: str
    price_date: date | None
    ttm_period: str | None


class CellCaveatOut(BaseModel):
    ticker: str
    text: str


class CompsRowOut(BaseModel):
    """`pct` values are fractions. `peers` is aligned with `CompsOut.companies[1:]`; `n` counts
    the peer values the statistics use. `target_vs_median` is a ratio minus one for `x` and
    `days` rows and a difference for `pct` rows; `target_rank` is 1 for the highest."""

    code: str
    label: str
    category: CompsCategory
    unit: Unit
    target: Decimal | None
    peers: list[Decimal | None]
    peer_median: Decimal | None
    peer_min: Decimal | None
    peer_max: Decimal | None
    n: int
    target_vs_median: Decimal | None
    target_rank: int | None
    caveats: list[CellCaveatOut]

    @classmethod
    def from_row(cls, r: CompsRow) -> "CompsRowOut":
        return cls(
            **{
                **r.__dict__,
                "caveats": [CellCaveatOut(ticker=c.ticker, text=c.text) for c in r.caveats],
            }
        )


class CompsOut(BaseModel):
    ticker: str
    set_id: int
    name: str
    basis: Literal["reported", "normalized"]
    companies: list[ComparedCompanyOut]  # the target first
    rows: list[CompsRowOut]

    @classmethod
    def from_comparison(cls, ticker: str, c: Comparison) -> "CompsOut":
        return cls(
            ticker=ticker,
            set_id=c.set.id,
            name=c.set.name,
            basis=c.basis,
            companies=[ComparedCompanyOut(**x.__dict__) for x in c.companies],
            rows=[CompsRowOut.from_row(r) for r in c.table.rows],
        )
