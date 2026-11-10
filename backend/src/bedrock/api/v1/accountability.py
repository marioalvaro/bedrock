from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.accountability import (
    BacktestOut,
    SnapshotDetailOut,
    SnapshotIn,
    SnapshotListOut,
    SnapshotOut,
)
from bedrock.services import backtest as backtest_service
from bedrock.services import snapshots as snapshots_service

router = APIRouter(tags=["accountability"])


@router.post("/companies/{ticker}/scenarios/{scenario_id}/snapshots", status_code=201)
def create_snapshot(
    scenario_id: int,
    body: SnapshotIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> SnapshotOut:
    view = snapshots_service.create_snapshot(session, company, scenario_id, body.note, now)
    return SnapshotOut.from_view(view)


@router.get("/companies/{ticker}/snapshots")
def list_snapshots(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> SnapshotListOut:
    return SnapshotListOut.from_view(snapshots_service.list_view(session, company))


@router.get("/companies/{ticker}/snapshots/{snapshot_id}")
def get_snapshot(
    snapshot_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> SnapshotDetailOut:
    return SnapshotDetailOut.from_detail(snapshots_service.detail(session, company, snapshot_id))


@router.post("/companies/{ticker}/backtest")
def run_backtest(
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> BacktestOut:
    return BacktestOut.from_view(backtest_service.run_backtest(session, company, now))


@router.get("/companies/{ticker}/backtest")
def get_backtest(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> BacktestOut:
    return BacktestOut.from_view(backtest_service.backtest_view(session, company))
