"""refresh_company: the use-case behind `POST /companies/{ticker}/refresh` and `bedrock refresh`."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.parse import parse_companyfacts
from bedrock.ingest.protocol import CompanyRef, SourceNotConfigured, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.canonical_item import CanonicalItem
from bedrock.models.company import Company
from bedrock.models.concept_mapping import ConceptMapping
from bedrock.models.corporate_action import CorporateAction
from bedrock.models.filing import Filing
from bedrock.models.price_daily import PriceDaily
from bedrock.models.raw_fact import RawFact
from bedrock.services.companies import CompanyNotFound
from bedrock.services.refresh import refresh_company

from .fakes import FakeEdgar, FakePrices
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

    assert _count(db_session, CanonicalItem) == 84
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


def test_prices_are_asked_for_only_what_follows_the_last_stored_day(db_session: Session) -> None:
    prices = FakePrices()
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)
    last = max(r.date for r in FakePrices().fetch(AAPL, None).rows)

    refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)

    assert prices.calls == [None, last]


def test_prices_are_not_asked_for_when_the_last_stored_day_is_today(db_session: Session) -> None:
    # yfinance fails for a start date after "now", and there is nothing newer to fetch anyway.
    prices = FakePrices()
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(prices=prices), "AAPL", NOW)
    last = max(r.date for r in FakePrices().fetch(AAPL, None).rows)
    same_day = datetime(last.year, last.month, last.day, 20, 0, tzinfo=UTC)

    result = refresh_company(db_session, _sources(prices=prices), "AAPL", same_day)

    assert prices.calls == [None]
    assert result.new_prices == 0 and result.warnings == []


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


def test_splits_are_not_asked_for_when_prices_are_current_today(db_session: Session) -> None:
    # The splits ride on the price fetch, which is skipped when the last stored day is today.
    follow(db_session, FakeEdgar(), "AAPL")
    refresh_company(db_session, _sources(), "AAPL", NOW)
    last = max(r.date for r in FakePrices().fetch(AAPL, None).rows)
    same_day = datetime(last.year, last.month, last.day, 20, 0, tzinfo=UTC)
    prices = FakePrices()

    result = refresh_company(db_session, _sources(prices=prices), "AAPL", same_day)

    assert prices.calls == []
    assert result.new_splits == 0
