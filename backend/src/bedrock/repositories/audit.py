from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.models.audit_log import AuditLog


def add_all(session: Session, rows: Iterable[AuditLog]) -> None:
    """Adds and flushes (no commit)."""
    session.add_all(rows)
    session.flush()


def page(
    session: Session, company_id: int, entity: str | None, limit: int, before_id: int | None
) -> list[AuditLog]:
    """At most `limit` of the company's rows, newest first, older than `before_id` when given."""
    stmt = select(AuditLog).where(AuditLog.company_id == company_id)
    if entity is not None:
        stmt = stmt.where(AuditLog.entity == entity)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    return list(session.execute(stmt.order_by(AuditLog.id.desc()).limit(limit)).scalars())


def get(session: Session, company_id: int, row_id: int) -> AuditLog | None:
    """The row, only when it belongs to the company."""
    stmt = select(AuditLog).where(AuditLog.company_id == company_id, AuditLog.id == row_id)
    return session.execute(stmt).scalar_one_or_none()


def set_rationale(session: Session, row: AuditLog, rationale: str | None) -> None:
    """The one update the table allows. Flushes (no commit)."""
    row.rationale = rationale
    session.flush()
