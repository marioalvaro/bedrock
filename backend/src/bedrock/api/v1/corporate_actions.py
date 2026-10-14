from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.repositories import corporate_actions as actions_repo
from bedrock.schemas.corporate_actions import CorporateActionOut

router = APIRouter(tags=["corporate-actions"])


@router.get("/companies/{ticker}/corporate-actions")
def list_corporate_actions(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> list[CorporateActionOut]:
    return [CorporateActionOut.from_model(a) for a in actions_repo.list_for(session, company.id)]
