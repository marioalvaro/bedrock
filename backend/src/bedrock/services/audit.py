"""The assumption audit trail: recording changed fields and reading them back (FR-ACC-04; docs/erd/
accountability.md "Audit trail"). Imports no other service: every audited writer calls it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from bedrock.backtest.audit import changes
from bedrock.models.audit_log import AuditLog
from bedrock.models.company import Company
from bedrock.repositories import audit as repo
from bedrock.services.errors import AuditRowNotFound, InvalidAuditRow

RATIONALE_LIMIT = 500

Describe = Callable[[str], tuple[str, str | None]]


@dataclass(frozen=True)
class AuditPage:
    rows: list[AuditLog]
    next_before_id: int | None


def case_scope(scenario_name: str, case: str) -> str:
    """The `scope` of a row about one case: "Main · Bull"."""
    return f"{scenario_name} · {case.capitalize()}"


def record(
    session: Session,
    company_id: int,
    entity: str,
    entity_id: int,
    scope: str | None,
    action: str,
    before: Mapping[str, str | None],
    after: Mapping[str, str | None],
    describe: Describe,
    stamp: datetime,
    rationale: str | None = None,
) -> int:
    """Adds one row per field that differs between `before` and `after`, in field order, and
    returns how many. `describe(field)` gives its (label, unit). Flushes, does not commit: the
    caller's transaction holds the change and its rows together."""
    found = changes(before, after)
    repo.add_all(
        session,
        [
            AuditLog(
                company_id=company_id,
                entity=entity,
                entity_id=entity_id,
                scope=scope,
                field=change.field,
                label=describe(change.field)[0],
                unit=describe(change.field)[1],
                old_value=change.old,
                new_value=change.new,
                action=action,
                rationale=rationale,
                changed_at=stamp,
            )
            for change in found
        ],
    )
    return len(found)


def page_view(
    session: Session, company: Company, entity: str | None, limit: int, before_id: int | None
) -> AuditPage:
    """A page of the company's rows, newest first; `next_before_id` is set when more remain."""
    rows = repo.page(session, company.id, entity, limit + 1, before_id)
    if len(rows) <= limit:
        return AuditPage(rows, None)
    shown = rows[:limit]
    return AuditPage(shown, shown[-1].id)


def set_rationale(
    session: Session, company: Company, row_id: int, rationale: str | None
) -> AuditLog:
    """Sets the row's rationale; blank clears it. Raises AuditRowNotFound (another company's row
    counts as unknown) and InvalidAuditRow."""
    clean = (rationale or "").strip()
    if len(clean) > RATIONALE_LIMIT:
        raise InvalidAuditRow(f"The rationale must be at most {RATIONALE_LIMIT} characters")
    row = repo.get(session, company.id, row_id)
    if row is None:
        raise AuditRowNotFound(str(row_id))
    repo.set_rationale(session, row, clean or None)
    session.commit()
    return row
