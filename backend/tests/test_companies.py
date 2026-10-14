from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import CompanyRef, SourceNotConfigured, SourceUnavailable
from bedrock.models.company import Company
from bedrock.models.concept_mapping import ConceptMapping
from bedrock.models.filing import Filing
from bedrock.models.price_daily import PriceDaily
from bedrock.models.raw_fact import RawFact

from .fakes import FakeEdgar, FakePrices

AAPL = CompanyRef("AAPL", "0000320193")
STAT_FIELDS = ("price", "price_date", "market_cap", "pe", "ev_ebitda", "revenue_growth")


def _add(client: TestClient, ticker: str = "AAPL") -> dict[str, object]:
    response = client.post("/api/v1/companies", json={"ticker": ticker})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_companies_requires_session(client: TestClient) -> None:
    response = client.get("/api/v1/companies")
    assert response.status_code == 401


def test_companies_empty(authed_client: TestClient) -> None:
    response = authed_client.get("/api/v1/companies")
    assert response.status_code == 200
    assert response.json() == []


def test_companies_returns_seeded_row(authed_client: TestClient, db_session: Session) -> None:
    company = Company(
        ticker="AAPL",
        cik="0000320193",
        name="Apple Inc.",
        fiscal_year_end_month=9,
        currency="USD",
        sic="3571",
        last_refreshed_at=None,
    )
    db_session.add(company)
    db_session.commit()

    response = authed_client.get("/api/v1/companies")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "AAPL"
    assert body[0]["cik"] == "0000320193"
    assert body[0]["name"] == "Apple Inc."
    assert body[0]["fiscal_year_end_month"] == 9
    assert body[0]["currency"] == "USD"
    assert body[0]["sic"] == "3571"
    assert body[0]["last_refreshed_at"] is None
    assert all(body[0][field] is None for field in STAT_FIELDS)  # nothing loaded yet


def test_adding_a_company_returns_it_with_key_stats_and_lists_it(
    authed_client: TestClient,
) -> None:
    body = _add(authed_client)

    assert (body["ticker"], body["cik"], body["name"]) == ("AAPL", "0000320193", "Apple Inc.")
    assert body["fiscal_year_end_month"] == 9
    # Stats are Decimals, sent as strings.
    assert Decimal(str(body["price"])) > 0
    assert Decimal(str(body["market_cap"])) > 0
    assert isinstance(body["pe"], str) and isinstance(body["revenue_growth"], str)
    assert body["price_date"] == FakePrices().fetch(AAPL, None).rows[-1].date.isoformat()
    listed = authed_client.get("/api/v1/companies").json()
    assert [c["ticker"] for c in listed] == ["AAPL"]
    assert listed[0]["market_cap"] == body["market_cap"]


def test_last_refreshed_at_is_sent_as_utc(authed_client: TestClient) -> None:
    # SQLite stores no time zone; without one in the JSON a browser would read it as local time.
    body = _add(authed_client)
    stamp = datetime.fromisoformat(str(body["last_refreshed_at"]))

    assert stamp.utcoffset() == timedelta(0)
    assert abs(datetime.now(stamp.tzinfo) - stamp) < timedelta(minutes=5)
    listed = authed_client.get("/api/v1/companies").json()[0]["last_refreshed_at"]
    assert datetime.fromisoformat(listed).utcoffset() == timedelta(0)


def test_the_ticker_is_normalized(authed_client: TestClient) -> None:
    assert _add(authed_client, " aapl ")["ticker"] == "AAPL"


def test_an_empty_ticker_is_rejected(authed_client: TestClient) -> None:
    assert authed_client.post("/api/v1/companies", json={"ticker": ""}).status_code == 422


def test_adding_an_unknown_ticker_is_a_404_with_the_reason(authed_client: TestClient) -> None:
    response = authed_client.post("/api/v1/companies", json={"ticker": "ZZZZ"})

    assert response.status_code == 404
    assert "ZZZZ" in response.json()["detail"]
    assert authed_client.get("/api/v1/companies").json() == []


def test_adding_a_followed_company_again_is_a_409(authed_client: TestClient) -> None:
    _add(authed_client)

    response = authed_client.post("/api/v1/companies", json={"ticker": "AAPL"})

    assert response.status_code == 409
    assert "AAPL" in response.json()["detail"]


def test_adding_without_a_sec_user_agent_is_a_503(
    authed_client: TestClient, fake_edgar: FakeEdgar
) -> None:
    fake_edgar.raises = SourceNotConfigured("SEC_USER_AGENT is not set")

    response = authed_client.post("/api/v1/companies", json={"ticker": "AAPL"})

    assert response.status_code == 503
    assert "SEC_USER_AGENT" in response.json()["detail"]


def test_an_upstream_failure_is_a_502_and_follows_nothing(
    authed_client: TestClient, fake_edgar: FakeEdgar, db_session: Session
) -> None:
    fake_edgar.fetch_raises = SourceUnavailable("sec.gov returned 500")

    response = authed_client.post("/api/v1/companies", json={"ticker": "AAPL"})

    assert response.status_code == 502
    assert _count(db_session, Company) == 0


def test_get_and_delete_a_followed_company(authed_client: TestClient) -> None:
    _add(authed_client)

    got = authed_client.get("/api/v1/companies/AAPL")
    assert got.status_code == 200 and got.json()["ticker"] == "AAPL"
    assert authed_client.get("/api/v1/companies/aapl").status_code == 200

    assert authed_client.delete("/api/v1/companies/AAPL").status_code == 204
    assert authed_client.get("/api/v1/companies/AAPL").status_code == 404
    assert authed_client.delete("/api/v1/companies/AAPL").status_code == 404


def test_deleting_a_company_removes_its_filings_facts_prices_and_overrides(
    authed_client: TestClient, db_session: Session
) -> None:
    _add(authed_client)
    assert _count(db_session, RawFact) > 0

    authed_client.delete("/api/v1/companies/AAPL")
    db_session.expire_all()

    for model in (Company, Filing, RawFact, PriceDaily):
        assert _count(db_session, model) == 0, model
    overrides = (
        select(func.count())
        .select_from(ConceptMapping)
        .where(ConceptMapping.company_id.is_not(None))
    )
    assert db_session.execute(overrides).scalar_one() == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/v1/companies/AAPL"), ("post", "/api/v1/companies/AAPL/refresh")],
)
def test_an_unfollowed_company_is_a_404(authed_client: TestClient, method: str, path: str) -> None:
    assert authed_client.request(method, path).status_code == 404


def test_refresh_reports_what_it_loaded(authed_client: TestClient) -> None:
    _add(authed_client)

    response = authed_client.post("/api/v1/companies/AAPL/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    keys = ("new_filings", "new_facts", "new_prices", "new_splits")
    assert tuple(body[key] for key in keys) == (0, 0, 0, 0)
    assert body["warnings"] == []
    assert datetime.fromisoformat(body["last_refreshed_at"]).utcoffset() == timedelta(0)


def test_refresh_moves_last_refreshed_at_forward(authed_client: TestClient) -> None:
    first = _add(authed_client)["last_refreshed_at"]

    refreshed = authed_client.post("/api/v1/companies/AAPL/refresh").json()["last_refreshed_at"]

    assert datetime.fromisoformat(refreshed) >= datetime.fromisoformat(str(first))
    assert authed_client.get("/api/v1/companies/AAPL").json()["last_refreshed_at"] == refreshed


def test_a_price_failure_during_refresh_is_a_warning_not_an_error(
    authed_client: TestClient, fake_prices: FakePrices
) -> None:
    _add(authed_client)
    fake_prices.raises = SourceUnavailable("yfinance AAPL: rate limited")

    response = authed_client.post("/api/v1/companies/AAPL/refresh")

    assert response.status_code == 200
    assert "rate limited" in response.json()["warnings"][0]


def test_an_edgar_failure_during_refresh_is_a_502(
    authed_client: TestClient, fake_edgar: FakeEdgar
) -> None:
    _add(authed_client)
    fake_edgar.fetch_raises = SourceUnavailable("down")

    assert authed_client.post("/api/v1/companies/AAPL/refresh").status_code == 502
