"""Point-in-time backtests through the API (FR-ACC-02, -03; docs/erd/accountability.md "Backtest",
"API"), on the recorded fixtures."""

from collections.abc import Callable, Generator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from bedrock.forecast.engine_defaults import ENGINE_CODES

from .accountability_data import withhold_filings
from .valuation_api import main_id, scenarios_url

API = "/api/v1/companies"
D = Decimal


def url(ticker: str = "AAPL") -> str:
    return f"{API}/{ticker}/backtest"


def run(client: TestClient, ticker: str = "AAPL") -> dict[str, Any]:
    response = client.post(url(ticker))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def runs_stored(session: Session, kind: str = "backtest") -> int:
    session.rollback()
    query = text("SELECT count(*) FROM forecast_run WHERE kind = :kind")
    return int(session.execute(query, {"kind": kind}).scalar_one())


@pytest.fixture
def aapl(seed_db: Callable[..., None], authed_client: TestClient) -> TestClient:
    seed_db("AAPL")
    return authed_client


@pytest.fixture
def session(app: FastAPI, aapl: TestClient) -> Generator[Session, None, None]:
    with app.state.session_factory() as opened:
        yield opened


def test_the_routes_require_a_session(aapl: TestClient) -> None:
    aapl.cookies.clear()

    assert aapl.get(url()).status_code == 401
    assert aapl.post(url()).status_code == 401


def test_before_a_run_there_is_nothing(aapl: TestClient) -> None:
    assert aapl.get(url()).json() == {
        "ran_at": None,
        "stale": False,
        "origins": [],
        "summary": [],
    }


def test_a_run_stores_ten_origins_of_six_methods_and_a_rerun_replaces_them(
    aapl: TestClient, session: Session
) -> None:
    body = run(aapl)

    assert body["ran_at"] is not None and body["stale"] is False
    assert len(body["origins"]) == 10
    dates = [o["as_of_date"] for o in body["origins"]]
    assert dates == sorted(dates)
    for origin in body["origins"]:
        assert [r["method"] for r in origin["runs"]] == list(ENGINE_CODES)
        assert all(r["error"] is None for r in origin["runs"])
    assert runs_stored(session) == 60
    for method in ENGINE_CODES:
        revenue = [
            r
            for r in body["summary"]
            if (r["kind"], r["code"], r["method"], r["freq"])
            == ("line", "revenue", method, "annual")
        ]
        assert [r["horizon"] for r in revenue] == [1, 2, 3, 4, 5], method
        first = revenue[0]
        assert (first["label"], first["unit"]) == ("Revenue", "USD")
        assert first["n"] == 10  # every origin's first year has an actual by now
        assert D(first["mape"]) > 0
        assert first["hit_rate"] is None and first["n_range"] == 0  # no line range before M8
    # AAPL's 2020 split lies after the first five origins: the forecasts' shares are already
    # today's, so scoring must not restate them from the origin (they would read as a 75% miss).
    eps = next(
        r
        for r in body["summary"]
        if (r["code"], r["method"], r["freq"], r["horizon"]) == ("eps_diluted", "auto", "annual", 1)
    )
    assert D(eps["mape"]) < D("0.3")
    assert aapl.get(url()).json() == body

    again = run(aapl)

    assert runs_stored(session) == 60
    assert [o["as_of_date"] for o in again["origins"]] == dates


def test_stale_goes_true_when_a_newer_10k_is_present(aapl: TestClient, session: Session) -> None:
    restore = withhold_filings(session, date(2024, 11, 1))
    assert run(aapl)["stale"] is False

    restore()

    assert aapl.get(url()).json()["stale"] is True


def test_a_snapshot_survives_a_rerun(aapl: TestClient, session: Session) -> None:
    main = main_id(aapl)
    created = aapl.post(f"{scenarios_url('AAPL')}/{main}/snapshots", json={}).json()

    run(aapl)
    run(aapl)

    assert runs_stored(session, "snapshot") == 3
    detail = aapl.get(f"{API}/AAPL/snapshots/{created['id']}").json()
    assert all(c["lines"] for c in detail["cases"])


def test_a_manual_company_has_nothing_to_back_test(authed_client: TestClient) -> None:
    company = {"ticker": "ACME", "name": "Acme Corp", "fiscal_year_end_month": 12}
    assert authed_client.post(f"{API}/manual", json=company).status_code == 201

    response = authed_client.post(url("ACME"))

    assert response.status_code == 422
    assert response.json()["detail"] == "No 10-K filings to back-test"


def test_de_origins_from_2020_are_listed_with_their_error_and_the_rest_scored(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("DE")

    body = run(authed_client, "DE")

    early = [o for o in body["origins"] if o["as_of_date"] < "2020"]
    late = [o for o in body["origins"] if o["as_of_date"] >= "2020"]
    assert early and late
    assert all(r["error"] is None for o in early for r in o["runs"])
    assert all("gross_margin" in r["error"] for o in late for r in o["runs"])
    assert any(r["code"] == "revenue" and r["n"] > 0 for r in body["summary"])
