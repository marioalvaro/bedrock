"""repositories/filing_lines.py: the face-statement lines of parsed filings and the filings' XBRL
status (M7b S6, docs/erd/data-coverage.md "Storage"), over a real SQLite database."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.parse import FilingRecord, ParsedFacts
from bedrock.ingest.xbrl import FilingLine as ParsedLine
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.models.filing_line import FilingLine
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import filing_lines as lines_repo


def _company(session: Session, ticker: str = "AAA") -> Company:
    company = Company(
        ticker=ticker,
        cik=f"{len(ticker):010d}",
        name=ticker,
        fiscal_year_end_month=12,
        currency="USD",
        sic=None,
        last_refreshed_at=None,
    )
    session.add(company)
    session.flush()
    return company


def _filings(session: Session, company: Company, *rows: tuple[str, str, date]) -> list[Filing]:
    """rows: (accession, form, filed_at)."""
    records = [
        FilingRecord(accession, form, filed, filed.year, "FY", filed)
        for accession, form, filed in rows
    ]
    facts_repo.insert_parsed(session, company, ParsedFacts(filings=records, facts=[]))
    session.flush()
    by_accession = {
        f.accession_no: f
        for f in session.execute(select(Filing).where(Filing.company_id == company.id)).scalars()
    }
    return [by_accession[accession] for accession, _, _ in rows]


def _line(statement: str, position: int, concept: str, parent: str | None = None) -> ParsedLine:
    return ParsedLine(
        statement=statement,
        position=position,
        taxonomy="us-gaap" if concept[0].isupper() else "acme",
        concept=concept,
        label=concept.lower(),
        calc_parent_taxonomy="us-gaap" if parent else None,
        calc_parent_concept=parent,
        calc_weight=Decimal("-1") if parent else None,
    )


def test_lines_are_stored_and_read_back_joined_to_their_filing(db_session: Session) -> None:
    company = _company(db_session)
    (filing,) = _filings(db_session, company, ("A-1", "10-K", date(2024, 11, 1)))
    filing.xbrl_status = "parsed"
    db_session.flush()  # the app's sessions do not autoflush
    lines = [_line("CF", 1, "NetIncomeLoss"), _line("CF", 2, "widgetCosts", "NetIncomeLoss")]

    assert lines_repo.insert_lines(db_session, filing.id, lines) == 2
    frame = lines_repo.lines_for(db_session, company.id)

    assert list(frame.columns) == lines_repo.LINE_COLUMNS
    assert frame.to_dict("records")[1] == {
        "accession_no": "A-1",
        "form": "10-K",
        "filed_at": date(2024, 11, 1),
        "statement": "CF",
        "position": 2,
        "taxonomy": "acme",
        "concept": "widgetCosts",
        "label": "widgetcosts",
        "calc_parent_taxonomy": "us-gaap",
        "calc_parent_concept": "NetIncomeLoss",
        "calc_weight": Decimal("-1"),
    }
    # A plain Decimal, not the column's padded one (G15).
    assert str(frame.iloc[1]["calc_weight"]) == "-1"
    assert frame.iloc[0]["calc_weight"] is None


def test_lines_are_read_only_from_parsed_filings_of_the_company(db_session: Session) -> None:
    company, other = _company(db_session), _company(db_session, "BBBB")
    parsed, failed = _filings(
        db_session, company, ("A-1", "10-K", date(2024, 1, 1)), ("A-2", "10-K", date(2025, 1, 1))
    )
    (theirs,) = _filings(db_session, other, ("B-1", "10-K", date(2024, 1, 1)))
    for filing, status in ((parsed, "parsed"), (failed, "failed"), (theirs, "parsed")):
        filing.xbrl_status = status
        db_session.flush()  # the app's sessions do not autoflush
        lines_repo.insert_lines(db_session, filing.id, [_line("BS", 1, "Assets")])

    assert lines_repo.lines_for(db_session, company.id)["accession_no"].tolist() == ["A-1"]


def test_lines_as_of_a_date_exclude_filings_filed_later(db_session: Session) -> None:
    company = _company(db_session)
    early, late = _filings(
        db_session, company, ("A-1", "10-K", date(2024, 1, 1)), ("A-2", "10-Q", date(2024, 5, 1))
    )
    for filing in (early, late):
        filing.xbrl_status = "parsed"
        db_session.flush()  # the app's sessions do not autoflush
        lines_repo.insert_lines(db_session, filing.id, [_line("IS", 1, "Revenues")])

    assert lines_repo.lines_for(db_session, company.id, as_of=date(2024, 4, 30))[
        "accession_no"
    ].tolist() == ["A-1"]
    assert lines_repo.lines_for(db_session, company.id, as_of=date(2024, 5, 1))[
        "accession_no"
    ].tolist() == ["A-1", "A-2"]


def test_no_lines_give_an_empty_frame_with_the_columns(db_session: Session) -> None:
    frame = lines_repo.lines_for(db_session, _company(db_session).id)

    assert frame.empty
    assert list(frame.columns) == lines_repo.LINE_COLUMNS


def test_deleting_a_filings_lines_leaves_the_others(db_session: Session) -> None:
    company = _company(db_session)
    first, second = _filings(
        db_session, company, ("A-1", "10-K", date(2024, 1, 1)), ("A-2", "10-K", date(2025, 1, 1))
    )
    for filing in (first, second):
        lines_repo.insert_lines(db_session, filing.id, [_line("IS", 1, "Revenues")])

    assert lines_repo.delete_lines(db_session, first.id) == 1
    remaining = db_session.execute(select(FilingLine.filing_id)).scalars().all()
    assert remaining == [second.id]


def test_filings_to_parse_are_the_four_forms_not_tried_newest_first(db_session: Session) -> None:
    company = _company(db_session)
    filings = _filings(
        db_session,
        company,
        ("A-1", "10-K", date(2023, 1, 1)),
        ("A-2", "8-K", date(2023, 2, 1)),
        ("A-3", "10-Q", date(2023, 5, 1)),
        ("A-4", "10-K/A", date(2023, 6, 1)),
        ("A-5", "10-Q/A", date(2023, 7, 1)),
        ("A-6", "10-Q", date(2023, 8, 1)),
        ("A-7", "S-1", date(2023, 9, 1)),
    )
    filings[5].xbrl_status = "parsed"
    db_session.flush()  # the app's sessions do not autoflush

    chosen = lines_repo.filings_to_parse(db_session, company.id, {None})

    assert [f.accession_no for f in chosen] == ["A-5", "A-4", "A-3", "A-1"]
    assert [
        f.accession_no for f in lines_repo.filings_to_parse(db_session, company.id, {None}, limit=2)
    ] == [
        "A-5",
        "A-4",
    ]
    assert [
        f.accession_no for f in lines_repo.filings_to_parse(db_session, company.id, {"parsed"})
    ] == ["A-6"]


def test_xbrl_progress_counts_parsed_and_total_filings_of_the_four_forms(
    db_session: Session,
) -> None:
    company, other, empty = (
        _company(db_session),
        _company(db_session, "BBBB"),
        _company(db_session, "CC"),
    )
    mine = _filings(
        db_session,
        company,
        ("A-1", "10-K", date(2023, 1, 1)),
        ("A-2", "10-Q", date(2023, 5, 1)),
        ("A-3", "8-K", date(2023, 6, 1)),
    )
    mine[0].xbrl_status = "parsed"
    db_session.flush()  # the app's sessions do not autoflush
    mine[2].xbrl_status = "parsed"  # not one of the four forms: not counted
    db_session.flush()  # the app's sessions do not autoflush
    (theirs,) = _filings(db_session, other, ("B-1", "10-Q", date(2023, 1, 1)))
    theirs.xbrl_status = "absent"
    db_session.flush()  # the app's sessions do not autoflush
    db_session.flush()

    progress = lines_repo.xbrl_progress(db_session, [company.id, other.id, empty.id])

    assert progress == {company.id: (1, 2), other.id: (0, 1), empty.id: (0, 0)}
    assert db_session.execute(select(func.count()).select_from(Filing)).scalar_one() == 4
