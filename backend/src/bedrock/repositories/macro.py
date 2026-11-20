from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.core.clock import naive_utc
from bedrock.models.macro import MacroObservation, MacroSeries
from bedrock.repositories.numeric import plain


def upsert(
    session: Session,
    series_id: str,
    title: str,
    frequency: str,
    source: str,
    rows: Sequence[tuple[date, Decimal]],
    fetched_at: datetime,
) -> int:
    """Store the series and its observations, a stored date taking the new value; returns how
    many dates were new."""
    at = naive_utc(fetched_at)
    series = session.get(MacroSeries, series_id)
    if series is None:
        series = MacroSeries(series_id=series_id, title=title, frequency=frequency, source=source)
        session.add(series)
    series.title, series.frequency, series.source, series.fetched_at = title, frequency, source, at
    session.flush()
    stmt = select(MacroObservation).where(MacroObservation.series_id == series_id)
    known = {row.date: row for row in session.execute(stmt).scalars()}
    added = 0
    for day, value in rows:
        if day in known:
            known[day].value = value
        else:
            session.add(MacroObservation(series_id=series_id, date=day, value=value))
            added += 1
    session.flush()
    return added


def observations(session: Session, series_id: str) -> list[tuple[date, Decimal]]:
    """Every `(date, value)` of the series, oldest first."""
    stmt = (
        select(MacroObservation.date, MacroObservation.value)
        .where(MacroObservation.series_id == series_id)
        .order_by(MacroObservation.date)
    )
    return [(row.date, plain(row.value)) for row in session.execute(stmt)]


def latest(session: Session, series_id: str) -> tuple[date, Decimal] | None:
    stmt = (
        select(MacroObservation.date, MacroObservation.value)
        .where(MacroObservation.series_id == series_id)
        .order_by(MacroObservation.date.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    return None if row is None else (row.date, plain(row.value))


def fetched_at(session: Session, series_id: str) -> datetime | None:
    series = session.get(MacroSeries, series_id)
    return None if series is None else series.fetched_at
