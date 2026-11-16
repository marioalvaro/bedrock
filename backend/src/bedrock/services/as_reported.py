"""One filing's statement as the company filed it (M7d S1, docs/erd/face-tree.md "As reported
route"). Read only: no feature takes a value from it."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.repositories import mappings as mappings_repo
from bedrock.services.errors import FilingNotFound
from bedrock.services.statements import canonical_items, face_lines
from bedrock.statements.projection import ProjectedStatement, project
from bedrock.statements.records import records


@dataclass(frozen=True)
class FilingRef:
    accession_no: str
    form: str
    filed_at: date


@dataclass(frozen=True)
class AsReported:
    """`statement` is None when the company has no parsed filing with lines for it. `filings`
    are those that have lines for it, newest first; `labels` names every canonical code."""

    statement: ProjectedStatement | None
    filings: list[FilingRef] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)


def as_reported(
    session: Session, company: Company, statement: str, accession: str | None
) -> AsReported:
    """The statement of `accession`, or by default of the newest 10-K (by filed date, then
    accession) that has lines for it, else of the newest parsed filing that has them. The face
    lines are loaded as the statements load them (`face_lines`). Raises FilingNotFound when
    `accession` is not a parsed filing of the company with lines for the statement."""
    items = canonical_items()
    labels = {i.code: i.label for i in items}
    face = face_lines(session, company, mappings_repo.mappings_for(session, company.id), None)
    filings: list[FilingRef] = []
    if face is not None:
        rows = face.lines[face.lines["statement"] == statement]
        seen = {
            (r["filed_at"], r["accession_no"], r["form"])
            for r in records(rows[["filed_at", "accession_no", "form"]])
        }
        filings = [FilingRef(a, f, d) for d, a, f in sorted(seen, reverse=True)]
    if accession is not None:
        if accession not in {f.accession_no for f in filings}:
            raise FilingNotFound(accession)
        chosen: str | None = accession
    else:
        candidates = [f for f in filings if f.form.startswith("10-K")] or filings
        chosen = candidates[0].accession_no if candidates else None
    if face is None or chosen is None:
        return AsReported(None, filings, labels)
    return AsReported(project(face, items, chosen, statement), filings, labels)
