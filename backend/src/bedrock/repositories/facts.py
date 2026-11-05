from collections.abc import Collection, Iterable
from datetime import date
from decimal import Decimal
from typing import Any, NamedTuple

import pandas as pd
from sqlalchemy import Select, insert, select, tuple_
from sqlalchemy.orm import Session

from bedrock.ingest.parse import ParsedFacts
from bedrock.mapping.mapper import CANONICAL_COLUMNS
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.models.raw_fact import RawFact
from bedrock.repositories.numeric import plain

FACT_COLUMNS = [
    "taxonomy",
    "concept",
    "unit",
    "period_start",
    "period_end",
    "value",
    "accession_no",
    "form",
    "filed_at",
]

_FactKey = tuple[int, str, str, str, date | None, date]


def insert_parsed(session: Session, company: Company, parsed: ParsedFacts) -> tuple[int, int]:
    """Append the filings and facts not stored yet; returns (new_filings, new_facts).

    SQLite's UNIQUE treats NULLs as distinct, so a fact with no `period_start` (an instant)
    is compared against the stored keys here instead of relying on the constraint."""
    stmt = select(Filing.accession_no, Filing.id).where(Filing.company_id == company.id)
    filing_ids = {accession: id_ for accession, id_ in session.execute(stmt)}

    new_filings = [f for f in parsed.filings if f.accession_no not in filing_ids]
    for filing in new_filings:
        row = Filing(
            company_id=company.id,
            accession_no=filing.accession_no,
            form=filing.form,
            filed_at=filing.filed_at,
            fiscal_year=filing.fiscal_year,
            fiscal_period=filing.fiscal_period,
            period_end=filing.period_end,
        )
        session.add(row)
        session.flush()
        filing_ids[filing.accession_no] = row.id

    known = _stored_keys(session, company.id, {filing_ids[f.accession_no] for f in parsed.facts})
    rows: list[dict[str, object]] = []
    for fact in parsed.facts:
        filing_id = filing_ids[fact.accession_no]
        key = (
            filing_id,
            fact.taxonomy,
            fact.concept,
            fact.unit,
            fact.period_start,
            fact.period_end,
        )
        if key in known:
            continue
        known.add(key)
        rows.append(
            {
                "company_id": company.id,
                "filing_id": filing_id,
                "taxonomy": fact.taxonomy,
                "concept": fact.concept,
                "unit": fact.unit,
                "period_start": fact.period_start,
                "period_end": fact.period_end,
                "fiscal_year": fact.fiscal_year,
                "fiscal_period": fact.fiscal_period,
                "frame": fact.frame,
                "value": fact.value,
            }
        )
    if rows:
        # Through the connection (Core), not the session's ORM bulk path: that one splits the
        # batch wherever a row has a NULL the next does not (instants, no frame), turning ~60k
        # rows into ~12k statements.
        session.connection().execute(insert(RawFact), rows)
    return len(new_filings), len(rows)


def _stored_keys(session: Session, company_id: int, filing_ids: Collection[int]) -> set[_FactKey]:
    stmt = select(
        RawFact.filing_id,
        RawFact.taxonomy,
        RawFact.concept,
        RawFact.unit,
        RawFact.period_start,
        RawFact.period_end,
    ).where(RawFact.company_id == company_id, RawFact.filing_id.in_(filing_ids))
    return {(r[0], r[1], r[2], r[3], r[4], r[5]) for r in session.execute(stmt)}


def load_facts(
    session: Session, company_id: int, concepts: Collection[tuple[str, str]]
) -> pd.DataFrame:
    """Every vintage of the given (taxonomy, concept) pairs, joined to its filing."""
    if not concepts:
        return _frame([])
    stmt = _joined().where(
        RawFact.company_id == company_id,
        tuple_(RawFact.taxonomy, RawFact.concept).in_(sorted(concepts)),
    )
    return _frame(session.execute(stmt).all())


def load_latest_annual_facts(session: Session, company_id: int) -> pd.DataFrame:
    """Every fact of the company's newest 10-K (any concept), for the unmapped-concepts report."""
    newest = (
        select(Filing.id)
        .where(Filing.company_id == company_id, Filing.form.like("10-K%"))
        .order_by(Filing.filed_at.desc(), Filing.accession_no.desc())
        .limit(1)
    )
    filing_id = session.execute(newest).scalar_one_or_none()
    if filing_id is None:
        return _frame([])
    return _frame(session.execute(_joined().where(RawFact.filing_id == filing_id)).all())


def load_cover_shares(session: Session, company_id: int) -> pd.DataFrame:
    """The cover-page share counts (`dei:EntityCommonStockSharesOutstanding`) in the canonical
    frame's shape, as `shares_outstanding` instants. A cover fact is dated weeks after the period
    it sits in, so each is dated on the period its filing reports (`Filing.period_end`). The
    caller split-adjusts it like any share count."""
    stmt = (
        select(
            RawFact.taxonomy,
            RawFact.concept,
            RawFact.unit,
            Filing.period_end,
            RawFact.value,
            Filing.accession_no,
            Filing.form,
            Filing.filed_at,
        )
        .join(Filing, Filing.id == RawFact.filing_id)
        .where(
            RawFact.company_id == company_id,
            RawFact.taxonomy == "dei",
            RawFact.concept == "EntityCommonStockSharesOutstanding",
            RawFact.unit == "shares",
        )
    )
    records = [
        (
            "shares_outstanding",
            None,
            r[3],
            plain(r[4]),
            r[0],
            r[1],
            r[2],
            r[5],
            r[6],
            r[7],
            "instant",
        )
        for r in session.execute(stmt)
    ]
    return pd.DataFrame(records, columns=CANONICAL_COLUMNS).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )


class SharesOutstanding(NamedTuple):
    value: Decimal
    filed_at: date  # the filing that stated it: splits after this date change its meaning


def latest_shares_outstanding(session: Session, company_id: int) -> SharesOutstanding | None:
    """`dei:EntityCommonStockSharesOutstanding`: the newest filed value at the latest `end`."""
    stmt = (
        select(RawFact.value, Filing.filed_at)
        .join(Filing, Filing.id == RawFact.filing_id)
        .where(
            RawFact.company_id == company_id,
            RawFact.taxonomy == "dei",
            RawFact.concept == "EntityCommonStockSharesOutstanding",
            RawFact.unit == "shares",
        )
        .order_by(RawFact.period_end.desc(), Filing.filed_at.desc(), Filing.accession_no.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    return None if row is None else SharesOutstanding(plain(row[0]), row[1])


def _joined() -> Select[str, str, str, date | None, date, Decimal, str, str, date]:
    return select(
        RawFact.taxonomy,
        RawFact.concept,
        RawFact.unit,
        RawFact.period_start,
        RawFact.period_end,
        RawFact.value,
        Filing.accession_no,
        Filing.form,
        Filing.filed_at,
    ).join(Filing, Filing.id == RawFact.filing_id)


def _frame(rows: Iterable[Any]) -> pd.DataFrame:
    records = [(r[0], r[1], r[2], r[3], r[4], plain(r[5]), r[6], r[7], r[8]) for r in rows]
    return pd.DataFrame(records, columns=FACT_COLUMNS).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )
