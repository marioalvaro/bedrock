from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.scenarios import (
    DriverGridOut,
    DriversIn,
    ScenarioIn,
    ScenarioOut,
    ScenarioSettingsIn,
)
from bedrock.services import scenarios as service

router = APIRouter(tags=["scenarios"])


@router.get("/companies/{ticker}/scenarios")
def list_scenarios(
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> list[ScenarioOut]:
    return [ScenarioOut.from_model(s) for s in service.list_scenarios(session, company, now)]


@router.post("/companies/{ticker}/scenarios", status_code=201)
def create_scenario(
    body: ScenarioIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> ScenarioOut:
    return ScenarioOut.from_model(service.create_scenario(session, company, body.to_input(), now))


@router.put("/companies/{ticker}/scenarios/{scenario_id}")
def update_scenario(
    scenario_id: int,
    body: ScenarioSettingsIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> ScenarioOut:
    updated = service.update_scenario(session, company, scenario_id, body.to_input(), now)
    return ScenarioOut.from_model(updated)


@router.delete("/companies/{ticker}/scenarios/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_scenario(session, company, scenario_id)


@router.get("/companies/{ticker}/scenarios/{scenario_id}/drivers")
def get_drivers(
    scenario_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> DriverGridOut:
    return DriverGridOut.from_grid(service.driver_grid(session, company, scenario_id))


@router.put("/companies/{ticker}/scenarios/{scenario_id}/drivers")
def put_drivers(
    scenario_id: int,
    body: DriversIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> DriverGridOut:
    grid = service.put_drivers(session, company, scenario_id, body.to_input(), now)
    return DriverGridOut.from_grid(grid)
