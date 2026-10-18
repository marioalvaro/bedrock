from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.qoe_threshold import QoeThreshold
from bedrock.repositories.numeric import plain


def list_all(session: Session) -> list[QoeThreshold]:
    """Every override, by rule code, with plain-decimal levels (`repositories/numeric.py::plain`;
    a None level stays None)."""
    stmt = select(QoeThreshold).order_by(QoeThreshold.rule_code)
    return [_plain_levels(t) for t in session.execute(stmt).scalars()]


def get(session: Session, rule_code: str) -> QoeThreshold | None:
    """The override of the rule, with plain-decimal levels, or None."""
    stmt = select(QoeThreshold).where(QoeThreshold.rule_code == rule_code)
    found = session.execute(stmt).scalar_one_or_none()
    return None if found is None else _plain_levels(found)


def add(session: Session, threshold: QoeThreshold) -> QoeThreshold:
    """Adds and flushes (no commit)."""
    session.add(threshold)
    session.flush()
    return _plain_levels(threshold)


def delete(session: Session, threshold: QoeThreshold) -> None:
    """Deletes and flushes (no commit)."""
    session.delete(threshold)
    session.flush()


def _plain_levels(threshold: QoeThreshold) -> QoeThreshold:
    # Not a change: the stored values are the same, only without Numeric's padding.
    set_committed_value(threshold, "warn", _plain_or_none(threshold.warn))
    set_committed_value(threshold, "alert", _plain_or_none(threshold.alert))
    return threshold


def _plain_or_none(value: Decimal | None) -> Decimal | None:
    return None if value is None else plain(value)
