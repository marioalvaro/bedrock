"""The scheduled refreshes (docs/erd/data.md "Scheduled refresh"): prices of every followed
company, and the market series behind the valuation's discount defaults."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import CompanyRef, PricePayload, PriceRow, SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.models.price_daily import PriceDaily
from bedrock.repositories import macro
from bedrock.repositories import prices as prices_repo
from bedrock.services import market as market_service
from bedrock.services.prices import refresh_all_prices

from .fakes import FakeEdgar, FakeMarket, FakePrices
from .seed import follow

D = Decimal
NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)


class FailingFor(FakePrices):
    def __init__(self, ticker: str) -> None:
        super().__init__()
        self.ticker = ticker

    def fetch(self, company: CompanyRef, since: date | None) -> PricePayload:
        if company.ticker == self.ticker:
            raise SourceUnavailable("down")
        return super().fetch(company, since)


def _company(session: Session, ticker: str) -> Company:
    return session.execute(select(Company).where(Company.ticker == ticker)).scalar_one()


# -- prices -------------------------------------------------------------------------------------


def test_every_followed_company_s_prices_are_refreshed_without_edgar(db_session: Session) -> None:
    for ticker in ("AAPL", "MSFT"):
        follow(db_session, FakeEdgar(), ticker)
    edgar = FakeEdgar(raises=AssertionError("EDGAR must not be called"))

    result = refresh_all_prices(db_session, Sources(edgar=edgar, prices=FakePrices()), NOW)

    assert set(result.new_prices) == {"AAPL", "MSFT"}
    assert all(n > 0 for n in result.new_prices.values()) and result.warnings == []
    for ticker in ("AAPL", "MSFT"):
        company = _company(db_session, ticker)
        assert prices_repo.last_date(db_session, company.id) is not None
        assert company.last_refreshed_at is None  # a prices-only refresh is not a full refresh


def test_one_company_s_failure_is_a_warning_and_the_others_are_kept(db_session: Session) -> None:
    for ticker in ("AAPL", "MSFT"):
        follow(db_session, FakeEdgar(), ticker)

    result = refresh_all_prices(
        db_session, Sources(edgar=FakeEdgar(), prices=FailingFor("MSFT")), NOW
    )

    assert set(result.new_prices) == {"AAPL"}
    assert result.warnings == ["MSFT: prices not updated: down"]
    assert prices_repo.last_date(db_session, _company(db_session, "AAPL").id) is not None


# -- market series ------------------------------------------------------------------------------


def test_the_market_series_are_stored(db_session: Session) -> None:
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), market=FakeMarket())

    warnings = market_service.refresh_market(db_session, sources, NOW)

    assert warnings == []
    assert macro.latest(db_session, "^TNX") == (date(2026, 10, 8), D("4.25"))
    assert macro.latest(db_session, "DAMODARAN_ERP") == (date(2026, 10, 1), D("4.41"))
    assert len(macro.observations(db_session, "^GSPC")) == 5


def test_a_failing_market_series_is_a_warning_and_the_others_are_stored(
    db_session: Session,
) -> None:
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), market=FakeMarket(fail=("erp",)))

    warnings = market_service.refresh_market(db_session, sources, NOW)

    assert warnings == ["erp not updated: erp is down"]
    assert macro.latest(db_session, "DAMODARAN_ERP") is None
    assert macro.latest(db_session, "^TNX") is not None


def test_without_a_market_source_nothing_is_fetched(db_session: Session) -> None:
    assert market_service.refresh_market(db_session, Sources(FakeEdgar(), FakePrices()), NOW) == []


def test_the_market_is_due_once_a_day(db_session: Session) -> None:
    assert market_service.market_due(db_session, NOW)
    market_service.refresh_market(
        db_session, Sources(FakeEdgar(), FakePrices(), market=FakeMarket()), NOW
    )
    assert not market_service.market_due(db_session, NOW + timedelta(hours=6))
    assert market_service.market_due(db_session, NOW + timedelta(hours=21))


# -- defaults -----------------------------------------------------------------------------------


def _store(session: Session, series_id: str, rows: list[tuple[date, Decimal]]) -> None:
    macro.upsert(session, series_id, series_id, "daily", "test", rows, NOW)
    session.commit()


def test_with_no_stored_market_data_there_are_no_market_defaults(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    assert market_service.discount_defaults(db_session, _company(db_session, "AAPL")) == {}


def test_fred_s_yield_is_preferred_to_the_yield_index(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    _store(db_session, "^TNX", [(date(2026, 10, 8), D("4.30"))])
    _store(db_session, "DGS10", [(date(2026, 10, 7), D("4.20"))])
    _store(db_session, "DAMODARAN_ERP", [(date(2026, 10, 1), D("4.41"))])

    defaults = market_service.discount_defaults(db_session, _company(db_session, "AAPL"))

    assert defaults == {"risk_free_rate": D("0.0420"), "equity_risk_premium": D("0.0441")}


def test_beta_comes_from_the_company_s_adjusted_closes_against_the_index(
    db_session: Session,
) -> None:
    follow(db_session, FakeEdgar(), "AAPL")
    company = _company(db_session, "AAPL")
    db_session.query(PriceDaily).filter(PriceDaily.company_id == company.id).delete()
    # 62 month-ends: the stock moves 1.5x the index each month; the last month is partial.
    index_rows: list[tuple[date, Decimal]] = []
    price_rows: list[PriceRow] = []
    index_level, stock_level = D(1000), D(100)
    for k in range(62):
        y, m = divmod(2021 * 12 + 9 + k - 1, 12)
        day = date(y, m + 1, 28)
        r = [D("0.02"), D("-0.01"), D("0.03"), D("-0.02")][k % 4]
        index_level *= 1 + r
        stock_level *= 1 + D("1.5") * r
        index_rows.append((date(y, m + 1, 1), index_level))
        # A close moved by a split-free dividend gap: beta reads the adjusted close.
        price_rows.append(PriceRow(day, D(1), stock_level, 1))
    prices_repo.insert_new(db_session, company.id, price_rows)
    _store(db_session, "^GSPC", index_rows)

    defaults = market_service.discount_defaults(db_session, company)

    assert defaults == {"beta": D("1.50")}
