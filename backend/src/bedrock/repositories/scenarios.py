from collections.abc import Collection, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import Scenario
from bedrock.repositories.numeric import plain


def list_for(session: Session, company_id: int) -> list[Scenario]:
    """The company's scenarios, Base first, then by id."""
    stmt = (
        select(Scenario)
        .where(Scenario.company_id == company_id)
        .order_by(Scenario.is_default.desc(), Scenario.id)
    )
    return list(session.execute(stmt).scalars())


def get(session: Session, company_id: int, scenario_id: int) -> Scenario | None:
    """The scenario, only when it belongs to the company."""
    stmt = select(Scenario).where(Scenario.company_id == company_id, Scenario.id == scenario_id)
    return session.execute(stmt).scalar_one_or_none()


def add(session: Session, scenario: Scenario) -> Scenario:
    """Adds and flushes (no commit)."""
    session.add(scenario)
    session.flush()
    return scenario


def delete_scenario(session: Session, scenario: Scenario) -> None:
    """Deletes the scenario and its driver rows, and flushes (no commit)."""
    session.execute(delete(DriverValue).where(DriverValue.scenario_id == scenario.id))
    session.delete(scenario)
    session.flush()


def list_rows(session: Session, scenario_ids: Collection[int]) -> list[DriverValue]:
    """Every driver row of the given scenarios in one query, with plain-decimal values
    (`repositories/numeric.py::plain`)."""
    if not scenario_ids:
        return []
    stmt = (
        select(DriverValue)
        .where(DriverValue.scenario_id.in_(scenario_ids))
        .order_by(DriverValue.scenario_id, DriverValue.driver_code, DriverValue.fiscal_year)
    )
    found = list(session.execute(stmt).scalars())
    for row in found:
        # Not a change: the stored value is the same, only without Numeric's padding.
        set_committed_value(row, "value", plain(row.value))
    return found


def add_rows(session: Session, rows: Iterable[DriverValue]) -> None:
    """Adds and flushes (no commit)."""
    session.add_all(rows)
    session.flush()


def delete_rows(session: Session, scenario_id: int, codes: Collection[str]) -> None:
    """Deletes every row of the given drivers of the scenario, and flushes (no commit)."""
    if not codes:
        return
    session.execute(
        delete(DriverValue).where(
            DriverValue.scenario_id == scenario_id, DriverValue.driver_code.in_(codes)
        )
    )
    session.flush()
