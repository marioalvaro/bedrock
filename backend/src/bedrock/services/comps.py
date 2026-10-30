"""Comps sets, peer suggestions and the peer comparison of a followed company (FR-ANL-08)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.analysis.comps import (
    COMPS_ROWS,
    CompanyFigures,
    CompsTable,
    PeerCandidate,
    PeerSuggestion,
    compare,
    suggest_peers,
)
from bedrock.models.company import Company
from bedrock.models.comps_set import CompsSet
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import comps as repo
from bedrock.services import ratios as ratios_service
from bedrock.services.errors import CompsSetNotFound, InvalidCompsSet
from bedrock.services.statements import Basis, company_key_stats

__all__ = [
    "Comparison",
    "ComparedCompany",
    "SetView",
    "comparison",
    "create_set",
    "delete_set",
    "list_sets",
    "peer_suggestions",
    "update_set",
]

NAME_LIMIT = 60


@dataclass(frozen=True)
class SetView:
    id: int
    name: str
    members: list[Company]  # by ticker


@dataclass(frozen=True)
class ComparedCompany:
    ticker: str
    name: str
    price_date: date | None  # the latest close
    ttm_period: str | None  # label of the latest TTM period


@dataclass(frozen=True)
class Comparison:
    set: SetView
    basis: Basis
    companies: list[ComparedCompany]  # the target first, then the members by ticker
    table: CompsTable


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def list_sets(session: Session, company: Company) -> list[SetView]:
    """The company's sets by name, with their members by ticker."""
    sets = repo.list_sets(session, company.id)
    members = repo.members(session, [s.id for s in sets])
    return [SetView(s.id, s.name, members[s.id]) for s in sets]


def create_set(
    session: Session, company: Company, name: str, tickers: Sequence[str], now: datetime
) -> SetView:
    """Validates, stores (name stripped) and commits. Raises InvalidCompsSet for a blank name or
    one over `NAME_LIMIT` characters or already used by another set of the company, and for a
    member that is the company itself, listed twice or not a followed company."""
    clean = _check_name(session, company, name, None)
    peers = _resolve_members(session, company, tickers)
    stamp = _naive_utc(now)
    created = repo.add_set(
        session,
        CompsSet(company_id=company.id, name=clean, created_at=stamp, updated_at=stamp),
        [p.id for p in peers],
    )
    session.commit()
    return SetView(created.id, created.name, peers)


def update_set(
    session: Session,
    company: Company,
    set_id: int,
    name: str,
    tickers: Sequence[str],
    now: datetime,
) -> SetView:
    """Renames the set and replaces its members, under the rules of `create_set`. Raises
    CompsSetNotFound for an unknown id (or another company's)."""
    stored = _get_set(session, company, set_id)
    clean = _check_name(session, company, name, stored.id)
    peers = _resolve_members(session, company, tickers)
    stored.name = clean
    stored.updated_at = _naive_utc(now)
    repo.replace_members(session, stored, [p.id for p in peers])
    session.commit()
    return SetView(stored.id, stored.name, peers)


def delete_set(session: Session, company: Company, set_id: int) -> None:
    repo.delete_set(session, _get_set(session, company, set_id))
    session.commit()


def peer_suggestions(
    session: Session, company: Company, set_id: int | None = None
) -> list[PeerSuggestion]:
    """`analysis/comps.py::suggest_peers` over the other followed companies, with their market
    caps; `in_set` marks the members of set `set_id` (CompsSetNotFound if it is unknown)."""
    in_set = (
        set()
        if set_id is None
        else {p.id for p in repo.members(session, [_get_set(session, company, set_id).id])[set_id]}
    )
    others = [c for c in companies_repo.list_all(session) if c.id != company.id]
    return suggest_peers(
        _candidate(session, company, False),
        [_candidate(session, c, c.id in in_set) for c in others],
    )


def comparison(session: Session, company: Company, set_id: int, basis: Basis) -> Comparison:
    """The company against the members of its set on `basis` (one basis for all). Each figure is
    that company's own number: the current multiple (TTM at the latest close) for the Valuation
    rows, the last non-null TTM ratio for the others, the latest TTM revenue YoY for growth."""
    stored = _get_set(session, company, set_id)
    view = SetView(stored.id, stored.name, repo.members(session, [stored.id])[stored.id])
    compared = [_figures(session, c, basis) for c in (company, *view.members)]
    return Comparison(
        set=view,
        basis=basis,
        companies=[header for header, _ in compared],
        table=compare(compared[0][1], [figures for _, figures in compared[1:]]),
    )


def _figures(
    session: Session, company: Company, basis: Basis
) -> tuple[ComparedCompany, CompanyFigures]:
    current = ratios_service.current_ttm(session, company, basis)
    wanted = {row.code: row for row in COMPS_ROWS}
    values: dict[str, Decimal | None] = {}
    caveats: dict[str, str] = {}
    for ratio in current.table.rows:
        if ratio.code not in wanted:
            continue
        if ratio.category == "Valuation":
            values[ratio.code] = ratio.values[-1] if ratio.values else None
        else:
            values[ratio.code] = next((v for v in reversed(ratio.values) if v is not None), None)
        if ratio.caveat:
            caveats[ratio.code] = ratio.caveat
    revenue = next((r for r in current.income.rows if r.code == "revenue"), None)
    values["revenue_growth"] = revenue.yoy[-1] if revenue is not None and revenue.yoy else None
    periods = current.income.periods
    header = ComparedCompany(
        ticker=company.ticker,
        name=company.name,
        price_date=None if current.close is None else current.close[0],
        ttm_period=periods[-1].label if periods else None,
    )
    return header, CompanyFigures(company.ticker, values, caveats)


def _candidate(session: Session, company: Company, in_set: bool) -> PeerCandidate:
    return PeerCandidate(
        ticker=company.ticker,
        name=company.name,
        sic=company.sic,
        market_cap=company_key_stats(session, company).market_cap,
        in_set=in_set,
    )


def _get_set(session: Session, company: Company, set_id: int) -> CompsSet:
    stored = repo.get_set(session, company.id, set_id)
    if stored is None:
        raise CompsSetNotFound(str(set_id))
    return stored


def _check_name(session: Session, company: Company, name: str, own_id: int | None) -> str:
    clean = name.strip()
    if not clean:
        raise InvalidCompsSet("The name must not be blank")
    if len(clean) > NAME_LIMIT:
        raise InvalidCompsSet(f"The name must be at most {NAME_LIMIT} characters")
    if any(s.name == clean and s.id != own_id for s in repo.list_sets(session, company.id)):
        raise InvalidCompsSet(f"The company already has a comps set named {clean!r}")
    return clean


def _resolve_members(session: Session, company: Company, tickers: Sequence[str]) -> list[Company]:
    peers: dict[str, Company] = {}
    for raw in tickers:
        ticker = raw.strip().upper()
        if ticker == company.ticker:
            raise InvalidCompsSet(f"{ticker} is the company itself, not a peer")
        if ticker in peers:
            raise InvalidCompsSet(f"{ticker} is listed twice")
        peer = companies_repo.get_by_ticker(session, ticker)
        if peer is None:
            raise InvalidCompsSet(f"{ticker} is not a followed company")
        peers[ticker] = peer
    return sorted(peers.values(), key=lambda c: c.ticker)
