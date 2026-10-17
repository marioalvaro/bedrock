from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.schemas.qoe import QoeRuleOut, QoeThresholdsIn
from bedrock.services import qoe as service

router = APIRouter(tags=["qoe-rules"])


@router.get("/qoe-rules")
def list_qoe_rules(session: Session = Depends(get_session)) -> list[QoeRuleOut]:
    return [QoeRuleOut.from_setting(s) for s in service.list_rules(session)]


@router.put("/qoe-rules/{code}")
def set_qoe_thresholds(
    code: str,
    body: QoeThresholdsIn,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> QoeRuleOut:
    return QoeRuleOut.from_setting(service.set_thresholds(session, code, body.to_thresholds(), now))


@router.delete("/qoe-rules/{code}", status_code=204)
def reset_qoe_thresholds(code: str, session: Session = Depends(get_session)) -> None:
    service.reset(session, code)
