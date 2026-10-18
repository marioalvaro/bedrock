"""The ratios route over a followed AAPL (recorded fixtures, no network). FR-ANL-01..04."""

import time
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bedrock.ratios.registry import RATIOS

COMPANY = "/api/v1/companies/AAPL"
RATIOS_PATH = f"{COMPANY}/ratios"
ADJUSTMENTS = f"{COMPANY}/adjustments"

SGA_FY2024 = {
    "canonical_code": "sga",
    "fiscal_year": 2024,
    "fiscal_period": "FY",
    "amount": "-1000000000",
    "category": "one-off",
    "reason": "test",
}


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def get_ratios(client: TestClient, **params: str) -> dict[str, Any]:
    response = client.get(RATIOS_PATH, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def value(body: dict[str, Any], code: str, period: str) -> Decimal | None:
    row = next(r for r in body["rows"] if r["code"] == code)
    index = [p["key"] for p in body["periods"]].index(period)
    raw = row["values"][index]
    return None if raw is None else Decimal(raw)


# --- guards ----------------------------------------------------------------------------------


def test_ratios_require_a_session(client: TestClient) -> None:
    assert client.get(RATIOS_PATH, params={"freq": "annual"}).status_code == 401


def test_ratios_of_an_unfollowed_company_are_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(RATIOS_PATH, params={"freq": "annual"}).status_code == 404


@pytest.mark.parametrize(
    "params",
    [{"freq": "quarterly"}, {}, {"freq": "annual", "basis": "adjusted"}],
    ids=["quarterly", "missing-freq", "bad-basis"],
)
def test_bad_query_values_are_a_422(aapl_client: TestClient, params: dict[str, str]) -> None:
    assert aapl_client.get(RATIOS_PATH, params=params).status_code == 422


# --- shape -----------------------------------------------------------------------------------


def test_annual_ratios_have_the_documented_shape(aapl_client: TestClient) -> None:
    body = get_ratios(aapl_client, freq="annual")

    assert set(body) == {"ticker", "freq", "basis", "periods", "rows"}
    assert (body["ticker"], body["freq"], body["basis"]) == ("AAPL", "annual", "reported")
    periods: list[dict[str, Any]] = body["periods"]
    assert len(periods) >= 10
    assert set(periods[0]) == {
        "key",
        "label",
        "fiscal_year",
        "fiscal_period",
        "period_start",
        "period_end",
        "is_forecast",
    }
    rows: list[dict[str, Any]] = body["rows"]
    assert [r["code"] for r in rows] == [r.code for r in RATIOS]
    for row, ratio in zip(rows, RATIOS, strict=True):
        assert set(row) == {"code", "label", "category", "unit", "definition", "caveat", "values"}
        assert (row["label"], row["category"], row["unit"], row["definition"]) == (
            ratio.label,
            ratio.category,
            ratio.unit,
            ratio.definition,
        )
        assert row["caveat"] is None  # AAPL has no caveat
        assert len(row["values"]) == len(periods)
    gross = next(r for r in rows if r["code"] == "gross_margin")["values"]
    assert all(isinstance(v, str) for v in gross)
    assert all(0 < Decimal(v) < 1 for v in gross)


def test_ttm_ratios_are_served_fast_with_a_diluted_eps(aapl_client: TestClient) -> None:
    started = time.perf_counter()
    response = aapl_client.get(RATIOS_PATH, params={"freq": "ttm"})
    elapsed = time.perf_counter() - started

    assert response.status_code == 200, response.text
    assert elapsed < 1.0
    body = response.json()
    assert body["freq"] == "ttm"
    assert all(p["key"].startswith("TTM-") for p in body["periods"])
    eps = value(body, "eps_diluted", body["periods"][-1]["key"])
    assert eps is not None and eps > 0


# --- normalized basis --------------------------------------------------------------------------


def test_an_adjustment_moves_normalized_ratios_only_until_it_is_deleted(
    aapl_client: TestClient,
) -> None:
    reported_before = get_ratios(aapl_client, freq="annual")

    created = aapl_client.post(ADJUSTMENTS, json=SGA_FY2024)
    assert created.status_code == 201, created.text
    reported = get_ratios(aapl_client, freq="annual")
    normalized = get_ratios(aapl_client, freq="annual", basis="normalized")

    assert normalized["basis"] == "normalized"
    assert reported == reported_before
    for code in ("roe", "net_margin"):
        before, after = value(reported, code, "FY2024"), value(normalized, code, "FY2024")
        assert before is not None and after is not None and after > before

    assert aapl_client.delete(f"{ADJUSTMENTS}/{created.json()['id']}").status_code == 204
    restored = get_ratios(aapl_client, freq="annual", basis="normalized")
    assert restored["rows"] == reported["rows"] and restored["periods"] == reported["periods"]
