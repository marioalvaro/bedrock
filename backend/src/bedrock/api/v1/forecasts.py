from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.forecasts import CompareOut, ForecastOut
from bedrock.services import forecasts as service

# Included before the scenarios router, so /scenarios/compare is not read as /scenarios/{id}.
router = APIRouter(tags=["forecasts"])


@router.get("/companies/{ticker}/scenarios/compare")
def compare_scenarios(
    freq: Literal["annual", "quarterly"] = Query(),
    codes: str | None = Query(default=None, description="Comma-separated line item codes"),
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> CompareOut:
    wanted = None if codes is None else [c.strip() for c in codes.split(",") if c.strip()]
    return CompareOut.from_comparison(service.compare(session, company, freq, wanted, now))


@router.get("/companies/{ticker}/scenarios/{scenario_id}/forecast")
def get_forecast(
    scenario_id: int,
    statement: Literal["IS", "BS", "CF"] = Query(alias="type"),
    freq: Literal["annual", "quarterly"] = Query(),
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> ForecastOut:
    forecast = service.forecast_table(session, company, scenario_id, statement, freq)
    return ForecastOut.from_forecast(
        forecast,
        ticker=company.ticker,
        statement=statement,
        freq=freq,
        currency=company.currency,
        scenario_id=scenario_id,
    )
