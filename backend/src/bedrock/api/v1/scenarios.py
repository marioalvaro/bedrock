import re
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.forecast.driver_io import DriverFileIssue
from bedrock.models.company import Company
from bedrock.models.scenario import Case
from bedrock.schemas.scenarios import (
    DriverFileErrorsOut,
    DriverGridOut,
    DriverImportOut,
    DriversIn,
    ScenarioIn,
    ScenarioOut,
    ScenarioSettingsIn,
)
from bedrock.services import scenarios as service
from bedrock.services.errors import InvalidDriverFile

router = APIRouter(tags=["scenarios"])

MAX_BYTES = 1024 * 1024  # a driver file is a few kB
_MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]")


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


@router.get("/companies/{ticker}/scenarios/{scenario_id}/cases/{case}/drivers")
def get_drivers(
    scenario_id: int,
    case: Case,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> DriverGridOut:
    return DriverGridOut.from_grid(service.driver_grid(session, company, scenario_id, case))


@router.put("/companies/{ticker}/scenarios/{scenario_id}/cases/{case}/drivers")
def put_drivers(
    scenario_id: int,
    case: Case,
    body: DriversIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> DriverGridOut:
    grid = service.put_drivers(session, company, scenario_id, case, body.to_input(), now)
    return DriverGridOut.from_grid(grid)


@router.post("/companies/{ticker}/scenarios/{scenario_id}/cases/{case}/reset")
def reset_case(
    scenario_id: int,
    case: Case,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> DriverGridOut:
    return DriverGridOut.from_grid(service.reset_case(session, company, scenario_id, case, now))


@router.get("/companies/{ticker}/scenarios/{scenario_id}/cases/{case}/drivers/export")
def export_drivers(
    scenario_id: int,
    case: Case,
    format: Literal["csv", "xlsx"] = "csv",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> Response:
    content, name = service.export_drivers(session, company, scenario_id, case, format)
    return Response(
        content, media_type=_MEDIA[format], headers={"Content-Disposition": _attachment(name)}
    )


@router.post(
    "/companies/{ticker}/scenarios/{scenario_id}/cases/{case}/drivers/import",
    responses={422: {"model": DriverFileErrorsOut}},
)
def import_drivers(
    scenario_id: int,
    case: Case,
    file: UploadFile = File(),
    dry_run: bool = Form(False),
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> DriverImportOut:
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise InvalidDriverFile([DriverFileIssue(None, None, "The file is larger than 1 MB")])
    result = service.import_drivers(
        session, company, scenario_id, case, content, file.filename or "drivers", dry_run, now
    )
    return DriverImportOut.from_result(result, dry_run)


def _attachment(name: str) -> str:
    """An attachment header: an ASCII `filename` with unsafe characters as `_` (a scenario name
    is free text) and the exact name as RFC 5987 `filename*`."""
    ascii_name = _UNSAFE.sub("_", name)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
