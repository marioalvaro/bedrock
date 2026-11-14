"""services/filings.py::ingest_filings: each 10-K and 10-Q read once, its extension facts stored as
raw facts and its statement lines stored (M7b S6, docs/erd/data-coverage.md "Flow")."""

from collections.abc import Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.ingest.xbrl import XBRL_PARSER_VERSION
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.models.filing_line import FilingLine
from bedrock.models.raw_fact import RawFact
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import filing_lines as lines_repo
from bedrock.services.filings import ingest_filings

from .fakes import FakeEdgar, FakeFilings, FakePrices

FY2024 = "0000320193-24-000123"  # AAPL 10-K FY2024, recorded
FY2010 = "0001193125-10-238044"  # AAPL 10-K FY2010, recorded
FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")


def _sources(filings: FakeFilings | None) -> Sources:
    return Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=filings)


def _aapl(session: Session, seed_db: Callable[..., None]) -> Company:
    seed_db("AAPL")
    company = companies_repo.get_by_ticker(session, "AAPL")
    assert company is not None
    return company


def _status(session: Session, accession: str) -> tuple[str | None, int | None]:
    filing = session.execute(select(Filing).where(Filing.accession_no == accession)).scalar_one()
    return filing.xbrl_status, filing.xbrl_parser_version


def _count(session: Session, model: type, *where: object) -> int:
    return session.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def _four_forms(session: Session, company: Company) -> list[str]:
    stmt = (
        select(Filing.accession_no)
        .where(Filing.company_id == company.id, Filing.form.in_(FORMS))
        .order_by(Filing.filed_at.desc(), Filing.accession_no.desc())
    )
    return list(session.execute(stmt).scalars())


def test_extension_facts_are_inserted_from_the_filing_and_no_standard_fact_is_added(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    company = _aapl(db_session, seed_db)
    standard_before = _count(db_session, RawFact)

    result = ingest_filings(db_session, _sources(FakeFilings()), company, limit=None)

    from_filings = db_session.execute(select(RawFact).where(RawFact.source == "filing")).scalars()
    rows = list(from_filings)
    assert rows and {r.taxonomy for r in rows} == {"aapl"}
    assert result.new_facts == len(rows)
    assert _count(db_session, RawFact, RawFact.source == "companyfacts") == standard_before
    # Each fact belongs to its filing and carries the filing's fy/fp, as companyfacts facts do.
    filings = {f.id: f for f in db_session.execute(select(Filing)).scalars()}
    assert {filings[r.filing_id].accession_no for r in rows} == {FY2024, FY2010}
    assert all(r.fiscal_year == filings[r.filing_id].fiscal_year for r in rows)
    assert all(r.fiscal_period == filings[r.filing_id].fiscal_period for r in rows)


def test_each_filing_gets_a_status_and_the_parsed_ones_their_lines(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    company = _aapl(db_session, seed_db)
    total = len(_four_forms(db_session, company))

    result = ingest_filings(db_session, _sources(FakeFilings()), company, limit=None)

    assert (result.parsed, result.absent, result.failed) == (2, total - 2, 0)
    assert _status(db_session, FY2024) == ("parsed", XBRL_PARSER_VERSION)
    assert _status(db_session, FY2010) == ("parsed", XBRL_PARSER_VERSION)
    assert _count(db_session, Filing, Filing.xbrl_status == "absent") == total - 2
    # Filings of other forms are never tried.
    assert _count(db_session, Filing, Filing.xbrl_status.is_(None)) == _count(
        db_session, Filing, Filing.form.not_in(FORMS)
    )
    frame = lines_repo.lines_for(db_session, company.id)
    assert result.new_lines == len(frame) == _count(db_session, FilingLine)
    assert set(frame["accession_no"]) == {FY2024, FY2010}
    assert set(frame["statement"]) == {"IS", "BS", "CF"}


def test_the_work_is_committed_filing_by_filing(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    company = _aapl(db_session, seed_db)
    ingest_filings(db_session, _sources(FakeFilings()), company, limit=3)

    db_session.rollback()

    assert _count(db_session, Filing, Filing.xbrl_status.is_not(None)) == 3


def test_a_second_run_fetches_and_inserts_nothing(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    company = _aapl(db_session, seed_db)
    ingest_filings(db_session, _sources(FakeFilings()), company, limit=None)
    facts, lines = _count(db_session, RawFact), _count(db_session, FilingLine)
    again = FakeFilings()

    result = ingest_filings(db_session, _sources(again), company, limit=None)

    assert again.calls == []
    assert (result.parsed, result.absent, result.failed, result.new_facts, result.new_lines) == (
        0,
        0,
        0,
        0,
        0,
    )
    assert (_count(db_session, RawFact), _count(db_session, FilingLine)) == (facts, lines)


def test_limit_takes_the_newest_filings_of_the_four_forms(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    company = _aapl(db_session, seed_db)
    filings = FakeFilings()

    ingest_filings(db_session, _sources(filings), company, limit=4)

    assert filings.calls == _four_forms(db_session, company)[:4]


@pytest.mark.parametrize(
    "fake",
    [
        FakeFilings(fail={FY2024: SourceUnavailable("HTTP 503 after 3 retries")}),
        FakeFilings(broken={FY2024}),
    ],
    ids=["fetch-fails", "parse-fails"],
)
def test_a_failing_filing_is_failed_with_a_warning_and_the_next_is_still_processed(
    db_session: Session, seed_db: Callable[..., None], fake: FakeFilings
) -> None:
    company = _aapl(db_session, seed_db)

    result = ingest_filings(db_session, _sources(fake), company, limit=None)

    assert _status(db_session, FY2024) == ("failed", None)
    assert _status(db_session, FY2010) == ("parsed", XBRL_PARSER_VERSION)
    assert result.failed == 1
    assert len(result.warnings) == 1 and FY2024 in result.warnings[0]
    assert not lines_repo.lines_for(db_session, company.id)["accession_no"].eq(FY2024).any()


def test_reparse_rebuilds_the_lines_and_retries_failed_filings_without_new_facts(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    company = _aapl(db_session, seed_db)
    ingest_filings(db_session, _sources(FakeFilings(broken={FY2010})), company, limit=None)
    assert _status(db_session, FY2010)[0] == "failed"
    full_lines_2024 = _count(db_session, FilingLine)
    # A stale line of an older parser version, to be replaced.
    fy2024 = db_session.execute(select(Filing).where(Filing.accession_no == FY2024)).scalar_one()
    db_session.query(FilingLine).filter(FilingLine.position > 3).delete()
    fy2024.xbrl_parser_version = XBRL_PARSER_VERSION - 1
    db_session.commit()
    facts_before = _count(db_session, RawFact, RawFact.filing_id == fy2024.id)
    absent_before = _count(db_session, Filing, Filing.xbrl_status == "absent")
    filings = FakeFilings()

    result = ingest_filings(db_session, _sources(filings), company, limit=None, reparse=True)

    assert sorted(filings.calls) == sorted([FY2024, FY2010])  # absent filings are not re-read
    assert _status(db_session, FY2024) == ("parsed", XBRL_PARSER_VERSION)
    assert _status(db_session, FY2010) == ("parsed", XBRL_PARSER_VERSION)
    assert _count(db_session, RawFact, RawFact.filing_id == fy2024.id) == facts_before
    assert _count(db_session, Filing, Filing.xbrl_status == "absent") == absent_before
    fy2024_lines = _count(db_session, FilingLine, FilingLine.filing_id == fy2024.id)
    assert fy2024_lines == full_lines_2024
    assert result.parsed == 2 and result.new_lines == _count(db_session, FilingLine)


def test_without_a_filings_source_nothing_is_tried(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    company = _aapl(db_session, seed_db)

    result = ingest_filings(db_session, _sources(None), company, limit=None)

    assert (result.parsed, result.absent, result.failed) == (0, 0, 0)
    assert _count(db_session, Filing, Filing.xbrl_status.is_not(None)) == 0


def test_a_manual_company_has_no_filings_to_read(db_session: Session) -> None:
    company = Company(
        ticker="PRIV",
        cik=None,
        name="Private",
        fiscal_year_end_month=12,
        currency="USD",
        source="manual",
        sic=None,
        last_refreshed_at=None,
    )
    db_session.add(company)
    db_session.commit()
    filings = FakeFilings()

    result = ingest_filings(db_session, _sources(filings), company, limit=None)

    assert filings.calls == [] and result.parsed == 0
