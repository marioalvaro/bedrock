from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.models.company import Company


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
