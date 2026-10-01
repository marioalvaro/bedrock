from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_session
from bedrock.schemas.company import CompanyOut
from bedrock.services.companies import list_companies

router = APIRouter(tags=["companies"])


@router.get("/companies", response_model=list[CompanyOut])
def get_companies(session: Session = Depends(get_session)) -> list[CompanyOut]:
    return [CompanyOut.model_validate(c) for c in list_companies(session)]
