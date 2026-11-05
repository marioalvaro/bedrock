"""The capital-allocation route over a followed AAPL (recorded fixtures, no network).
FR-ANL-06."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

COMPANY = "/api/v1/companies/AAPL"
CAPITAL = f"{COMPANY}/capital-allocation"

ROWS = [
    ("cfo", "USD", False),
    ("free_cash_flow", "USD", False),
    ("capex", "USD", True),
    ("d_and_a", "USD", False),
    ("capex_to_da", "x", False),
    ("acquisitions", "USD", True),
    ("buybacks", "USD", True),
    ("dividends_paid", "USD", True),
    ("shareholder_returns", "USD", True),
    ("net_share_change", "pct", False),
]


@pytest.fixture
def aapl_db(seed_db: Callable[..., None]) -> None:
    seed_db("AAPL")


@pytest.fixture
def aapl_client(aapl_db: None, authed_client: TestClient) -> TestClient:
    return authed_client


def get_capital(client: TestClient, freq: str = "annual") -> dict[str, Any]:
    response = client.get(CAPITAL, params={"freq": freq})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def row(body: dict[str, Any], code: str) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in body["rows"] if r["code"] == code)
    return found


def at(values: list[str | None], index: int) -> Decimal | None:
    raw = values[index]
    return None if raw is None else Decimal(raw)


# --- guards ----------------------------------------------------------------------------------


def test_capital_allocation_requires_a_session(client: TestClient) -> None:
    assert client.get(CAPITAL, params={"freq": "annual"}).status_code == 401


def test_capital_allocation_of_an_unfollowed_company_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(CAPITAL, params={"freq": "annual"}).status_code == 404


@pytest.mark.parametrize("params", [{"freq": "quarterly"}, {}], ids=["quarterly", "missing-freq"])
def test_bad_freq_is_a_422(aapl_client: TestClient, params: dict[str, str]) -> None:
    assert aapl_client.get(CAPITAL, params=params).status_code == 422


# --- shape -----------------------------------------------------------------------------------


def assert_shape(body: dict[str, Any]) -> None:
    n = len(body["periods"])
    assert n > 0
    assert [(r["code"], r["unit"]) for r in body["rows"]] == [(c, u) for c, u, _ in ROWS]
    for r, (_, _, pct) in zip(body["rows"], ROWS, strict=True):
        assert set(r) == {"code", "label", "unit", "values", "pct_of_cfo", "pct_of_fcf"}
        assert isinstance(r["label"], str) and r["label"]
        assert len(r["values"]) == n
        if pct:
            assert len(r["pct_of_cfo"]) == n and len(r["pct_of_fcf"]) == n
        else:
            assert r["pct_of_cfo"] is None and r["pct_of_fcf"] is None


def test_annual_capital_allocation_has_the_documented_shape(aapl_client: TestClient) -> None:
    body = get_capital(aapl_client)

    assert set(body) == {"ticker", "freq", "periods", "rows"}
    assert (body["ticker"], body["freq"]) == ("AAPL", "annual")
    assert all(p["fiscal_period"] == "FY" for p in body["periods"])
    assert_shape(body)


def test_ttm_capital_allocation_is_served(aapl_client: TestClient) -> None:
    body = get_capital(aapl_client, freq="ttm")

    assert body["freq"] == "ttm"
    assert all(p["key"].startswith("TTM-") for p in body["periods"])
    assert_shape(body)
    latest = len(body["periods"]) - 1
    buybacks = row(body, "buybacks")
    # TTM-FY2026Q3: buybacks -82,226,000,000 over FCF 136,683,000,000 = 0.6015817... by hand
    assert body["periods"][latest]["key"] == "TTM-FY2026Q3"
    assert buybacks["values"][latest] == "-82226000000"
    assert row(body, "free_cash_flow")["values"][latest] == "136683000000"
    assert buybacks["pct_of_fcf"][latest] == "0.601582"


# --- values ----------------------------------------------------------------------------------


def test_aapl_buybacks_are_outflows_and_a_positive_share_of_fcf(aapl_client: TestClient) -> None:
    body = get_capital(aapl_client)
    buybacks = row(body, "buybacks")
    fcf = row(body, "free_cash_flow")["values"]
    latest = len(body["periods"]) - 1

    # AAPL bought back nothing before its 2012 program; every later year is an outflow.
    years = [p["fiscal_year"] for p in body["periods"]]
    judged = [(y, Decimal(v)) for y, v in zip(years, buybacks["values"], strict=True) if v]
    assert all(v <= 0 for _, v in judged)
    assert [v for y, v in judged if y >= 2013] and all(v < 0 for y, v in judged if y >= 2013)
    value, base = at(buybacks["values"], latest), at(fcf, latest)
    share = at(buybacks["pct_of_fcf"], latest)
    assert value is not None and base is not None and share is not None
    assert share > 0
    # FY2025: buybacks -90,711,000,000 over FCF 98,767,000,000 = 0.9184343... by hand
    assert body["periods"][latest]["key"] == "FY2025"
    assert (value, base) == (Decimal("-90711000000"), Decimal("98767000000"))
    assert share == Decimal("0.918434")


def test_aapl_share_count_has_no_split_jump(aapl_client: TestClient) -> None:
    body = get_capital(aapl_client)
    keys = [p["key"] for p in body["periods"]]
    change = row(body, "net_share_change")["values"]

    for key in ("FY2020", "FY2021"):
        value = at(change, keys.index(key))
        assert value is not None and abs(value) < Decimal("0.1"), key


# --- reported basis --------------------------------------------------------------------------


CAPEX_FY2024 = {
    "canonical_code": "capex",
    "fiscal_year": 2024,
    "fiscal_period": "FY",
    "amount": "-5000000000",
    "category": "one-off",
    "reason": "test",
}


def test_capital_allocation_ignores_adjustments(aapl_client: TestClient) -> None:
    before = get_capital(aapl_client)

    created = aapl_client.post(f"{COMPANY}/adjustments", json=CAPEX_FY2024)
    assert created.status_code == 201, created.text

    assert get_capital(aapl_client) == before
