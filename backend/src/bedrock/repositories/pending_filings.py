"""The 10-Ks and 10-Qs EDGAR lists that `filing` does not hold yet (M7c, docs/erd/data.md
"New-filing detection")."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import FilingRef
from bedrock.models.filing import Filing
from bedrock.models.pending_filing import PendingFiling


def for_companies(session: Session, company_ids: Collection[int]) -> dict[int, list[PendingFiling]]:
    """Company id → its pending rows, newest `filed_at` first, in one query; [] for a company
    with none."""
    found: dict[int, list[PendingFiling]] = {company_id: [] for company_id in company_ids}
    if not found:
        return found
    stmt = (
        select(PendingFiling)
        .where(PendingFiling.company_id.in_(found))
        .order_by(PendingFiling.filed_at.desc(), PendingFiling.accession_no.desc())
    )
    for row in session.execute(stmt).scalars():
        found[row.company_id].append(row)
    return found


def replace(
    session: Session, company_id: int, refs: Collection[FilingRef], detected_at: datetime
) -> None:
    """Make the company's rows exactly `refs`: rows not among them are deleted, new ones added
    with `detected_at`, kept ones untouched. No commit."""
    wanted = {ref.accession_no: ref for ref in refs}
    stored = for_companies(session, [company_id])[company_id]
    for row in stored:
        if row.accession_no not in wanted:
            session.delete(row)
    kept = {row.accession_no for row in stored}
    for accession, ref in wanted.items():
        if accession not in kept:
            session.add(
                PendingFiling(
                    company_id=company_id,
                    accession_no=accession,
                    form=ref.form,
                    filed_at=ref.filed_at,
                    period_end=ref.period_end,
                    detected_at=detected_at,
                )
            )


def delete_ingested(session: Session, company_id: int) -> None:
    """Delete the company's rows whose accession is now in `filing`. No commit."""
    loaded = select(Filing.accession_no).where(Filing.company_id == company_id)
    session.execute(
        delete(PendingFiling).where(
            PendingFiling.company_id == company_id, PendingFiling.accession_no.in_(loaded)
        )
    )
