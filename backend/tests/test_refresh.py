"""refresh_company: the use-case behind `POST /companies/{ticker}/refresh` and `bedrock refresh`."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.parse import parse_companyfacts
from bedrock.ingest.protocol import (
    CompanyRef,
    PricePayload,
    PriceRow,
    SourceNotConfigured,
    SourceUnavailable,
)
from bedrock.ingest.sources import Sources
from bedrock.models.canonical_item import CanonicalItem
from bedrock.models.company import Company
from bedrock.models.concept_mapping import ConceptMapping
from bedrock.models.corporate_action import CorporateAction
from bedrock.models.filing import Filing
from bedrock.models.filing_line import FilingLine
from bedrock.models.price_daily import PriceDaily
from bedrock.models.raw_fact import RawFact
from bedrock.services.companies import CompanyNotFound
from bedrock.services.refresh import refresh_company

from .fakes import FakeEdgar, FakeFilings, FakePrices
from .seed import follow

NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)
LATER = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
AAPL = CompanyRef("AAPL", "0000320193")


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _sources(edgar: FakeEdgar | None = None, prices: FakePrices | None = None) -> Sources:
    return Sources(edgar=edgar or FakeEdgar(), prices=prices or FakePrices())


def test_refresh_stores_filings_facts_and_prices_and_reports_the_counts(
    db_session: Session,
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    expected = parse_companyfacts(FakeEdgar().fetch(AAPL, None).companyfacts)

    result = refresh_company(db_session, _sources(), "AAPL", NOW)

    assert result.ticker == "AAPL"
    assert result.new_filings == len(expected.filings) == _count(db_session, Filing)
    assert result.new_facts == len(expected.facts) == _count(db_session, RawFact)
    assert result.new_prices == len(FakePrices().fetch(AAPL, None).rows)
    assert result.new_prices == _count(db_session, PriceDaily)
    assert result.warnings == []


def test_refresh_syncs_the_canonical_items_and_the_mappings_of_the_followed_companies(
    db_session: Session,
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")

    refresh_company(db_session, _sources(), "AAPL", NOW)

    assert _count(db_session, CanonicalItem) == 95
    overrides = db_session.execute(
        select(ConceptMapping.concept).where(ConceptMapping.company_id.is_not(None))
    ).scalars()
    assert "CommonStockValue" in set(overrides)  # Apple's override


def test_a_second_refresh_inserts_nothing_new(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(), "AAPL", NOW)
    facts, prices = _count(db_session, RawFact), _count(db_session, PriceDaily)

    again = refresh_company(db_session, _sources(), "AAPL", LATER)

    assert (again.new_filings, again.new_facts, again.new_prices, again.new_splits) == (0, 0, 0, 0)
    assert _count(db_session, RawFact) == facts
    assert _count(db_session, PriceDaily) == prices


def test_refresh_sets_the_time_it_was_given_as_utc(db_session: Session) -> None:
    company = follow(db_session, FakeEdgar(), "AAPL")

    result = refresh_company(db_session, _sources(), "AAPL", NOW)

    assert result.last_refreshed_at == NOW
    db_session.refresh(company)
    assert company.last_refreshed_at == datetime(2026, 10, 8, 14, 30)  # naive UTC in SQLite


def test_a_price_failure_is_a_warning_and_the_filings_are_still_stored(
    db_session: Session,
) -> None:
    company = follow(db_session, FakeEdgar(), "AAPL")
    prices = FakePrices(raises=SourceUnavailable("yfinance AAPL: rate limited"))

    result = refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)

    assert (result.new_prices, result.new_splits) == (0, 0)
    assert _count(db_session, CorporateAction) == 0
    assert len(result.warnings) == 1 and "rate limited" in result.warnings[0]
    assert result.new_facts > 0
    db_session.refresh(company)
    assert company.last_refreshed_at is not None


@pytest.mark.parametrize("error", [SourceUnavailable("down"), SourceNotConfigured("no UA")])
def test_an_edgar_failure_is_raised_and_leaves_nothing_behind(
    db_session: Session, error: Exception
) -> None:
    company = follow(db_session, FakeEdgar(), "AAPL")

    with pytest.raises(type(error)):
        refresh_company(db_session, _sources(FakeEdgar(fetch_raises=error)), "AAPL", NOW)

    assert _count(db_session, CanonicalItem) == 0  # the mapping sync was rolled back too
    assert _count(db_session, RawFact) == 0
    db_session.refresh(company)
    assert company.last_refreshed_at is None


def test_refreshing_a_company_that_is_not_followed_is_an_error(db_session: Session) -> None:
    with pytest.raises(CompanyNotFound):
        refresh_company(db_session, _sources(), "AAPL", NOW)


def test_the_ticker_is_case_insensitive(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")

    assert refresh_company(db_session, _sources(), "aapl", NOW).ticker == "AAPL"
    assert db_session.execute(select(Company.ticker)).scalar_one() == "AAPL"


def test_prices_are_asked_for_from_the_last_stored_day_on(db_session: Session) -> None:
    # The last stored day is fetched again: during the session it was a provisional close.
    prices = FakePrices()
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)
    last = max(r.date for r in FakePrices().fetch(AAPL, None).rows)

    refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)

    assert prices.calls == [None, last - timedelta(days=1)]


class MovingPrices(FakePrices):
    """The recorded prices, with the last day's close moved: a later quote of the same day."""

    def fetch(self, company: CompanyRef, since: date | None) -> PricePayload:
        payload = super().fetch(company, since)
        last = max(r.date for r in _all_rows())
        rows = [
            replace(r, close=r.close + 1, adj_close=r.adj_close + 1) if r.date == last else r
            for r in payload.rows
        ]
        return replace(payload, rows=rows)


def _all_rows() -> list[PriceRow]:
    return FakePrices().fetch(AAPL, None).rows


def test_a_later_refresh_the_same_day_updates_that_day_s_close(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(), "AAPL", NOW)
    last = max(_all_rows(), key=lambda r: r.date)
    same_day = datetime(last.date.year, last.date.month, last.date.day, 20, 0, tzinfo=UTC)

    result = refresh_company(db_session, _sources(prices=MovingPrices()), "AAPL", same_day)

    stored = db_session.get(PriceDaily, (_company_id(db_session), last.date))
    assert stored is not None and stored.close == last.close + 1
    assert result.new_prices == 0 and result.warnings == []


def _company_id(session: Session) -> int:
    return session.execute(select(Company.id)).scalar_one()


def test_refresh_stores_the_split_history(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")

    result = refresh_company(db_session, _sources(), "AAPL", NOW)

    recorded = FakePrices().fetch(AAPL, None).splits
    assert len(recorded) >= 2
    assert result.new_splits == len(recorded) == _count(db_session, CorporateAction)
    stored = db_session.execute(select(CorporateAction.effective_date)).scalars()
    assert set(stored) == {s.effective_date for s in recorded}


def test_splits_come_with_every_price_fetch_and_a_second_refresh_adds_none(
    db_session: Session,
) -> None:
    prices = FakePrices()
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)

    again = refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)

    assert prices.calls[1] is not None  # an incremental fetch still carries the full history
    assert again.new_splits == 0


# --- filing-level XBRL (M7b S6) -----------------------------------------------------------------

AAPL_FY2024_10K = "0000320193-24-000123"  # recorded under fixtures/edgar/filings/


def _with_filings(filings: FakeFilings) -> Sources:
    return Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=filings)


def _mark_newer_filings_tried(session: Session, accession: str) -> None:
    """So the four newest untried filings start at the recorded one."""
    filed = session.execute(
        select(Filing.filed_at).where(Filing.accession_no == accession)
    ).scalar_one()
    for filing in session.execute(select(Filing).where(Filing.filed_at > filed)).scalars():
        filing.xbrl_status = "absent"
    session.commit()


def test_refresh_reads_the_four_newest_filings_not_tried_and_counts_their_lines(
    db_session: Session,
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(), "AAPL", NOW)
    _mark_newer_filings_tried(db_session, AAPL_FY2024_10K)
    filings = FakeFilings()

    result = refresh_company(db_session, _with_filings(filings), "AAPL", LATER)

    assert len(filings.calls) == 4 and filings.calls[0] == AAPL_FY2024_10K
    assert result.new_filing_lines == _count(db_session, FilingLine) > 0
    assert result.warnings == []


def test_a_first_load_reads_the_newest_four_filings(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    filings = FakeFilings()

    result = refresh_company(db_session, _with_filings(filings), "AAPL", NOW)

    assert len(filings.calls) == 4
    assert result.new_filing_lines == 0  # the four newest recorded filings are not on disk


def test_a_filings_failure_is_a_warning_and_the_companyfacts_are_kept(
    db_session: Session,
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(), "AAPL", NOW)
    _mark_newer_filings_tried(db_session, AAPL_FY2024_10K)
    failing = FakeFilings(fail={AAPL_FY2024_10K: SourceUnavailable("HTTP 503")})

    result = refresh_company(db_session, _with_filings(failing), "AAPL", LATER)

    assert len(result.warnings) == 1 and AAPL_FY2024_10K in result.warnings[0]
    assert _count(db_session, RawFact) > 0


def test_a_filings_source_that_is_not_configured_is_a_warning(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    filings = FakeFilings()
    filings.raises = SourceNotConfigured("SEC_USER_AGENT is not set")

    result = refresh_company(db_session, _with_filings(filings), "AAPL", NOW)

    assert result.warnings == ["filings not read: SEC_USER_AGENT is not set"]
    assert result.new_facts == _count(db_session, RawFact) > 0


def test_without_a_filings_source_refresh_tries_no_filing(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")

    result = refresh_company(db_session, _sources(), "AAPL", NOW)

    assert result.new_filing_lines == 0
    assert _count(db_session, FilingLine) == 0
    assert (
        db_session.execute(
            select(func.count()).select_from(Filing).where(Filing.xbrl_status.is_not(None))
        ).scalar_one()
        == 0
    )


def test_an_unexpected_filings_error_is_a_warning_after_the_refresh_is_stored(
    db_session: Session,
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    filings = FakeFilings()
    filings.raises = RuntimeError("disk full")

    result = refresh_company(db_session, _with_filings(filings), "AAPL", NOW)

    assert result.warnings == ["filings not read: disk full"]
    assert result.new_facts == _count(db_session, RawFact) > 0
