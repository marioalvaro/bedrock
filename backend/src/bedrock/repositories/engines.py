from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.models.driver_engine import DriverEngineChoice


def list_for(session: Session, scenario_id: int) -> list[DriverEngineChoice]:
    """The scenario's stored engine choices, by driver code."""
    stmt = (
        select(DriverEngineChoice)
        .where(DriverEngineChoice.scenario_id == scenario_id)
        .order_by(DriverEngineChoice.driver_code)
    )
    return list(session.execute(stmt).scalars())


def put(
    session: Session, scenario_id: int, choices: Mapping[str, str | None], stamp: datetime
) -> None:
    """Per driver code: an engine code inserts or updates the scenario's row, None (`auto`)
    deletes it. Flushes (no commit)."""
    stored = {r.driver_code: r for r in list_for(session, scenario_id)}
    for code, engine in choices.items():
        row = stored.get(code)
        if engine is None:
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(
                DriverEngineChoice(
                    scenario_id=scenario_id, driver_code=code, engine_code=engine, updated_at=stamp
                )
            )
        elif row.engine_code != engine:
            row.engine_code = engine
            row.updated_at = stamp
    session.flush()
