"""GET /companies/{ticker}/summary (M7c S6, FR-WS-04; docs/erd/workspace.md "Company summary")."""

from collections.abc import Callable

from fastapi.testclient import TestClient


def test_the_summary_answers_every_block(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL")
    authed_client.get("/api/v1/companies/AAPL/scenarios")  # creates the default scenario
    authed_client.post("/api/v1/companies/AAPL/notes", json={"body_md": "# Thesis\nServices"})

    response = authed_client.get("/api/v1/companies/aapl/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"ticker", "metrics", "flags", "valuation", "notes", "forecast", "warnings"}
    assert body["ticker"] == "AAPL"
    revenue = body["metrics"][0]
    assert set(revenue) == {"code", "label", "unit", "years", "latest", "yoy"}
    assert revenue["code"] == "revenue" and len(revenue["years"]) == 5
    assert set(revenue["years"][0]) == {"fiscal_year", "value"}
    assert [m["code"] for m in body["metrics"]] == [
        "revenue",
        "gross_margin",
        "operating_margin",
        "fcf_margin",
        "roic",
        "eps_diluted",
        "net_debt_to_ebitda",
    ]
    assert body["flags"] and set(body["flags"][0]) == {
        "code",
        "label",
        "severity",
        "value",
        "unit",
        "period_label",
    }
    assert set(body["valuation"]) == {
        "scenario_id",
        "scenario_name",
        "price",
        "price_date",
        "low",
        "high",
        "base",
        "upside",
    }
    [note] = body["notes"]
    assert note["excerpt"] == "Thesis Services" and note["created_at"].endswith("Z")
    forecast = body["forecast"]
    assert set(forecast) == {
        "scenario_id",
        "scenario_name",
        "updated_at",
        "last_snapshot_at",
        "newest_filing_date",
        "stale",
    }
    assert forecast["updated_at"].endswith("Z") and forecast["stale"] is False
    assert body["warnings"] == []


def test_a_company_without_a_scenario_has_null_valuation_and_forecast(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL")

    body = authed_client.get("/api/v1/companies/AAPL/summary").json()

    assert body["valuation"] is None and body["forecast"] is None and body["notes"] == []


def test_an_unknown_ticker_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get("/api/v1/companies/ZZZZ/summary").status_code == 404


def test_the_summary_needs_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/companies/AAPL/summary").status_code == 401
