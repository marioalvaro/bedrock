"""Valuation ratios through the API over a followed AAPL (recorded fixtures). FR-ANL-07."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from bedrock.ingest.protocol import PriceRow
from bedrock.models.company import Company
from bedrock.models.price_daily import PriceDaily
from bedrock.repositories import prices as price_repo
from tests.test_ratios_api import RATIOS_PATH, value

FY2023_CLOSE = Decimal("170.00")
FY2024_CLOSE = Decimal("225.00")


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


@pytest.fixture
def priced_client(aapl_client: TestClient, db_session: Session) -> TestClient:
    """AAPL with closes on its FY2023 and FY2024 year ends (the recorded price fixture covers
    only the last year, which holds no fiscal year end)."""
    company = db_session.query(Company).filter_by(ticker="AAPL").one()
    rows = [
        PriceRow(date=date(2023, 9, 29), close=FY2023_CLOSE, adj_close=FY2023_CLOSE, volume=1),
        PriceRow(date=date(2024, 9, 27), close=FY2024_CLOSE, adj_close=FY2024_CLOSE, volume=1),
    ]
    price_repo.insert_new(db_session, company.id, rows)
    db_session.commit()
    return aapl_client


def ratios(client: TestClient, freq: str = "annual") -> dict[str, Any]:
    response = client.get(RATIOS_PATH, params={"freq": freq})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_valuation_rows_are_listed_in_the_valuation_category(priced_client: TestClient) -> None:
    body = ratios(priced_client)
    codes = [r["code"] for r in body["rows"] if r["category"] == "Valuation"]
    assert codes[:2] == ["pe", "earnings_yield"] and len(codes) == 14
    ev = next(r for r in body["rows"] if r["code"] == "enterprise_value_usd")
    assert (ev["label"], ev["unit"]) == ("Enterprise value", "USD")
    assert any(v is not None for v in ev["values"])


def test_annual_pb_equals_the_close_over_book_value_per_share(priced_client: TestClient) -> None:
    body = ratios(priced_client)
    pb, bvps = value(body, "pb", "FY2024"), value(body, "bvps", "FY2024")
    assert pb is not None and bvps is not None
    assert abs(pb - FY2024_CLOSE / bvps) < Decimal("0.01")


def test_each_year_uses_its_own_close(priced_client: TestClient) -> None:
    body = ratios(priced_client)
    pe23, ey23 = value(body, "pe", "FY2023"), value(body, "earnings_yield", "FY2023")
    pe24 = value(body, "pe", "FY2024")
    assert pe23 is not None and ey23 is not None and pe24 is not None
    assert abs(pe23 * ey23 - 1) < Decimal("0.001")
    assert value(body, "pe", "FY2022") is None  # no close on or before FY2022's end


def test_periods_before_the_first_stored_close_have_empty_valuation(
    aapl_client: TestClient,
) -> None:
    body = ratios(aapl_client)
    row = next(r for r in body["rows"] if r["code"] == "ev_ebitda")
    assert all(v is None for v in row["values"])


# --- /multiples ------------------------------------------------------------------------------

MULTIPLES = "/api/v1/companies/AAPL/multiples"


def multiples(client: TestClient, **params: str) -> dict[str, Any]:
    response = client.get(MULTIPLES, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_multiples_require_a_session(client: TestClient) -> None:
    assert client.get(MULTIPLES).status_code == 401


def test_multiples_of_an_unfollowed_company_are_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(MULTIPLES).status_code == 404


def test_a_bad_basis_is_a_422(aapl_client: TestClient) -> None:
    assert aapl_client.get(MULTIPLES, params={"basis": "adjusted"}).status_code == 422


def test_multiples_have_the_documented_shape(priced_client: TestClient) -> None:
    body = multiples(priced_client)
    assert body["ticker"] == "AAPL" and body["basis"] == "reported"
    assert [r["code"] for r in body["rows"]][:3] == ["pe", "earnings_yield", "peg"]
    assert set(body["rows"][0]) == {
        "code",
        "label",
        "unit",
        "caveat",
        "current",
        "min",
        "median",
        "max",
        "percentile",
        "n",
    }


def test_the_current_multiple_uses_the_latest_close(priced_client: TestClient) -> None:
    body = multiples(priced_client)
    # the recorded price fixture's last row, the latest close of the fake source
    assert (body["price"], body["price_date"]) == ("336.67", "2026-10-07")
    row = next(r for r in body["rows"] if r["code"] == "pe")
    assert row["current"] is not None and Decimal(row["current"]) > 0
    assert row["n"] >= 2  # at least the two annual P/Es of the closes `priced_client` inserts
    assert (row["min"] is None) == (row["n"] < 3)  # a range needs three annual values


def test_a_company_without_prices_has_empty_multiples(
    aapl_client: TestClient, db_session: Session
) -> None:
    company = db_session.query(Company).filter_by(ticker="AAPL").one()
    db_session.execute(delete(PriceDaily).where(PriceDaily.company_id == company.id))
    db_session.commit()
    body = multiples(aapl_client)
    assert body["price"] is None and body["price_date"] is None
    priced = [r for r in body["rows"] if r["code"] != "payout_ratio"]  # payout needs no price
    assert all(r["current"] is None for r in priced)


def test_the_current_pe_agrees_with_the_company_list_pe(aapl_client: TestClient) -> None:
    listed = next(c for c in aapl_client.get("/api/v1/companies").json() if c["ticker"] == "AAPL")
    current = next(r for r in multiples(aapl_client)["rows"] if r["code"] == "pe")["current"]
    assert listed["pe"] is not None and current is not None
    # the list divides by the cover-page share count, the ratio by the balance-sheet count
    assert abs(Decimal(current) / Decimal(listed["pe"]) - 1) < Decimal("0.01")
