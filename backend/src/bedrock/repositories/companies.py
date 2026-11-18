from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.adjustment import Adjustment
from bedrock.models.company import Company
from bedrock.models.comps_set import CompsSet
from bedrock.models.filing import Filing
from bedrock.models.forecast_run import ForecastSnapshot
from bedrock.models.guidance import Guidance
from bedrock.models.note import Note
from bedrock.models.raw_fact import RawFact
from bedrock.models.scenario import Scenario
from bedrock.models.statement_import import StatementImport
from bedrock.models.thesis_checkpoint import ThesisCheckpoint


def get_by_ticker(session: Session, ticker: str) -> Company | None:
    return session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()


def list_all(session: Session) -> list[Company]:
    """Every company, archived ones included, by ticker."""
    return list(session.execute(select(Company).order_by(Company.ticker)).scalars().all())


def list_followed(session: Session, archived: bool = False) -> list[Company]:
    """The followed companies (`archived_at` null), or with `archived` the archived ones only,
    by ticker."""
    cut = Company.archived_at.is_not(None) if archived else Company.archived_at.is_(None)
    stmt = select(Company).where(cut).order_by(Company.ticker)
    return list(session.execute(stmt).scalars().all())


def get_by_cik(session: Session, cik: str) -> Company | None:
    return session.execute(select(Company).where(Company.cik == cik)).scalar_one_or_none()


@dataclass(frozen=True)
class DeletionCounts:
    """The rows of one company that deleting it cascades to, per kind."""

    filings: int
    facts: int
    notes: int
    scenarios: int
    snapshots: int
    guidance: int
    adjustments: int
    checkpoints: int
    comps_sets: int
    imports: int


_COUNTED = {
    "filings": Filing.company_id,
    "facts": RawFact.company_id,
    "notes": Note.company_id,
    "scenarios": Scenario.company_id,
    "snapshots": ForecastSnapshot.company_id,
    "guidance": Guidance.company_id,
    "adjustments": Adjustment.company_id,
    "checkpoints": ThesisCheckpoint.company_id,
    "comps_sets": CompsSet.company_id,
    "imports": StatementImport.company_id,
}


def deletion_counts(session: Session, company_id: int) -> DeletionCounts:
    """Every count of `DeletionCounts` in one query (a scalar subquery per table)."""
    columns = [
        select(func.count(column)).where(column == company_id).scalar_subquery().label(name)
        for name, column in _COUNTED.items()
    ]
    row = session.execute(select(*columns)).one()
    return DeletionCounts(**row._asdict())
