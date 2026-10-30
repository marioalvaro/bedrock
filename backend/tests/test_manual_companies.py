"""Manual-only companies (FR-DATA-01, FR-DATA-15): followed without SEC, filled by import."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.repositories import prices as prices_repo
from bedrock.services.companies import (
    CompanyExists,
    add_company,
    add_manual_company,
    get_company,
    remove_company,
)
from bedrock.services.imports import confirm_import
from bedrock.services.refresh import refresh_company
from bedrock.services.statements import mapping_gaps

from .fakes import FakeEdgar, FakePrices
from .import_data import statement_rows, workbook
from .seed import fake_sources

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
FY2024 = (2024, "FY", date(2024, 1, 1), date(2024, 12, 31))
BS_FY2024 = (2024, "FY", None, date(2024, 12, 31))


def _manual(session: Session, ticker: str = "ACME", month: int = 12) -> Company:
    return add_manual_company(session, ticker, "Acme Corp", month, "3571").company


def _no_edgar() -> Sources:
    """EDGAR fails if anything calls it; prices are the recorded ones."""
    return Sources(edgar=FakeEdgar(raises=AssertionError("EDGAR was called")), prices=FakePrices())


def test_a_manual_company_has_no_cik_and_reports_in_usd(db_session: Session) -> None:
    view = add_manual_company(db_session, " acme ", "Acme Corp", 6, None)

    company = view.company
    assert (company.ticker, company.name, company.fiscal_year_end_month) == ("ACME", "Acme Corp", 6)
    assert (company.source, company.cik, company.currency) == ("manual", None, "USD")
    assert company.sic is None and company.last_refreshed_at is None
    assert (view.stats.price, view.stats.market_cap, view.stats.pe) == (None, None, None)


def test_two_manual_companies_can_both_have_no_cik(db_session: Session) -> None:
    _manual(db_session, "ONE")
    _manual(db_session, "TWO")

    assert db_session.execute(select(func.count()).where(Company.cik.is_(None))).scalar() == 2


def test_a_ticker_already_followed_cannot_be_created_again(db_session: Session) -> None:
    _manual(db_session, "ACME")
    add_company(db_session, fake_sources(), "AAPL", NOW)

    with pytest.raises(CompanyExists):
        add_manual_company(db_session, "acme", "Another", 12, None)
    with pytest.raises(CompanyExists):
        add_manual_company(db_session, "AAPL", "Not Apple", 9, None)
    assert db_session.execute(select(func.count()).select_from(Company)).scalar() == 2


def test_a_followed_manual_company_blocks_the_same_ticker_from_sec(db_session: Session) -> None:
    _manual(db_session, "AAPL")

    with pytest.raises(CompanyExists):
        add_company(db_session, fake_sources(), "AAPL", NOW)


def test_removing_a_manual_company_removes_it(db_session: Session) -> None:
    _manual(db_session)

    remove_company(db_session, "ACME")

    assert db_session.execute(select(func.count()).select_from(Company)).scalar() == 0


def test_refresh_never_calls_edgar_and_still_records_prices(db_session: Session) -> None:
    # COST has recorded prices; the company is manual, so its EDGAR facts are not fetched.
    company = _manual(db_session, "COST")

    result = refresh_company(db_session, _no_edgar(), "COST", NOW)

    assert (result.new_filings, result.new_facts) == (0, 0)
    assert result.new_prices > 100 and result.warnings == []
    assert prices_repo.latest_close(db_session, company.id) is not None
    assert company.last_refreshed_at == NOW.replace(tzinfo=None)


def test_a_price_failure_is_a_warning_on_a_manual_company(db_session: Session) -> None:
    company = _manual(db_session)
    sources = Sources(
        edgar=FakeEdgar(raises=AssertionError("EDGAR was called")),
        prices=FakePrices(raises=SourceUnavailable("yfinance down")),
    )

    result = refresh_company(db_session, sources, "ACME", NOW)

    assert [w.startswith("prices and splits not updated") for w in result.warnings] == [True]
    assert company.last_refreshed_at == NOW.replace(tzinfo=None)


def test_a_ticker_the_price_source_does_not_know_has_no_prices(db_session: Session) -> None:
    company = _manual(db_session, "NOPRICES")

    result = refresh_company(db_session, _no_edgar(), "NOPRICES", NOW)

    assert (result.new_prices, result.new_splits, result.warnings) == (0, 0, [])
    assert prices_repo.latest_close(db_session, company.id) is None


def test_key_stats_use_the_balance_sheet_share_count(db_session: Session) -> None:
    company = _manual(db_session, "COST")
    refresh_company(db_session, _no_edgar(), "COST", NOW)
    _, close = prices_repo.latest_close(db_session, company.id)  # type: ignore[misc]
    book = workbook(
        {
            "IS": statement_rows([FY2024], {"revenue": [5_000_000]}),
            "BS": statement_rows([BS_FY2024], {"shares_outstanding": [2_000_000]}),
        },
        scale="units",
    )
    confirm_import(db_session, company, book, "acme.xlsx", None, NOW)

    stats = get_company(db_session, "COST").stats

    assert stats.price == close
    assert stats.market_cap == (close * Decimal(2_000_000)).quantize(Decimal("0.01"))


def test_key_stats_have_no_market_cap_without_a_share_count(db_session: Session) -> None:
    company = _manual(db_session, "COST")
    refresh_company(db_session, _no_edgar(), "COST", NOW)
    book = workbook({"IS": statement_rows([FY2024], {"revenue": [5_000_000]})}, scale="units")
    confirm_import(db_session, company, book, "acme.xlsx", None, NOW)

    stats = get_company(db_session, "COST").stats

    assert stats.price is not None and stats.market_cap is None


def test_data_gaps_of_a_manual_company_list_no_unmapped_concepts(db_session: Session) -> None:
    company = _manual(db_session)
    book = workbook({"IS": statement_rows([FY2024], {"revenue": [5_000_000]})}, scale="units")
    confirm_import(db_session, company, book, "acme.xlsx", None, NOW)

    gaps = mapping_gaps(db_session, company)

    assert gaps.unmapped_concepts == []
    assert "revenue" not in {m.code for m in gaps.missing_items}
    assert "cost_of_revenue" in {m.code for m in gaps.missing_items}


def test_the_api_creates_a_manual_company(authed_client: TestClient) -> None:
    response = authed_client.post(
        "/api/v1/companies/manual",
        json={"ticker": "acme", "name": "Acme Corp", "fiscal_year_end_month": 6, "sic": "3571"},
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["ticker"], body["name"], body["cik"], body["source"]) == (
        "ACME",
        "Acme Corp",
        None,
        "manual",
    )
    assert (body["fiscal_year_end_month"], body["currency"], body["sic"]) == (6, "USD", "3571")
    assert body["market_cap"] is None and body["last_refreshed_at"] is None
    assert authed_client.get("/api/v1/companies/ACME").json() == body
    assert [c["ticker"] for c in authed_client.get("/api/v1/companies").json()] == ["ACME"]


def test_the_api_rejects_a_ticker_that_is_already_followed(authed_client: TestClient) -> None:
    body = {"ticker": "ACME", "name": "Acme Corp", "fiscal_year_end_month": 12}
    assert authed_client.post("/api/v1/companies/manual", json=body).status_code == 201

    response = authed_client.post("/api/v1/companies/manual", json=body)

    assert response.status_code == 409
    assert "ACME" in response.json()["detail"]


@pytest.mark.parametrize(
    "change",
    [
        {"ticker": "  "},
        {"ticker": "TOOLONGTICKER1"},
        {"name": " "},
        {"fiscal_year_end_month": 0},
        {"fiscal_year_end_month": 13},
        {"sic": "35"},
        {"sic": "abcd"},
    ],
)
def test_the_api_validates_a_manual_company(authed_client: TestClient, change: dict) -> None:
    body = {"ticker": "ACME", "name": "Acme Corp", "fiscal_year_end_month": 12, **change}

    assert authed_client.post("/api/v1/companies/manual", json=body).status_code == 422


def test_a_manual_company_with_no_data_serves_empty_statements_and_refreshes(
    authed_client: TestClient,
) -> None:
    body = {"ticker": "ACME", "name": "Acme Corp", "fiscal_year_end_month": 12}
    authed_client.post("/api/v1/companies/manual", json=body)

    statements = authed_client.get("/api/v1/companies/ACME/statements?type=IS&freq=annual")
    refresh = authed_client.post("/api/v1/companies/ACME/refresh")

    assert statements.status_code == 200 and statements.json()["periods"] == []
    assert refresh.status_code == 200 and refresh.json()["new_facts"] == 0
