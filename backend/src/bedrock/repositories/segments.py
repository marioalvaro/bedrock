from collections.abc import Collection

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.segment_series import SegmentSeries
from bedrock.models.segment_value import SegmentValue
from bedrock.repositories.numeric import plain


def list_series(session: Session, company_id: int) -> list[SegmentSeries]:
    """The company's series by display order, then id."""
    stmt = (
        select(SegmentSeries)
        .where(SegmentSeries.company_id == company_id)
        .order_by(SegmentSeries.display_order, SegmentSeries.id)
    )
    return list(session.execute(stmt).scalars())


def get_series(session: Session, company_id: int, series_id: int) -> SegmentSeries | None:
    """The series, only when it belongs to the company."""
    stmt = select(SegmentSeries).where(
        SegmentSeries.company_id == company_id, SegmentSeries.id == series_id
    )
    return session.execute(stmt).scalar_one_or_none()


def max_display_order(session: Session, company_id: int) -> int:
    """The company's highest display order (0 without series)."""
    stmt = select(func.max(SegmentSeries.display_order)).where(
        SegmentSeries.company_id == company_id
    )
    return session.execute(stmt).scalar_one() or 0


def add_series(session: Session, series: SegmentSeries) -> SegmentSeries:
    """Adds and flushes (no commit)."""
    session.add(series)
    session.flush()
    return series


def delete_series(session: Session, series: SegmentSeries) -> None:
    """Deletes the series and its values, and flushes (no commit)."""
    session.execute(delete(SegmentValue).where(SegmentValue.series_id == series.id))
    session.delete(series)
    session.flush()


def list_values(session: Session, series_ids: Collection[int]) -> list[SegmentValue]:
    """Every value of the given series in one query, with plain-decimal values
    (`repositories/numeric.py::plain`)."""
    if not series_ids:
        return []
    stmt = (
        select(SegmentValue)
        .where(SegmentValue.series_id.in_(series_ids))
        .order_by(SegmentValue.series_id, SegmentValue.fiscal_year, SegmentValue.id)
    )
    found = list(session.execute(stmt).scalars())
    for v in found:
        # Not a change: the stored value is the same, only without Numeric's padding.
        set_committed_value(v, "value", plain(v.value))
    return found


def add_value(session: Session, value: SegmentValue) -> SegmentValue:
    """Adds and flushes (no commit)."""
    session.add(value)
    session.flush()
    return value


def delete_value(session: Session, value: SegmentValue) -> None:
    """Deletes and flushes (no commit)."""
    session.delete(value)
    session.flush()
