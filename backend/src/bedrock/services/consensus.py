"""Analyst consensus (docs/erd/analysis.md "Consensus guidance"): the daily refresh of Yahoo's
rows, their placement on the company's reported revenue, and the read-only `consensus` guidance
entries the refresh logs from them."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bedrock.analysis.consensus import ConsensusRow, EpsHistoryRow, place, place_history
from bedrock.core.clock import naive_utc
from bedrock.ingest.protocol import CompanyRef, ConsensusLike
from bedrock.models.company import Company
from bedrock.models.consensus_estimate import ConsensusEstimate
from bedrock.models.guidance import Guidance
from bedrock.repositories.numeric import plain
from bedrock.services.adjustments import AMOUNT_LIMIT
from bedrock.services.statements import statement_tables

# The basis each consensus metric is judged on: Yahoo's EPS is the street's adjusted figure, so
# normalized; revenue is as reported (user decision 2026-11-07).
BASIS = {"revenue": "reported", "eps_diluted": "normalized"}

_Annual = dict[int, Decimal]
_Quarterly = dict[tuple[int, str], Decimal]
_QuarterEnds = dict[tuple[int, str], date]

# How far back the earnings history is backfilled (user decision 2026-11-07: at most a year).
BACKFILL_WINDOW = timedelta(days=365)
HISTORY_NOTE = "Analyst consensus before the report (Yahoo earnings history, average)"


@dataclass(frozen=True)
class Estimate:
    metric: str  # revenue | eps_diluted
    fiscal_year: int
    fiscal_period: str  # FY | Q1..Q4
    low: Decimal
    avg: Decimal | None
    high: Decimal
    analysts: int | None
    as_of: date


def refresh_consensus(
    session: Session, source: ConsensusLike, company: Company, now: datetime
) -> int:
    """Replace the company's stored rows with a fresh fetch, log the placed estimates as
    consensus guidance (`log_guidance`), backfill the past year's quarterly EPS consensus
    (`backfill_guidance`) and commit; returns the row count. Raises SourceUnavailable when
    either call fails (the stored rows and entries are kept)."""
    ref = CompanyRef(company.ticker, company.cik)
    rows = source.fetch(ref)
    history = source.history(ref)
    at = naive_utc(now)
    session.execute(delete(ConsensusEstimate).where(ConsensusEstimate.company_id == company.id))
    for r in rows:
        session.add(
            ConsensusEstimate(
                company_id=company.id,
                period=r.period,
                metric=r.metric,
                low=r.low,
                avg=r.avg,
                high=r.high,
                analysts=r.analysts,
                year_ago_revenue=r.year_ago_revenue,
                fetched_at=at,
            )
        )
    session.flush()
    log_guidance(session, company, at)
    backfill_guidance(session, company, history, at)
    session.commit()
    return len(rows)


def backfill_guidance(
    session: Session, company: Company, history: list[EpsHistoryRow], at: datetime
) -> int:
    """Log each past quarter of Yahoo's earnings history that ended within `BACKFILL_WINDOW` of
    `at` as a point `eps_diluted` consensus entry (low = high = the average before the report,
    normalized basis, given on the fiscal quarter's end), unless its quarter already has a
    consensus entry. Flushes, no commit; returns the entries added."""
    _, _, quarter_ends = _reported(session, company)
    have = {
        (g.fiscal_year, g.fiscal_period)
        for g in session.execute(
            select(Guidance).where(
                Guidance.company_id == company.id,
                Guidance.source == "consensus",
                Guidance.metric == "eps_diluted",
            )
        ).scalars()
    }
    added = 0
    for p in place_history(history, quarter_ends, since=at.date() - BACKFILL_WINDOW):
        if (p.fiscal_year, p.fiscal_period) in have:
            continue
        if not (p.estimate.is_finite() and abs(p.estimate) < AMOUNT_LIMIT):
            continue
        session.add(
            Guidance(
                company_id=company.id,
                metric="eps_diluted",
                fiscal_year=p.fiscal_year,
                fiscal_period=p.fiscal_period,
                low=p.estimate,
                high=p.estimate,
                basis=BASIS["eps_diluted"],
                direction="higher",
                given_on=p.quarter_end,
                source_note=HISTORY_NOTE,
                source="consensus",
                created_at=at,
                updated_at=at,
            )
        )
        added += 1
    session.flush()
    return added


def log_guidance(session: Session, company: Company, at: datetime) -> int:
    """Log each placed estimate as a `consensus` guidance entry given on `at`'s date, unless its
    period is already reported or its range equals the latest consensus entry of its (metric,
    period). A changed range is a new revision, except that a second change on the same day
    replaces that day's entry. Flushes, no commit; returns the entries added or replaced."""
    estimates, annual, quarterly = _placed(session, company)
    today = at.date()
    latest: dict[tuple[str, int, str], Guidance] = {}
    for g in session.execute(
        select(Guidance).where(Guidance.company_id == company.id, Guidance.source == "consensus")
    ).scalars():
        key = (g.metric, g.fiscal_year, g.fiscal_period)
        if key not in latest or (g.given_on, g.id) > (latest[key].given_on, latest[key].id):
            latest[key] = g
    written = 0
    for e in estimates:
        reported = (
            e.fiscal_year in annual
            if e.fiscal_period == "FY"
            else (e.fiscal_year, e.fiscal_period) in quarterly
        )
        if reported or not all(v.is_finite() and abs(v) < AMOUNT_LIMIT for v in (e.low, e.high)):
            continue
        last = latest.get((e.metric, e.fiscal_year, e.fiscal_period))
        if last is not None and (last.low, last.high) == (e.low, e.high):
            continue
        if last is not None and last.given_on == today:
            last.low, last.high, last.source_note, last.updated_at = e.low, e.high, note(e), at
        else:
            session.add(
                Guidance(
                    company_id=company.id,
                    metric=e.metric,
                    fiscal_year=e.fiscal_year,
                    fiscal_period=e.fiscal_period,
                    low=e.low,
                    high=e.high,
                    basis=BASIS[e.metric],
                    direction="higher",
                    given_on=today,
                    source_note=note(e),
                    source="consensus",
                    created_at=at,
                    updated_at=at,
                )
            )
        written += 1
    session.flush()
    return written


def note(e: Estimate) -> str:
    """The source note of a consensus entry: "Analyst consensus (Yahoo, 37 analysts, as of
    2026-11-07)", without the analysts when Yahoo gives no count."""
    analysts = "" if e.analysts is None else f"{e.analysts} analysts, "
    return f"Analyst consensus (Yahoo, {analysts}as of {e.as_of.isoformat()})"


def consensus(session: Session, company: Company) -> list[Estimate]:
    """The stored rows placed on fiscal periods, FY first then quarters, by period."""
    return _placed(session, company)[0]


def _placed(session: Session, company: Company) -> tuple[list[Estimate], _Annual, _Quarterly]:
    """The placed estimates, with the reported annual and quarterly revenue they were placed by
    (empty when nothing is stored)."""
    stored = (
        session.execute(select(ConsensusEstimate).where(ConsensusEstimate.company_id == company.id))
        .scalars()
        .all()
    )
    if not stored:
        return [], {}, {}
    rows = [
        ConsensusRow(
            s.period,
            s.metric,
            _plain(s.low),
            _plain(s.avg),
            _plain(s.high),
            s.analysts,
            _plain(s.year_ago_revenue),
        )
        for s in stored
    ]
    annual, quarterly, _ = _reported(session, company)
    as_of = max(s.fetched_at for s in stored).date()
    placed = place(rows, annual, quarterly)
    estimates = sorted(
        (
            Estimate(
                p.metric, p.fiscal_year, p.fiscal_period, p.low, p.avg, p.high, p.analysts, as_of
            )
            for p in placed
        ),
        key=lambda e: (e.fiscal_period != "FY", e.fiscal_year, e.fiscal_period, e.metric),
    )
    return estimates, annual, quarterly


def _reported(session: Session, company: Company) -> tuple[_Annual, _Quarterly, _QuarterEnds]:
    """The reported revenue by fiscal year and by quarter, and each reported quarter's end."""
    tables = statement_tables(session, company, [("IS", "annual"), ("IS", "quarterly")])
    annual: _Annual = {}
    quarterly: _Quarterly = {}
    ends: _QuarterEnds = {}
    for (_, freq), table in tables.items():
        row = table.row("revenue")
        if row is None:
            continue
        for period, value in zip(table.periods, row.values, strict=True):
            if value is None or period.key.startswith("TTM"):
                continue
            if freq == "annual" and period.fiscal_period == "FY":
                annual[period.fiscal_year] = value
            elif freq == "quarterly" and period.fiscal_period.startswith("Q"):
                quarterly[period.point] = value
                ends[period.point] = period.end
    return annual, quarterly, ends


def _plain(value: Decimal | None) -> Decimal | None:
    return None if value is None else plain(value)
