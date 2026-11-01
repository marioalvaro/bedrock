from collections.abc import Collection, Iterable
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import CASES, Scenario, ScenarioCase
from bedrock.repositories.numeric import plain


def list_for(session: Session, company_id: int) -> list[Scenario]:
    """The company's scenarios, the default first, then by id."""
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


def add_cases(session: Session, scenario: Scenario, stamp: datetime) -> dict[str, ScenarioCase]:
    """Gives the scenario its three cases and flushes (no commit)."""
    cases = {
        case: ScenarioCase(scenario_id=scenario.id, case=case, created_at=stamp, updated_at=stamp)
        for case in CASES
    }
    session.add_all(cases.values())
    session.flush()
    return cases


def cases_of(session: Session, scenario_id: int) -> dict[str, ScenarioCase]:
    """The scenario's cases by name (empty for an unknown or deleted scenario)."""
    stmt = select(ScenarioCase).where(ScenarioCase.scenario_id == scenario_id)
    return {c.case: c for c in session.execute(stmt).scalars()}


def delete_scenario(session: Session, scenario: Scenario) -> None:
    """Deletes the scenario, its cases and their driver rows, and flushes (no commit)."""
    case_ids = select(ScenarioCase.id).where(ScenarioCase.scenario_id == scenario.id)
    session.execute(delete(DriverValue).where(DriverValue.case_id.in_(case_ids)))
    session.execute(delete(ScenarioCase).where(ScenarioCase.scenario_id == scenario.id))
    session.delete(scenario)
    session.flush()


def list_rows(session: Session, case_ids: Collection[int]) -> list[DriverValue]:
    """Every driver row of the given cases in one query, with plain-decimal values
    (`repositories/numeric.py::plain`)."""
    if not case_ids:
        return []
    stmt = (
        select(DriverValue)
        .where(DriverValue.case_id.in_(case_ids))
        .order_by(DriverValue.case_id, DriverValue.driver_code, DriverValue.fiscal_year)
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


def delete_rows(session: Session, case_id: int, codes: Collection[str]) -> None:
    """Deletes every row of the given drivers of the case, and flushes (no commit)."""
    if not codes:
        return
    session.execute(
        delete(DriverValue).where(
            DriverValue.case_id == case_id, DriverValue.driver_code.in_(codes)
        )
    )
    session.flush()


def delete_all_rows(session: Session, case_id: int) -> None:
    """Deletes every driver row of the case, and flushes (no commit)."""
    session.execute(delete(DriverValue).where(DriverValue.case_id == case_id))
    session.flush()
