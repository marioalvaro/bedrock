"""Helpers for the accountability API tests: filings that have not landed yet."""

from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from bedrock.models.filing import Filing
from bedrock.models.raw_fact import RawFact


def withhold_filings(session: Session, after: date) -> Callable[[], None]:
    """Deletes every filing filed after `after` and its facts, and returns the function that puts
    them back: a test snapshots "before" and then lets the actuals land."""
    filings: list[dict[str, Any]] = [
        dict(row)
        for row in session.execute(
            select(Filing.__table__).where(Filing.filed_at > after)
        ).mappings()
    ]
    ids = [row["id"] for row in filings]
    facts: list[dict[str, Any]] = [
        dict(row)
        for row in session.execute(
            select(RawFact.__table__).where(RawFact.filing_id.in_(ids))
        ).mappings()
    ]
    session.execute(delete(RawFact).where(RawFact.filing_id.in_(ids)))
    session.execute(delete(Filing).where(Filing.id.in_(ids)))
    session.commit()

    def restore() -> None:
        session.execute(insert(Filing.__table__), filings)
        session.execute(insert(RawFact.__table__), facts)
        session.commit()

    return restore
