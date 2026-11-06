from collections.abc import Collection, Mapping
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bedrock.models.valuation_input import ValuationInput


def list_rows(session: Session, case_ids: Collection[int]) -> list[ValuationInput]:
    """Every stored input of the given cases in one query."""
    if not case_ids:
        return []
    stmt = (
        select(ValuationInput)
        .where(ValuationInput.case_id.in_(case_ids))
        .order_by(ValuationInput.case_id, ValuationInput.code)
    )
    return list(session.execute(stmt).scalars())


def put_rows(
    session: Session, case_id: int, values: Mapping[str, str | None], stamp: datetime
) -> None:
    """Per code: a text inserts or updates the case's row, None deletes it. Flushes (no commit)."""
    stored = {r.code: r for r in list_rows(session, [case_id])}
    for code, value in values.items():
        row = stored.get(code)
        if value is None:
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(ValuationInput(case_id=case_id, code=code, value=value, updated_at=stamp))
        elif row.value != value:
            row.value = value
            row.updated_at = stamp
    session.flush()


def delete_all(session: Session, case_id: int) -> None:
    """Deletes every stored input of the case. Flushes (no commit)."""
    session.execute(delete(ValuationInput).where(ValuationInput.case_id == case_id))
    session.flush()
