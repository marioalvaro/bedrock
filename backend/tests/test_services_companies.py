"""Following, listing and removing companies."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from bedrock.analysis.multiples import key_stats
from bedrock.ingest.protocol import (
    CompanyProfile,
    CompanyRef,
    SourceNotConfigured,
    SourceUnavailable,
    UnknownTicker,
)
from bedrock.ingest.sources import Sources
from bedrock.models.canonical_item import CanonicalItem
from bedrock.models.company import Company
from bedrock.models.concept_mapping import ConceptMapping
from bedrock.models.corporate_action import CorporateAction
from bedrock.models.filing import Filing
from bedrock.models.pending_filing import PendingFiling
from bedrock.models.price_daily import PriceDaily
from bedrock.models.raw_fact import RawFact
from bedrock.repositories import facts as facts_repo
from bedrock.services.companies import (
    CompanyArchived,
    CompanyExists,
    CompanyNotFound,
    add_company,
    archive_company,
    get_company,
    list_companies,
    remove_company,
)
from bedrock.statements.build import build_statement

from .fakes import FakeEdgar, FakePrices
from .seed import fake_sources
from .statements_pipeline import run_pipeline

NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)
AAPL = CompanyRef("AAPL", "0000320193")
COST = CompanyRef("COST", "0000909832")


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_adding_a_company_follows_it_and_loads_its_data(db_session: Session) -> None:
    view = add_company(db_session, fake_sources(), "aapl", NOW)

    assert (view.company.ticker, view.company.cik) == ("AAPL", "0000320193")
    assert view.company.last_refreshed_at == datetime(2026, 10, 8, 14, 30)
    assert _count(db_session, Filing) > 0 and _count(db_session, PriceDaily) > 0


def test_a_new_company_has_key_stats(db_session: Session) -> None:
    view = add_company(db_session, fake_sources(), "AAPL", NOW)

    last_close = FakePrices().fetch(AAPL, None).rows[-1]
    assert view.stats.price == last_close.close
    assert view.stats.price_date == last_close.date
    assert view.stats.market_cap is not None and view.stats.market_cap > 0
    assert view.stats.pe is not None
    assert view.stats.revenue_growth is not None


def test_the_list_stats_match_stats_from_the_full_statements(db_session: Session) -> None:
    # The list loads only the concepts the stats need; it must not change a number.
    view = add_company(db_session, fake_sources(), "COST", NOW)
    pipeline = run_pipeline("COST")
    price = FakePrices().fetch(COST, None).rows[-1]
    shares = facts_repo.latest_shares_outstanding(db_session, view.company.id)
    assert shares is not None
    ttm = {s: build_statement(pipeline.canonical, pipeline.items, s, "ttm") for s in ("IS", "CF")}

    expected = key_stats(
        close=(price.date, price.close),
        shares=shares.value,
        ttm=ttm,
        quarterly_bs=pipeline.quarterly["BS"],
    )

    assert view.stats == expected
    assert view.stats.ev_ebitda is not None  # Costco maps every input


def test_a_split_after_the_shares_filing_multiplies_the_market_cap(db_session: Session) -> None:
    view = add_company(db_session, fake_sources(), "AAPL", NOW)
    before = view.stats.market_cap
    assert before is not None
    db_session.add(
        CorporateAction(
            company_id=view.company.id,
            type="split",
            effective_date=date(2099, 1, 1),  # after every filing
            ratio=Decimal(2),
            source="test",
        )
    )
    db_session.commit()

    after = get_company(db_session, "AAPL").stats.market_cap

    assert after == before * 2


def test_ev_ebitda_needs_every_input(db_session: Session) -> None:
    # Apple's short-term debt is a summed concept, commercial paper + term debt: every input exists.
    assert add_company(db_session, fake_sources(), "AAPL", NOW).stats.ev_ebitda is not None
    # Microsoft's D&A line is a custom tag that companyfacts omits, so EBITDA is unknown.
    assert add_company(db_session, fake_sources(), "MSFT", NOW).stats.ev_ebitda is None


def test_adding_the_same_company_twice_is_a_conflict_without_any_network_call(
    db_session: Session,
) -> None:
    add_company(db_session, fake_sources(), "AAPL", NOW)
    broken = Sources(
        edgar=FakeEdgar(raises=SourceUnavailable("must not be called")), prices=FakePrices()
    )

    with pytest.raises(CompanyExists):
        add_company(db_session, broken, "AAPL", NOW)


def test_a_second_ticker_of_a_followed_cik_is_a_conflict(db_session: Session) -> None:
    class AliasEdgar(FakeEdgar):
        def resolve(self, ticker: str) -> CompanyProfile:
            return replace(super().resolve("AAPL"), ticker=ticker.upper())

    add_company(db_session, fake_sources(), "AAPL", NOW)

    with pytest.raises(CompanyExists):
        add_company(db_session, Sources(edgar=AliasEdgar(), prices=FakePrices()), "APC", NOW)


def test_an_unknown_ticker_is_not_followed(db_session: Session) -> None:
    with pytest.raises(UnknownTicker):
        add_company(db_session, fake_sources(), "ZZZZ", NOW)

    assert _count(db_session, Company) == 0


@pytest.mark.parametrize("error", [SourceUnavailable("down"), SourceNotConfigured("no UA")])
def test_a_failed_first_load_leaves_no_half_added_company(
    db_session: Session, error: Exception
) -> None:
    sources = Sources(edgar=FakeEdgar(fetch_raises=error), prices=FakePrices())

    with pytest.raises(type(error)):
        add_company(db_session, sources, "AAPL", NOW)

    assert _count(db_session, Company) == 0
    assert _count(db_session, RawFact) == 0
    assert _count(db_session, CanonicalItem) == 0


def test_a_price_failure_does_not_stop_a_company_being_added(db_session: Session) -> None:
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(raises=SourceUnavailable("down")))

    view = add_company(db_session, sources, "AAPL", NOW)

    assert view.stats.price is None and view.stats.market_cap is None
    assert view.stats.revenue_growth is not None


def test_a_followed_company_is_found_whatever_the_case(db_session: Session) -> None:
    add_company(db_session, fake_sources(), "AAPL", NOW)

    assert get_company(db_session, "aapl").company.ticker == "AAPL"
    with pytest.raises(CompanyNotFound):
        get_company(db_session, "MSFT")


def test_the_list_is_ordered_by_ticker_and_carries_each_companys_stats(
    db_session: Session,
) -> None:
    assert list_companies(db_session) == []
    add_company(db_session, fake_sources(), "MSFT", NOW)
    add_company(db_session, fake_sources(), "AAPL", NOW)

    views = list_companies(db_session)

    assert [v.company.ticker for v in views] == ["AAPL", "MSFT"]
    assert all(v.stats.market_cap is not None for v in views)


def test_removing_a_company_removes_all_its_data_and_overrides(db_session: Session) -> None:
    add_company(db_session, fake_sources(), "AAPL", NOW)
    add_company(db_session, fake_sources(), "MSFT", NOW)
    msft_facts = db_session.execute(
        select(func.count()).select_from(RawFact).join(Company).where(Company.ticker == "MSFT")
    ).scalar_one()

    archive_company(db_session, "AAPL", NOW)
    remove_company(db_session, "aapl")

    assert [c for c in db_session.execute(select(Company.ticker)).scalars()] == ["MSFT"]
    assert _count(db_session, RawFact) == msft_facts
    assert (
        _count(db_session, PriceDaily)
        == db_session.execute(
            select(func.count())
            .select_from(PriceDaily)
            .join(Company)
            .where(Company.ticker == "MSFT")
        ).scalar_one()
    )
    msft_id = db_session.execute(select(Company.id)).scalar_one()
    owners = set(
        db_session.execute(
            select(ConceptMapping.company_id).where(ConceptMapping.company_id.is_not(None))
        ).scalars()
    )
    assert owners == {msft_id}  # Microsoft's overrides stay, Apple's are gone


def test_removing_a_company_that_is_not_followed_is_an_error(db_session: Session) -> None:
    with pytest.raises(CompanyNotFound):
        remove_company(db_session, "AAPL")


# --- the new filings on the views (M7c, FR-DATA-23) ---------------------------------------------


def _bare(session: Session, ticker: str, cik: str | None) -> Company:
    company = Company(
        ticker=ticker,
        cik=cik,
        name=ticker,
        fiscal_year_end_month=12,
        currency="USD",
        source="sec" if cik else "manual",
    )
    session.add(company)
    session.flush()
    return company


def _pending(session: Session, company: Company, accession: str, filed: date) -> None:
    session.add(
        PendingFiling(
            company_id=company.id,
            accession_no=accession,
            form="10-Q",
            filed_at=filed,
            period_end=None,
            detected_at=NOW.replace(tzinfo=None),
        )
    )


def test_the_views_carry_each_company_s_new_filings_read_in_one_query(
    db_session: Session,
) -> None:
    first = _bare(db_session, "AAA", "0000000001")
    second = _bare(db_session, "BBB", "0000000002")
    _bare(db_session, "MAN", None)
    _pending(db_session, first, "a-old", date(2026, 7, 31))
    _pending(db_session, first, "a-new", date(2026, 10, 30))
    _pending(db_session, second, "b-1", date(2026, 8, 1))
    db_session.commit()
    statements: list[str] = []

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        views = list_companies(db_session)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    found = {v.company.ticker: [f.accession_no for f in v.new_filings] for v in views}
    assert found == {"AAA": ["a-new", "a-old"], "BBB": ["b-1"], "MAN": []}
    assert sum("FROM pending_filing" in s for s in statements) == 1


def test_one_company_s_view_carries_its_new_filings(db_session: Session) -> None:
    company = _bare(db_session, "AAA", "0000000001")
    _pending(db_session, company, "a-1", date(2026, 10, 30))
    db_session.commit()

    assert [f.accession_no for f in get_company(db_session, "aaa").new_filings] == ["a-1"]


def test_a_share_class_of_an_archived_filer_points_to_the_archived_company(
    db_session: Session,
) -> None:
    # Another ticker of the same filer is archived: restoring it is the way back (FR-WS-07).
    db_session.add(
        Company(
            ticker="AAPL.B",
            cik="0000320193",
            name="Apple Inc.",
            fiscal_year_end_month=9,
            currency="USD",
            archived_at=datetime(2026, 10, 1),
        )
    )
    db_session.commit()

    with pytest.raises(CompanyArchived) as raised:
        add_company(db_session, fake_sources(), "AAPL", NOW)

    assert str(raised.value) == "AAPL.B"
    assert [c.ticker for c in db_session.execute(select(Company)).scalars()] == ["AAPL.B"]
