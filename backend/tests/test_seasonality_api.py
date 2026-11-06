"""The STL decomposition of a quarterly IS/CF line through the API (FR-FCST-08; docs/erd/
forecasting.md "Statistical engines (M6)" → API), on the recorded fixtures."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.services.errors import InvalidSeasonality
from bedrock.services.seasonality import decomposition

from .seed import fake_sources, follow


def _get(client: TestClient, ticker: str, **params: str) -> Any:
    return client.get(f"/api/v1/companies/{ticker}/seasonality", params=params)


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_route_requires_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/companies/COST/seasonality").status_code == 401


def test_cost_revenue_has_a_strong_q4_pattern(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("COST")

    body = _ok(_get(authed_client, "COST", code="revenue"))

    assert body["code"] == "revenue"
    assert body["label"] == "Revenue"
    assert len(body["periods"]) == 72
    assert body["periods"][0] == {"fiscal_year": 2009, "fiscal_period": "Q1", "label": "Q1 FY09"}
    for key in ("observed", "trend", "seasonal", "residual"):
        assert len(body[key]) == 72, key
    factors = {f["fiscal_period"]: f for f in body["factors"]}
    assert max(factors, key=lambda q: factors[q]["value"]) == "Q4"
    assert factors["Q4"]["value"] > 0
    assert factors["Q4"]["pct"] > 0.15
    assert abs(sum(f["value"] for f in body["factors"])) < 1e-6 * abs(body["observed"][-1])
    assert body["strength"] > 0.9
    codes = [line["code"] for line in body["lines"]]
    assert "revenue" in codes
    assert codes.index("revenue") < codes.index("net_income")  # canonical order


def test_the_default_line_is_revenue_and_aapl_peaks_in_q1(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL")

    body = _ok(_get(authed_client, "AAPL"))

    assert body["code"] == "revenue"
    factors = {f["fiscal_period"]: f["value"] for f in body["factors"]}
    assert max(factors, key=lambda q: factors[q]) == "Q1"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"code": "nope"}, "Unknown line nope"),
        ({"code": "total_assets"}, "Unknown line total_assets"),  # a balance sheet line
    ],
)
def test_an_unknown_line_is_a_422(
    seed_db: Callable[..., None], authed_client: TestClient, params: dict[str, str], message: str
) -> None:
    seed_db("COST")

    response = _get(authed_client, "COST", **params)

    assert response.status_code == 422
    assert response.json() == {"detail": message}


def test_a_line_with_too_few_consecutive_quarters_is_a_422(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("COST")

    response = _get(authed_client, "COST", code="net_income_nci")

    assert response.status_code == 422
    assert response.json()["detail"].endswith(" has fewer than 12 consecutive quarters")


def test_lines_hold_only_the_decomposable_ones(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("COST")

    codes = [line["code"] for line in _ok(_get(authed_client, "COST"))["lines"]]

    assert "net_income_nci" not in codes
    assert "goodwill_impairment" not in codes
    assert codes[0] == "revenue"


def test_a_company_with_no_quarterly_history_is_a_422(db_session: Session) -> None:
    empty = follow(db_session, fake_sources().edgar, "MSFT")  # followed, no statements

    with pytest.raises(InvalidSeasonality, match="No quarterly history"):
        decomposition(db_session, empty, "revenue")
