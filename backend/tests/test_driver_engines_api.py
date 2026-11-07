"""One driver's engines on its whole run, through the API (FR-FCST-07, -08; docs/erd/forecasting.md
"Statistical engines (M6)" → API → driver-engines), on the recorded fixtures."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

D = Decimal


def _url(ticker: str, scenario_id: int, case: str = "base") -> str:
    return f"/api/v1/companies/{ticker}/scenarios/{scenario_id}/cases/{case}/driver-engines"


def _main(client: TestClient, ticker: str) -> int:
    scenarios = client.get(f"/api/v1/companies/{ticker}/scenarios").json()
    return int(next(s["id"] for s in scenarios if s["name"] == "Main"))


def _get(client: TestClient, ticker: str, code: str, case: str = "base") -> Any:
    return client.get(_url(ticker, _main(client, ticker), case), params={"code": code})


@pytest.fixture
def aapl(seed_db: Callable[..., None], authed_client: TestClient) -> TestClient:
    seed_db("AAPL")
    return authed_client


def test_aapl_gross_margin_shows_the_run_and_three_engines(aapl: TestClient) -> None:
    response = _get(aapl, "AAPL", "gross_margin")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["driver_code"] == "gross_margin"
    assert body["label"] == "Gross margin"
    assert body["unit"] == "pct"
    assert body["engine"] == "auto"
    assert body["used"] in ("arima", "ets", "blend")
    assert len(body["history"]) == len(body["history_periods"]) >= 11
    assert body["history_periods"][-1]["label"].startswith("FY")
    n = len(body["forecast_years"])
    assert len(body["forecast_labels"]) == len(body["values"]) == len(body["sources"]) == n
    assert [e["code"] for e in body["engines"]] == ["arima", "ets", "blend"]
    for engine in body["engines"]:
        assert engine["error"] is None, engine["code"]
        for key in ("values", "p05", "p25", "p75", "p95"):
            assert len(engine[key]) == n, (engine["code"], key)
        low, high = D(engine["p05"][0]), D(engine["p95"][0])
        assert low <= D(engine["values"][0]) <= high
        assert engine["holdout_mae"] is not None
    assert D(body["mean"]) > 0
    assert [s["fiscal_period"] for s in body["seasonal"]] == ["Q1", "Q2", "Q3", "Q4"]
    assert abs(sum(D(s["value"]) for s in body["seasonal"])) < D("0.0001")


def test_a_driver_with_too_little_history_reports_each_engines_error(aapl: TestClient) -> None:
    body = _get(aapl, "AAPL", "tax_rate").json()
    short = _get(aapl, "AAPL", "interest_rate").json()  # AAPL has no interest-rate history

    assert short["history"] == []
    assert [e["error"] for e in short["engines"]] == [
        "ARIMA: 0 years of history (needs 8)",
        "ETS: 0 years of history (needs 8)",
        "Blend: 0 years of history (needs 8)",
    ]
    assert all(e["values"] == [] and e["p05"] == [] for e in short["engines"])
    assert D(short["mean"]) > 0  # the M4 default still stands
    assert short["used"] == "mean"
    assert body["engines"][0]["code"] == "arima"


def test_an_unknown_code_is_a_422(aapl: TestClient) -> None:
    response = _get(aapl, "AAPL", "nope")

    assert response.status_code == 422
    assert response.json() == {"detail": "nope is not a driver of the growth method"}


def test_the_case_s_resolved_values_and_sources_are_returned(aapl: TestClient) -> None:
    bull = _get(aapl, "AAPL", "gross_margin", "bull").json()
    base = _get(aapl, "AAPL", "gross_margin", "base").json()

    assert set(base["sources"]) == {"engine"}
    assert set(bull["sources"]) == {"offset"}
    assert [D(b) - D(a) for a, b in zip(base["values"], bull["values"], strict=True)] == [
        D("0.01")
    ] * len(base["values"])


def test_unknown_scenario_and_case(aapl: TestClient) -> None:
    assert aapl.get(_url("AAPL", 999_999), params={"code": "gross_margin"}).status_code == 404
    bad_case = aapl.get(_url("AAPL", _main(aapl, "AAPL"), "worst"), params={"code": "gross_margin"})
    assert bad_case.status_code == 422


def test_a_code_with_a_colon_travels_in_the_query(aapl: TestClient) -> None:
    response = _get(aapl, "AAPL", "segment:business:Services")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "segment:business:Services is not a driver of the growth method"
    }
