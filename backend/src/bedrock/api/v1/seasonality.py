from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bedrock.api.deps import get_session
from bedrock.api.v1.statements import followed_company
from bedrock.models.company import Company
from bedrock.schemas.seasonality import SeasonalityOut
from bedrock.services import seasonality as service

router = APIRouter(tags=["seasonality"])


@router.get("/companies/{ticker}/seasonality")
def get_seasonality(
    code: str = service.DEFAULT_LINE,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> SeasonalityOut:
    return SeasonalityOut.from_view(service.decomposition(session, company, code))
