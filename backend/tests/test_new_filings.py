"""New-filing detection (docs/erd/data.md "New-filing detection", FR-DATA-23): the filing index
parser, which refs are new, and the daily check that marks a company."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.parse import parse_recent_filings, unseen_filings
from bedrock.ingest.protocol import FilingRef, SourceNotConfigured, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.models.pending_filing import PendingFiling
from bedrock.repositories import companies as companies_repo
from bedrock.repositories.pending_filings import for_companies
from bedrock.services.new_filings import (
    FILINGS_CHECK_INTERVAL,
    check_all,
    check_company,
    filings_due,
)
from bedrock.services.refresh import refresh_company

from .fakes import FakeEdgar, FakePrices, FakeSubmissions
from .seed import fake_sources

INDEX = Path(__file__).parent / "fixtures" / "edgar" / "recent_filings" / "AAPL.json"


def _index() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(INDEX.read_text())
    return doc


def _doc(*rows: tuple[str, str, str, str]) -> dict[str, Any]:
    accessions, forms, filed, reported = (list(column) for column in zip(*rows, strict=True))
    recent = {
        "accessionNumber": accessions,
        "form": forms,
        "filingDate": filed,
        "reportDate": reported,
    }
    return {"filings": {"recent": recent}}


# --- the parser ---------------------------------------------------------------------------------


def test_the_parser_keeps_the_10_k_and_10_q_rows_newest_first() -> None:
    assert parse_recent_filings(_index()) == [
        FilingRef("0000320193-26-000029", "10-K", date(2026, 10, 30), date(2026, 9, 26)),
        FilingRef("0000320193-26-000020", "10-Q", date(2026, 7, 31), date(2026, 6, 27)),
        FilingRef("0000320193-26-000013", "10-Q", date(2026, 5, 1), date(2026, 3, 28)),
    ]


def test_amendments_and_other_forms_are_left_out() -> None:
    doc = _doc(
        ("a1", "10-K/A", "2026-01-02", "2025-09-27"),
        ("a2", "10-Q/A", "2026-01-03", "2025-12-27"),
        ("a3", "8-K", "2026-01-04", "2026-01-04"),
        ("a4", "10-KT", "2026-01-05", "2025-12-31"),
    )

    assert parse_recent_filings(doc) == []


def test_a_blank_report_date_is_no_period_end() -> None:
    doc = _doc(("a1", "10-Q", "2026-02-01", ""))

    assert parse_recent_filings(doc) == [FilingRef("a1", "10-Q", date(2026, 2, 1), None)]


def test_rows_are_sorted_newest_first_whatever_the_order_given() -> None:
    doc = _doc(
        ("old", "10-Q", "2025-05-02", "2025-03-29"),
        ("new", "10-K", "2025-10-31", "2025-09-27"),
        ("mid", "10-Q", "2025-08-01", "2025-06-28"),
    )

    assert [ref.accession_no for ref in parse_recent_filings(doc)] == ["new", "mid", "old"]


def test_a_document_without_recent_filings_gives_nothing() -> None:
    assert parse_recent_filings({}) == []
    assert parse_recent_filings({"filings": {}}) == []
    empty = {"accessionNumber": [], "form": [], "filingDate": [], "reportDate": []}
    assert parse_recent_filings({"filings": {"recent": empty}}) == []


# --- which refs are new -------------------------------------------------------------------------

NEW_10K = FilingRef("n-10k", "10-K", date(2026, 10, 30), date(2026, 9, 26))
STORED = FilingRef("s-10q", "10-Q", date(2026, 7, 31), date(2026, 6, 27))
OLD = FilingRef("o-10q", "10-Q", date(2026, 5, 1), date(2026, 3, 28))


def test_a_ref_not_stored_and_filed_on_or_after_the_newest_stored_is_new() -> None:
    same_day = FilingRef("same-day", "10-Q", date(2026, 7, 31), None)

    assert unseen_filings([NEW_10K, same_day, STORED], {"s-10q"}, date(2026, 7, 31)) == [
        NEW_10K,
        same_day,
    ]


def test_a_stored_accession_is_not_new() -> None:
    assert unseen_filings([STORED], {"s-10q"}, date(2026, 1, 1)) == []


def test_an_older_ref_companyfacts_never_listed_is_not_new() -> None:
    assert unseen_filings([OLD], {"s-10q"}, date(2026, 7, 31)) == []


def test_without_a_stored_filing_nothing_is_new() -> None:
    assert unseen_filings([NEW_10K, OLD], set(), None) == []


def test_the_fixture_against_the_recorded_companyfacts_has_one_new_10_k() -> None:
    stored = {"0000320193-26-000020", "0000320193-26-000013"}

    unseen = unseen_filings(parse_recent_filings(_index()), stored, date(2026, 7, 31))

    assert [(ref.accession_no, ref.form) for ref in unseen] == [("0000320193-26-000029", "10-K")]


# --- when a company is due ----------------------------------------------------------------------

NOW = datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
NAIVE_NOW = NOW.replace(tzinfo=None)


def test_the_check_interval_is_twenty_hours() -> None:
    assert FILINGS_CHECK_INTERVAL == timedelta(hours=20)


@pytest.mark.parametrize(
    ("checked_at", "due"),
    [
        (None, True),
        (NAIVE_NOW - timedelta(hours=19, minutes=59), False),
        (NAIVE_NOW - timedelta(hours=20), True),
        (NAIVE_NOW - timedelta(days=3), True),
    ],
)
def test_a_company_is_due_when_never_checked_or_checked_twenty_hours_ago(
    checked_at: datetime | None, due: bool
) -> None:
    assert filings_due(checked_at, NOW) is due


# --- the check on a seeded company --------------------------------------------------------------

Q2 = FilingRef("q2", "10-Q", date(2026, 5, 1), date(2026, 3, 28))
Q3 = FilingRef("q3", "10-Q", date(2026, 7, 31), date(2026, 6, 27))
FY = FilingRef("fy", "10-K", date(2026, 10, 30), date(2026, 9, 26))
Q1 = FilingRef("q1-next", "10-Q", date(2027, 1, 29), None)


def _company(session: Session, ticker: str = "AAA", *, cik: str | None = "0000000001") -> Company:
    company = Company(
        ticker=ticker,
        cik=cik,
        name=ticker,
        fiscal_year_end_month=9,
        currency="USD",
        source="sec" if cik else "manual",
    )
    session.add(company)
    session.flush()
    for ref in (Q2, Q3):  # the stored filings: Q2 and Q3 are loaded, the 10-K is not
        session.add(
            Filing(
                company_id=company.id,
                accession_no=f"{ticker}-{ref.accession_no}",
                form=ref.form,
                filed_at=ref.filed_at,
                period_end=ref.period_end,
            )
        )
    session.commit()
    return company


def _stored(ticker: str, ref: FilingRef) -> FilingRef:
    return FilingRef(f"{ticker}-{ref.accession_no}", ref.form, ref.filed_at, ref.period_end)


def _rows(session: Session, company: Company) -> list[tuple[str, str, date, date | None]]:
    session.expire_all()
    return [
        (r.accession_no, r.form, r.filed_at, r.period_end)
        for r in for_companies(session, [company.id])[company.id]
    ]


def test_a_check_marks_the_unseen_10_k_and_records_when_it_ran(db_session: Session) -> None:
    company = _company(db_session)
    source = FakeSubmissions({"AAA": [FY, _stored("AAA", Q3), _stored("AAA", Q2)]})

    assert check_company(db_session, source, company, NOW) == 1

    assert _rows(db_session, company) == [("fy", "10-K", date(2026, 10, 30), date(2026, 9, 26))]
    assert company.filings_checked_at == NAIVE_NOW
    row = db_session.execute(select(PendingFiling)).scalar_one()
    assert row.detected_at == NAIVE_NOW


def test_a_second_check_keeps_the_row_as_it_was_detected(db_session: Session) -> None:
    company = _company(db_session)
    source = FakeSubmissions({"AAA": [FY, _stored("AAA", Q3)]})
    check_company(db_session, source, company, NOW)
    first = db_session.execute(select(PendingFiling)).scalar_one()
    first_id = first.id

    later = NOW + timedelta(days=1)
    assert check_company(db_session, source, company, later) == 1

    db_session.expire_all()
    again = db_session.execute(select(PendingFiling)).scalar_one()
    assert (again.id, again.detected_at) == (first_id, NAIVE_NOW)
    assert company.filings_checked_at == later.replace(tzinfo=None)


def test_a_ref_that_is_no_longer_unseen_is_deleted_and_a_new_one_added(
    db_session: Session,
) -> None:
    company = _company(db_session)
    check_company(db_session, FakeSubmissions({"AAA": [FY]}), company, NOW)

    # The 10-K is gone from the index (withdrawn), a newer 10-Q is listed.
    assert check_company(db_session, FakeSubmissions({"AAA": [Q1]}), company, NOW) == 1

    assert [row[0] for row in _rows(db_session, company)] == ["q1-next"]


def test_pending_rows_are_newest_first_and_every_asked_company_has_a_list(
    db_session: Session,
) -> None:
    company = _company(db_session)
    other = _company(db_session, "BBB", cik="0000000002")
    check_company(db_session, FakeSubmissions({"AAA": [FY, Q1]}), company, NOW)

    found = for_companies(db_session, [company.id, other.id])

    assert [r.accession_no for r in found[company.id]] == ["q1-next", "fy"]
    assert found[other.id] == []
    assert for_companies(db_session, []) == {}


def test_a_manual_company_is_skipped_with_no_call(db_session: Session) -> None:
    company = _company(db_session, "MAN", cik=None)
    source = FakeSubmissions({"MAN": [FY]})

    assert check_company(db_session, source, company, NOW) == 0

    assert source.calls == []
    assert company.filings_checked_at is None


def test_an_unavailable_index_is_raised_with_nothing_written(db_session: Session) -> None:
    company = _company(db_session)
    check_company(db_session, FakeSubmissions({"AAA": [FY]}), company, NOW)

    with pytest.raises(SourceUnavailable):
        check_company(
            db_session,
            FakeSubmissions(raises=SourceUnavailable("down")),
            company,
            NOW + timedelta(days=1),
        )

    db_session.rollback()
    assert [row[0] for row in _rows(db_session, company)] == ["fy"]
    assert company.filings_checked_at == NAIVE_NOW


# --- every due company --------------------------------------------------------------------------


def test_check_all_checks_every_due_sec_company_in_ticker_order(db_session: Session) -> None:
    late = _company(db_session, "ZZZ", cik="0000000003")
    early = _company(db_session, "AAA")
    fresh = _company(db_session, "MMM", cik="0000000004")
    fresh.filings_checked_at = NAIVE_NOW - timedelta(hours=1)
    _company(db_session, "MAN", cik=None)
    db_session.commit()
    source = FakeSubmissions({"AAA": [FY], "ZZZ": [FilingRef("zfy", "10-K", FY.filed_at, None)]})

    assert check_all(db_session, source, NOW) == []

    assert source.calls == ["AAA", "ZZZ"]
    found = for_companies(db_session, [early.id, late.id, fresh.id])
    assert [len(found[c.id]) for c in (early, late, fresh)] == [1, 1, 0]


@pytest.mark.parametrize("error", [SourceUnavailable("down"), SourceNotConfigured("no UA")])
def test_a_failing_company_is_a_warning_and_keeps_its_rows_and_check_time(
    db_session: Session, error: Exception
) -> None:
    company = _company(db_session)
    check_company(db_session, FakeSubmissions({"AAA": [FY]}), company, NOW - timedelta(days=1))

    warnings = check_all(db_session, FakeSubmissions(raises=error), NOW)

    assert warnings == [f"AAA: filings not checked: {error}"]
    assert [row[0] for row in _rows(db_session, company)] == ["fy"]
    assert company.filings_checked_at == NAIVE_NOW - timedelta(days=1)


def test_a_failing_company_does_not_stop_the_others(db_session: Session) -> None:
    _company(db_session)
    other = _company(db_session, "BBB", cik="0000000002")

    class _FailsFirst(FakeSubmissions):
        def recent_filings(self, company: Any) -> list[FilingRef]:
            if company.ticker == "AAA":
                self.calls.append(company.ticker)
                raise SourceUnavailable("down")
            return super().recent_filings(company)

    source = _FailsFirst({"BBB": [FY]})

    assert check_all(db_session, source, NOW) == ["AAA: filings not checked: down"]
    assert len(for_companies(db_session, [other.id])[other.id]) == 1


def test_a_check_adds_no_filing_and_no_fact(db_session: Session) -> None:
    company = _company(db_session)
    before = db_session.execute(select(func.count()).select_from(Filing)).scalar_one()

    check_all(db_session, FakeSubmissions({"AAA": [FY, Q1]}), NOW)

    assert db_session.execute(select(func.count()).select_from(Filing)).scalar_one() == before
    assert len(for_companies(db_session, [company.id])[company.id]) == 2


# --- the refresh clears what it loaded ----------------------------------------------------------

LOADED = FilingRef("0000320193-26-000020", "10-Q", date(2026, 7, 31), date(2026, 6, 27))
NOT_SERVED = FilingRef("0000320193-26-000029", "10-K", date(2026, 10, 30), date(2026, 9, 26))


def _mark_aapl(session: Session) -> Company:
    company = companies_repo.get_by_ticker(session, "AAPL")
    assert company is not None
    # As if the check ran while the 10-Q was not loaded yet: the refresh below stores it.
    session.add_all(
        PendingFiling(
            company_id=company.id,
            accession_no=ref.accession_no,
            form=ref.form,
            filed_at=ref.filed_at,
            period_end=ref.period_end,
            detected_at=NAIVE_NOW,
        )
        for ref in (LOADED, NOT_SERVED)
    )
    session.commit()
    return company


def test_a_refresh_clears_the_filings_it_stored_and_keeps_those_not_served_yet(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _mark_aapl(db_session)

    refresh_company(db_session, fake_sources(), "AAPL", NOW)

    assert [row[0] for row in _rows(db_session, company)] == [NOT_SERVED.accession_no]


def test_a_failed_refresh_clears_nothing(seed_db: Any, db_session: Session) -> None:
    seed_db("AAPL")
    company = _mark_aapl(db_session)
    sources = Sources(edgar=FakeEdgar(fetch_raises=SourceUnavailable("down")), prices=FakePrices())

    with pytest.raises(SourceUnavailable):
        refresh_company(db_session, sources, "AAPL", NOW)

    assert len(_rows(db_session, company)) == 2


def test_check_all_skips_an_archived_company(db_session: Session) -> None:
    archived = _company(db_session, "AAA")
    archived.archived_at = NAIVE_NOW - timedelta(days=3)
    _company(db_session, "BBB", cik="0000000002")
    db_session.commit()
    source = FakeSubmissions({"AAA": [FY], "BBB": [FilingRef("bfy", "10-K", FY.filed_at, None)]})

    assert check_all(db_session, source, NOW) == []

    assert source.calls == ["BBB"]
    assert for_companies(db_session, [archived.id])[archived.id] == []
    assert archived.filings_checked_at is None
