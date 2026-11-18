"""Line classification (M7d S3, docs/erd/face-tree.md "Routes"). Only `POST …/classifications/
run` builds a classifier and lets it ask; no GET does."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from bedrock.api.deps import (
    get_classifications,
    get_classifier_factory,
    get_clock,
    get_session,
    get_session_factory,
    get_settings,
)
from bedrock.api.v1.statements import followed_company
from bedrock.core.config import Settings
from bedrock.models.company import Company
from bedrock.schemas.classification import (
    AnswerIn,
    ClassificationOut,
    ClassificationRunOut,
    ClassificationsOut,
    ClassificationStatusOut,
    DecisionIn,
    ModeIn,
    RunIn,
)
from bedrock.schemas.company import CompanyListItem
from bedrock.services import classification as service
from bedrock.services import companies as companies_service
from bedrock.services.classification import ClassificationRunner, Factory

router = APIRouter(tags=["classification"])


@router.get("/classification/status")
def get_status(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_clock),
) -> ClassificationStatusOut:
    """The classifiers and whether each has its key, the token budgets and what was used."""
    return ClassificationStatusOut.from_status(service.status(session, settings, now))


@router.get("/companies/{ticker}/classifications")
def get_classifications_of(
    classifier: str | None = None,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ClassificationsOut:
    """The company's lines to classify with their answers; with `classifier`, also what a run of
    it would ask now and its estimate. 409 for an unknown classifier name."""
    return ClassificationsOut.from_view(service.overview(session, settings, company, classifier))


@router.post("/companies/{ticker}/classifications/run", status_code=202)
def start_run(
    ticker: str,
    body: RunIn,
    session: Session = Depends(get_session),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    factory: Factory = Depends(get_classifier_factory),
    settings: Settings = Depends(get_settings),
    runner: ClassificationRunner = Depends(get_classifications),
) -> ClassificationRunOut:
    """Ask the classifier about the company's open lines, in a worker thread. This sends their
    labels, tags and amounts to the provider. 409 when the classifier has no key, nothing is
    left to ask, `confirm_lines` is not the number that would be sent, the estimate does not fit
    a budget, or a run is running."""
    run = runner.start(
        session, session_factory, factory, settings, ticker, body.classifier, body.confirm_lines
    )
    return ClassificationRunOut.from_model(run)


@router.put("/companies/{ticker}/classifications/{classification_id}")
def decide(
    classification_id: int,
    body: DecisionIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> ClassificationOut:
    """Accept, reject or reopen one answer."""
    return ClassificationOut.from_model(
        service.decide(session, company, classification_id, body.status, now)
    )


@router.put("/companies/{ticker}/classifications")
def answer(
    body: AnswerIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> ClassificationOut:
    """The user's own answer for one line, stored accepted."""
    return ClassificationOut.from_model(
        service.answer(
            session, company, body.statement, body.taxonomy, body.concept, body.codes, now
        )
    )


@router.put("/companies/{ticker}/classification-mode")
def set_mode(
    body: ModeIn,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> CompanyListItem:
    """What of the classifications the company's statements use: off, accepted, or all."""
    service.set_mode(session, company, body.mode, body.source, now)
    return CompanyListItem.from_view(companies_service.get_company(session, company.ticker))
