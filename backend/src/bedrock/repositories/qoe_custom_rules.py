from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.qoe_custom_rule import QoeCustomRule
from bedrock.repositories.numeric import plain


def list_all(session: Session) -> list[QoeCustomRule]:
    """Every custom rule in id order, with plain-decimal levels (`repositories/numeric.py::plain`;
    a None level stays None)."""
    stmt = select(QoeCustomRule).order_by(QoeCustomRule.id)
    return [_plain_levels(r) for r in session.execute(stmt).scalars()]


def get(session: Session, rule_id: int) -> QoeCustomRule | None:
    """The custom rule with plain-decimal levels, or None."""
    found = session.get(QoeCustomRule, rule_id)
    return None if found is None else _plain_levels(found)


def add(session: Session, rule: QoeCustomRule) -> QoeCustomRule:
    """Adds and flushes (no commit)."""
    session.add(rule)
    session.flush()
    return _plain_levels(rule)


def delete(session: Session, rule: QoeCustomRule) -> None:
    """Deletes and flushes (no commit)."""
    session.delete(rule)
    session.flush()


def _plain_levels(rule: QoeCustomRule) -> QoeCustomRule:
    # Not a change: the stored values are the same, only without Numeric's padding.
    set_committed_value(rule, "warn", _plain_or_none(rule.warn))
    set_committed_value(rule, "alert", _plain_or_none(rule.alert))
    return rule


def _plain_or_none(value: Decimal | None) -> Decimal | None:
    return None if value is None else plain(value)
