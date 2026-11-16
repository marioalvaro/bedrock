"""The face-statement lines of parsed filings, and each filing's XBRL status (M7b S6,
docs/erd/data-coverage.md "Storage" and "Structure rules")."""

from collections.abc import Collection, Sequence
from datetime import date

import pandas as pd
from sqlalchemy import ColumnElement, case, delete, func, insert, or_, select
from sqlalchemy.orm import Session

from bedrock.ingest.xbrl import FilingLine as ParsedLine
from bedrock.models.filing import Filing
from bedrock.models.filing_line import FilingLine
from bedrock.repositories.numeric import plain

# The forms whose XBRL is read; everything else (8-K, S-1, …) is skipped.
XBRL_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")

LINE_COLUMNS = [
    "accession_no",
    "form",
    "filed_at",
    "statement",
    "position",
    "taxonomy",
    "concept",
    "label",
    "calc_parent_taxonomy",
    "calc_parent_concept",
    "calc_weight",
]


def insert_lines(session: Session, filing_id: int, lines: Sequence[ParsedLine]) -> int:
    """Append one filing's lines; returns how many."""
    rows = [
        {
            "filing_id": filing_id,
            "statement": line.statement,
            "position": line.position,
            "taxonomy": line.taxonomy,
            "concept": line.concept,
            "label": line.label,
            "calc_parent_taxonomy": line.calc_parent_taxonomy,
            "calc_parent_concept": line.calc_parent_concept,
            "calc_weight": line.calc_weight,
        }
        for line in lines
    ]
    if rows:
        session.connection().execute(insert(FilingLine), rows)
    return len(rows)


def delete_lines(session: Session, filing_id: int) -> int:
    """Remove one filing's lines (a `--reparse` rebuilds them); returns how many."""
    result = session.execute(delete(FilingLine).where(FilingLine.filing_id == filing_id))
    return int(result.rowcount)  # type: ignore[attr-defined]  # a DML result has a rowcount


def lines_for(session: Session, company_id: int, as_of: date | None = None) -> pd.DataFrame:
    """Every line of the company's `parsed` filings (filed on or before `as_of`, when given),
    joined to its filing, in filing date, statement and presentation order."""
    stmt = (
        select(
            Filing.accession_no,
            Filing.form,
            Filing.filed_at,
            FilingLine.statement,
            FilingLine.position,
            FilingLine.taxonomy,
            FilingLine.concept,
            FilingLine.label,
            FilingLine.calc_parent_taxonomy,
            FilingLine.calc_parent_concept,
            FilingLine.calc_weight,
        )
        .join(Filing, Filing.id == FilingLine.filing_id)
        .where(Filing.company_id == company_id, Filing.xbrl_status == "parsed")
        .order_by(Filing.filed_at, Filing.accession_no, FilingLine.statement, FilingLine.position)
    )
    if as_of is not None:
        stmt = stmt.where(Filing.filed_at <= as_of)
    records = []
    for row in session.execute(stmt):
        weight = row.calc_weight
        records.append((*row[:10], None if weight is None else plain(weight)))
    return pd.DataFrame(records, columns=LINE_COLUMNS).astype({"calc_weight": "object"})


def filings_to_parse(
    session: Session, company_id: int, statuses: Collection[str | None], limit: int | None = None
) -> list[Filing]:
    """The company's filings of the four forms whose `xbrl_status` is one of `statuses` (None =
    not tried), newest first, at most `limit`."""
    wanted = [s for s in statuses if s is not None]
    condition: ColumnElement[bool] = Filing.xbrl_status.in_(wanted)
    if None in statuses:
        condition = or_(condition, Filing.xbrl_status.is_(None))
    stmt = (
        select(Filing)
        .where(Filing.company_id == company_id, Filing.form.in_(XBRL_FORMS), condition)
        .order_by(Filing.filed_at.desc(), Filing.accession_no.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def xbrl_progress(session: Session, company_ids: Collection[int]) -> dict[int, tuple[int, int]]:
    """Company id → (parsed, total) filings of the four forms, in one query; (0, 0) for a company
    with none."""
    stmt = (
        select(
            Filing.company_id,
            func.sum(case((Filing.xbrl_status == "parsed", 1), else_=0)),
            func.count(),
        )
        .where(Filing.company_id.in_(company_ids), Filing.form.in_(XBRL_FORMS))
        .group_by(Filing.company_id)
    )
    progress = {company_id: (0, 0) for company_id in company_ids}
    for company_id, parsed, total in session.execute(stmt):
        progress[company_id] = (int(parsed or 0), int(total))
    return progress
