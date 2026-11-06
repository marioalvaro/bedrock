from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.models.scenario import Case
from bedrock.schemas.valuation import (
    SensitivityGridOut,
    TornadoOut,
    ValuationInputsIn,
    ValuationInputsOut,
    ValuationOut,
    ValuationSummaryOut,
)
from bedrock.services import sensitivity as sensitivity_service
from bedrock.services import valuation as service

router = APIRouter(tags=["valuation"])
CASE_PATH = "/companies/{ticker}/scenarios/{scenario_id}/cases/{case}"


@router.get(f"{CASE_PATH}/valuation-inputs")
def get_valuation_inputs(
    scenario_id: int,
    case: Case,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> ValuationInputsOut:
    return ValuationInputsOut.from_view(
        service.valuation_inputs(session, company, scenario_id, case)
    )


@router.put(f"{CASE_PATH}/valuation-inputs")
def put_valuation_inputs(
    scenario_id: int,
    case: Case,
    body: ValuationInputsIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> ValuationInputsOut:
    rows = [(r.code, r.value) for r in body.rows]
    view = service.put_valuation_inputs(session, company, scenario_id, case, rows, now)
    return ValuationInputsOut.from_view(view)


@router.post(f"{CASE_PATH}/valuation-inputs/reset")
def reset_valuation_inputs(
    scenario_id: int,
    case: Case,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> ValuationInputsOut:
    view = service.reset_valuation_inputs(session, company, scenario_id, case)
    return ValuationInputsOut.from_view(view)


@router.get(f"{CASE_PATH}/valuation")
def get_valuation(
    scenario_id: int,
    case: Case,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> ValuationOut:
    return ValuationOut.from_valuation(service.case_valuation(session, company, scenario_id, case))


@router.get("/companies/{ticker}/scenarios/{scenario_id}/valuation")
def get_valuation_summary(
    scenario_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> ValuationSummaryOut:
    return ValuationSummaryOut.from_summary(
        service.valuation_summary(session, company, scenario_id)
    )


@router.get(f"{CASE_PATH}/sensitivity/tornado")
def get_tornado(
    scenario_id: int,
    case: Case,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> TornadoOut:
    return TornadoOut.from_result(sensitivity_service.tornado(session, company, scenario_id, case))


@router.get(f"{CASE_PATH}/sensitivity/grid")
def get_sensitivity_grid(
    scenario_id: int,
    case: Case,
    x: str = Query(description="Sensitivity input code of the columns"),
    y: str = Query(description="Sensitivity input code of the rows"),
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> SensitivityGridOut:
    result = sensitivity_service.grid(session, company, scenario_id, case, x, y)
    return SensitivityGridOut.from_result(result)
