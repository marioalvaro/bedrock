"""Line classifications and the runs that produce them (M7d S3, docs/erd/face-tree.md "Storage",
"Effective classification")."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.classification_run import ClassificationRun
from bedrock.models.company import Company
from bedrock.models.line_classification import LineClassification

Line = tuple[str, str, str]  # (statement, taxonomy, concept)
Concept = tuple[str, str]  # (taxonomy, concept)
CONFIDENCE_PLACES = Decimal("0.0001")
COST_PLACES = Decimal("0.000001")  # SQLite sums a Numeric as a float
_STATEMENT_ORDER = ("IS", "BS", "CF")


@dataclass(frozen=True)
class Proposal:
    statement: str
    taxonomy: str
    concept: str
    codes: tuple[str, ...]
    confidence: float  # 0..1


def line_of(row: LineClassification) -> Line:
    return (row.statement, row.taxonomy, row.concept)


def codes_of(row: LineClassification) -> tuple[str, ...]:
    return tuple(json.loads(row.codes))


def codes_text(codes: Sequence[str]) -> str:
    """The stored form of an answer's codes: a JSON list."""
    return json.dumps(list(codes))


def confidence_value(confidence: float) -> Decimal:
    """A confidence as the column keeps it (four places)."""
    return Decimal(str(confidence)).quantize(CONFIDENCE_PLACES)


def rows_for(session: Session, company_id: int) -> list[LineClassification]:
    """Every answer for the company's lines, by id."""
    stmt = (
        select(LineClassification)
        .where(LineClassification.company_id == company_id)
        .order_by(LineClassification.id)
    )
    return list(session.execute(stmt).scalars())


def get(session: Session, company_id: int, classification_id: int) -> LineClassification | None:
    """The row, only when it belongs to the company."""
    stmt = select(LineClassification).where(
        LineClassification.company_id == company_id, LineClassification.id == classification_id
    )
    return session.execute(stmt).scalar_one_or_none()


def get_for(
    session: Session, company_id: int, line: Line, classifier: str
) -> LineClassification | None:
    """The classifier's answer for one line of the company."""
    stmt = select(LineClassification).where(
        LineClassification.company_id == company_id,
        LineClassification.statement == line[0],
        LineClassification.taxonomy == line[1],
        LineClassification.concept == line[2],
        LineClassification.classifier == classifier,
    )
    return session.execute(stmt).scalar_one_or_none()


def add_proposals(
    session: Session,
    company_id: int,
    classifier: str,
    run_id: int | None,
    proposals: Sequence[Proposal],
    stamp: datetime,
) -> int:
    """Adds one `proposed` row per proposal and flushes (no commit); returns how many."""
    session.add_all(
        LineClassification(
            company_id=company_id,
            statement=p.statement,
            taxonomy=p.taxonomy,
            concept=p.concept,
            classifier=classifier,
            codes=codes_text(p.codes),
            confidence=confidence_value(p.confidence),
            status="proposed",
            run_id=run_id,
            created_at=stamp,
        )
        for p in proposals
    )
    session.flush()
    return len(proposals)


def add(session: Session, row: LineClassification) -> LineClassification:
    """Adds and flushes (no commit)."""
    session.add(row)
    session.flush()
    return row


def set_status(
    session: Session, row: LineClassification, status: str, stamp: datetime
) -> list[LineClassification]:
    """Sets the row's status and `decided_at`, and flushes. At most one row of a line is
    accepted: accepting one sets any other accepted row of the line back to `proposed`. Returns
    the rows put back."""
    put_back: list[LineClassification] = []
    if status == "accepted":
        others = select(LineClassification).where(
            LineClassification.company_id == row.company_id,
            LineClassification.statement == row.statement,
            LineClassification.taxonomy == row.taxonomy,
            LineClassification.concept == row.concept,
            LineClassification.status == "accepted",
            LineClassification.id != row.id,
        )
        for other in session.execute(others).scalars():
            other.status = "proposed"
            other.decided_at = stamp
            put_back.append(other)
    row.status = status
    row.decided_at = stamp
    session.flush()
    return put_back


def effective_lines(
    rows: Sequence[LineClassification], mode: str, source: str | None, min_confidence: float
) -> dict[Line, tuple[str, ...]]:
    """The codes in force for each line under `mode`. `off`: none. `accepted`: the line's
    accepted row. `all`: its accepted row, else its `proposed` row of `source` with confidence at
    or above `min_confidence`. A rejected row is never in force."""
    if mode == "off":
        return {}
    out: dict[Line, tuple[str, ...]] = {}
    threshold = confidence_value(min_confidence)
    if mode == "all" and source is not None:
        for row in rows:
            usable = row.status == "proposed" and row.classifier == source
            if usable and row.confidence >= threshold:
                out[line_of(row)] = codes_of(row)
    for row in rows:
        if row.status == "accepted":
            out[line_of(row)] = codes_of(row)
    return out


def effective(
    session: Session, company: Company, min_confidence: float
) -> dict[Concept, tuple[str, ...]]:
    """The company's effective classifications by concept, under its mode and source: a
    concept's statements merged into one tuple of codes (a code belongs to one statement), IS,
    BS, CF."""
    if company.classification_mode == "off":
        return {}
    lines = effective_lines(
        rows_for(session, company.id),
        company.classification_mode,
        company.classification_source,
        min_confidence,
    )
    out: dict[Concept, tuple[str, ...]] = {}
    for line in sorted(lines, key=lambda ln: _STATEMENT_ORDER.index(ln[0])):
        concept = (line[1], line[2])
        merged = dict.fromkeys((*out.get(concept, ()), *lines[line]))
        out[concept] = tuple(merged)
    return out


def add_run(session: Session, run: ClassificationRun) -> ClassificationRun:
    """Adds and flushes (no commit). The database refuses a second `running` row
    (`IntegrityError`)."""
    session.add(run)
    session.flush()
    return run


def get_run(session: Session, run_id: int) -> ClassificationRun | None:
    return session.get(ClassificationRun, run_id)


def newest_run(session: Session, company_id: int) -> ClassificationRun | None:
    stmt = (
        select(ClassificationRun)
        .where(ClassificationRun.company_id == company_id)
        .order_by(ClassificationRun.started_at.desc(), ClassificationRun.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def running(session: Session) -> ClassificationRun | None:
    """The one running run of the database, if any."""
    stmt = select(ClassificationRun).where(ClassificationRun.status == "running")
    return session.execute(stmt).scalar_one_or_none()


def usage(session: Session, start: datetime, end: datetime) -> tuple[int, Decimal]:
    """(input + output tokens, cost in USD) of every run started in [`start`, `end`), whatever
    its company or status."""
    stmt = select(
        func.coalesce(
            func.sum(ClassificationRun.input_tokens + ClassificationRun.output_tokens), 0
        ),
        func.coalesce(func.sum(ClassificationRun.cost_usd), 0),
    ).where(ClassificationRun.started_at >= start, ClassificationRun.started_at < end)
    tokens, cost = session.execute(stmt).one()
    return int(tokens), Decimal(str(cost)).quantize(COST_PLACES)
