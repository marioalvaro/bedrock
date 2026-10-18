from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.schemas.qoe import QoeCustomRuleIn, QoeCustomRuleOut, QoeRuleOut, QoeThresholdsIn
from bedrock.services import qoe as service

router = APIRouter(tags=["qoe-rules"])
# CRUD of /qoe-custom-rules (FR-ANL-10)
custom_router = APIRouter(tags=["qoe-custom-rules"])


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
    warn, alert = body.level_texts()
    return QoeRuleOut.from_setting(service.set_thresholds(session, code, warn, alert, now))


@router.delete("/qoe-rules/{code}", status_code=204)
def reset_qoe_thresholds(code: str, session: Session = Depends(get_session)) -> None:
    service.reset(session, code)


@custom_router.get("/qoe-custom-rules")
def list_custom_rules(session: Session = Depends(get_session)) -> list[QoeCustomRuleOut]:
    return [QoeCustomRuleOut.from_view(v) for v in service.list_custom_rules(session)]


@custom_router.post("/qoe-custom-rules", status_code=201)
def create_custom_rule(
    body: QoeCustomRuleIn,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> QoeCustomRuleOut:
    return QoeCustomRuleOut.from_view(service.create_custom_rule(session, body.to_input(), now))


@custom_router.put("/qoe-custom-rules/{rule_id}")
def update_custom_rule(
    rule_id: int,
    body: QoeCustomRuleIn,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> QoeCustomRuleOut:
    view = service.update_custom_rule(session, rule_id, body.to_input(), now)
    return QoeCustomRuleOut.from_view(view)


@custom_router.delete("/qoe-custom-rules/{rule_id}", status_code=204)
def delete_custom_rule(rule_id: int, session: Session = Depends(get_session)) -> None:
    service.delete_custom_rule(session, rule_id)
