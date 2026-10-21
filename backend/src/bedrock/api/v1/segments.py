from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.segments import (
    ImportErrorOut,
    SegmentImportIn,
    SegmentImportOut,
    SegmentSeriesIn,
    SegmentSeriesOut,
    SegmentSeriesUpdate,
    SegmentsOut,
    SegmentValuesIn,
)
from bedrock.services import segments as service

router = APIRouter(tags=["segments"])


@router.get("/companies/{ticker}/segments")
def get_segments(
    freq: Literal["annual", "quarterly"] = "annual",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> SegmentsOut:
    return SegmentsOut.from_grid(service.segment_grid(session, company, freq), company.ticker)


@router.post("/companies/{ticker}/segment-series", status_code=201)
def create_series(
    body: SegmentSeriesIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> SegmentSeriesOut:
    data = service.SeriesInput(body.dimension, body.name, body.metric, body.unit)
    return SegmentSeriesOut.from_model(service.create_series(session, company, data, now))


@router.put("/companies/{ticker}/segment-series/{series_id}")
def update_series(
    series_id: int,
    body: SegmentSeriesUpdate,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> SegmentSeriesOut:
    return SegmentSeriesOut.from_model(
        service.update_series(session, company, series_id, body.name, body.display_order, now)
    )


@router.delete("/companies/{ticker}/segment-series/{series_id}", status_code=204)
def delete_series(
    series_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_series(session, company, series_id)


@router.put("/companies/{ticker}/segment-series/{series_id}/values")
def set_values(
    series_id: int,
    body: SegmentValuesIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> SegmentSeriesOut:
    values = [service.ValueInput(v.fiscal_year, v.fiscal_period, v.value) for v in body.values]
    return SegmentSeriesOut.from_model(service.set_values(session, company, series_id, values, now))


@router.post(
    "/companies/{ticker}/segments/import",
    responses={422: {"model": ImportErrorOut}},
)
def import_segments(
    body: SegmentImportIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> SegmentImportOut:
    result = service.import_segments(session, company, body.dimension, body.text, body.scale, now)
    return SegmentImportOut(
        series_created=result.series_created,
        values_created=result.values_created,
        values_updated=result.values_updated,
    )
