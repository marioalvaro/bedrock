"""Peer suggestions and the peer comparison (FR-ANL-08). Pure: figures in, tables out."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Literal

from bedrock.ratios.registry import RATIOS, Unit
from bedrock.statements.build import RATIO_PLACES

Match = Literal["industry", "industry group", "major group"]
CompsCategory = Literal["Valuation", "Profitability", "Solvency", "Efficiency", "Growth"]

# SIC digits shared -> match level; fewer than two shared digits is no match.
_MATCH_BY_DIGITS: dict[int, Match] = {4: "industry", 3: "industry group", 2: "major group"}
_MATCH_RANK = {"industry": 0, "industry group": 1, "major group": 2}


@dataclass(frozen=True)
class PeerCandidate:
    """A followed company as a peer candidate (or the target, whose `in_set` is unused)."""

    ticker: str
    name: str
    sic: str | None
    market_cap: Decimal | None
    in_set: bool = False


@dataclass(frozen=True)
class PeerSuggestion:
    ticker: str
    name: str
    sic: str
    match: Match
    market_cap: Decimal | None
    in_set: bool


def suggest_peers(
    target: PeerCandidate, candidates: Sequence[PeerCandidate]
) -> list[PeerSuggestion]:
    """The candidates that share the target's SIC prefix (4 digits `industry`, 3 `industry group`,
    2 `major group`); others and those without a SIC are left out. Ordered by match strength, then
    by market-cap closeness |ln(candidate / target)| (a missing or non-positive cap, either side,
    last), then ticker."""
    ranked: list[tuple[int, float, str, PeerSuggestion]] = []
    for c in candidates:
        match = _match(target.sic, c.sic)
        if match is None or c.sic is None:
            continue
        suggestion = PeerSuggestion(c.ticker, c.name, c.sic, match, c.market_cap, c.in_set)
        ranked.append((_MATCH_RANK[match], _cap_distance(target, c), c.ticker, suggestion))
    ranked.sort(key=lambda r: r[:3])
    return [r[3] for r in ranked]


def _match(a: str | None, b: str | None) -> Match | None:
    if not a or not b:
        return None
    shared = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        shared += 1
    return _MATCH_BY_DIGITS.get(min(shared, 4))


def _cap_distance(target: PeerCandidate, candidate: PeerCandidate) -> float:
    t, c = target.market_cap, candidate.market_cap
    if t is None or c is None or t <= 0 or c <= 0:
        return math.inf
    return abs(math.log(float(c / t)))


@dataclass(frozen=True)
class CompsRowDef:
    code: str
    label: str
    category: CompsCategory
    unit: Unit


def _registry_rows(category: CompsCategory, codes: str) -> list[CompsRowDef]:
    by_code = {r.code: r for r in RATIOS}
    return [CompsRowDef(c, by_code[c].label, category, by_code[c].unit) for c in codes.split()]


COMPS_ROWS: tuple[CompsRowDef, ...] = (
    *_registry_rows(
        "Valuation",
        "pe ev_ebitda ev_sales ev_ebit p_fcf pb ps earnings_yield fcf_yield dividend_yield",
    ),
    *_registry_rows(
        "Profitability",
        "gross_margin operating_margin ebitda_margin net_margin fcf_margin roe roic",
    ),
    *_registry_rows("Solvency", "net_debt_to_ebitda debt_to_equity interest_coverage"),
    *_registry_rows("Efficiency", "asset_turnover ccc"),
    CompsRowDef("revenue_growth", "Revenue growth (TTM YoY)", "Growth", "pct"),
)


@dataclass(frozen=True)
class CompanyFigures:
    """One company's comparable numbers by row code, and the caveat text it has per code."""

    ticker: str
    values: Mapping[str, Decimal | None]
    caveats: Mapping[str, str]


@dataclass(frozen=True)
class CellCaveat:
    ticker: str
    text: str


@dataclass(frozen=True)
class CompsRow:
    code: str
    label: str
    category: CompsCategory
    unit: Unit
    target: Decimal | None
    peers: list[Decimal | None]  # in the order the peers were given
    peer_median: Decimal | None
    peer_min: Decimal | None
    peer_max: Decimal | None
    n: int  # peer values used by the statistics
    target_vs_median: Decimal | None
    target_rank: int | None  # 1 = highest
    caveats: list[CellCaveat]  # target first, then peers in order


@dataclass(frozen=True)
class CompsTable:
    rows: list[CompsRow]


def compare(
    target: CompanyFigures,
    peers: Sequence[CompanyFigures],
    rows: Sequence[CompsRowDef] = COMPS_ROWS,
) -> CompsTable:
    """One row per `rows` entry. Peer statistics leave out nulls and, for an `x` row, values <= 0
    (such a value is still listed in `peers`); `n` counts the values used and is 0 when none is
    (the statistics are then null). `target_vs_median` is target / median - 1 for `x` and `days`
    rows (null when the median is <= 0) and target - median for `pct` rows; `target_rank` is 1 +
    the used peer values strictly above the target. Every number is quantized to 6 places."""
    return CompsTable([_row(d, target, peers) for d in rows])


def _row(d: CompsRowDef, target: CompanyFigures, peers: Sequence[CompanyFigures]) -> CompsRow:
    mine = _q(target.values.get(d.code))
    listed = [_q(p.values.get(d.code)) for p in peers]
    used = [v for v in listed if v is not None and (d.unit != "x" or v > 0)]
    mid = _q(median(used)) if used else None
    return CompsRow(
        code=d.code,
        label=d.label,
        category=d.category,
        unit=d.unit,
        target=mine,
        peers=listed,
        peer_median=mid,
        peer_min=min(used) if used else None,
        peer_max=max(used) if used else None,
        n=len(used),
        target_vs_median=_vs_median(d.unit, mine, mid),
        target_rank=None if mine is None else 1 + sum(v > mine for v in used),
        caveats=[
            CellCaveat(c.ticker, c.caveats[d.code]) for c in (target, *peers) if d.code in c.caveats
        ],
    )


def _vs_median(unit: Unit, target: Decimal | None, mid: Decimal | None) -> Decimal | None:
    if target is None or mid is None:
        return None
    if unit == "pct":
        return _q(target - mid)
    if mid <= 0:
        return None
    return _q(target / mid - 1)


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(RATIO_PLACES)
