from fastapi.testclient import TestClient


def _add(client: TestClient, ticker: str = "AAPL") -> None:
    assert client.post("/api/v1/companies", json={"ticker": ticker}).status_code == 201


def test_listing_requires_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/companies/AAPL/corporate-actions").status_code == 401


def test_an_unfollowed_company_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get("/api/v1/companies/AAPL/corporate-actions").status_code == 404


def test_aapl_lists_its_splits_oldest_first(authed_client: TestClient) -> None:
    _add(authed_client)

    response = authed_client.get("/api/v1/companies/aapl/corporate-actions")

    assert response.status_code == 200
    actions = response.json()
    dates = [a["effective_date"] for a in actions]
    assert dates == sorted(dates) and len(dates) == 5
    assert {
        "type": "split",
        "effective_date": "2014-06-09",
        "ratio": "7",
        "source": "yfinance",
    } in actions
    assert {
        "type": "split",
        "effective_date": "2020-08-31",
        "ratio": "4",
        "source": "yfinance",
    } in actions
    assert set(actions[0]) == {"type", "effective_date", "ratio", "source"}


def test_a_refresh_does_not_duplicate_the_actions(authed_client: TestClient) -> None:
    _add(authed_client)
    before = authed_client.get("/api/v1/companies/AAPL/corporate-actions").json()

    authed_client.post("/api/v1/companies/AAPL/refresh")

    assert authed_client.get("/api/v1/companies/AAPL/corporate-actions").json() == before
