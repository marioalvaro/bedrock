"""Engine choices, the driver grid's engine fields and the cross-check through the API (FR-FCST-07,
-11; docs/erd/forecasting.md "Statistical engines (M6)" → API), on the recorded fixtures."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

D = Decimal


def _base(ticker: str) -> str:
    return f"/api/v1/companies/{ticker}/scenarios"


def _main(client: TestClient, ticker: str = "AAPL") -> int:
    response = client.get(_base(ticker))
    assert response.status_code == 200, response.text
    return int(next(s["id"] for s in response.json() if s["name"] == "Main"))


def _engines(client: TestClient, scenario_id: int, ticker: str = "AAPL") -> str:
    return f"{_base(ticker)}/{scenario_id}/engines"


def _grid(client: TestClient, scenario_id: int, case: str = "base", ticker: str = "AAPL") -> Any:
    response = client.get(f"{_base(ticker)}/{scenario_id}/cases/{case}/drivers")
    assert response.status_code == 200, response.text
    return response.json()


def _row(body: dict[str, Any], code: str) -> dict[str, Any]:
    return next(r for r in body["rows"] if r["code"] == code)


@pytest.fixture
def aapl(seed_db: Callable[..., None], authed_client: TestClient) -> TestClient:
    seed_db("AAPL")
    return authed_client


def test_the_engine_routes_require_a_session(client: TestClient) -> None:
    url = f"{_base('AAPL')}/1/engines"
    assert client.get(url).status_code == 401
    assert client.put(url, json={"rows": []}).status_code == 401
    assert client.get(f"{_base('AAPL')}/1/cases/base/driver-engines?code=x").status_code == 401


def test_get_lists_the_drivers_of_the_method_with_auto(aapl: TestClient) -> None:
    scenario_id = _main(aapl)

    response = aapl.get(_engines(aapl, scenario_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scenario_id"] == scenario_id
    first = body["rows"][0]
    assert set(first) == {
        "driver_code", "label", "group", "unit", "engine", "used", "note", "seasonal",
    }  # fmt: skip
    assert first["driver_code"] == "revenue_growth"
    assert {r["engine"] for r in body["rows"]} == {"auto"}
    seasonal = {r["driver_code"]: r["seasonal"] for r in body["rows"]}
    assert seasonal["gross_margin"] is True
    assert seasonal["revenue_growth"] is False


def test_put_sets_the_engine_and_returns_the_rows(aapl: TestClient) -> None:
    scenario_id = _main(aapl)

    response = aapl.put(
        _engines(aapl, scenario_id), json={"rows": [{"driver_code": "tax_rate", "engine": "ets"}]}
    )

    assert response.status_code == 200, response.text
    rows = {r["driver_code"]: r for r in response.json()["rows"]}
    assert rows["tax_rate"]["engine"] == "ets"
    assert rows["tax_rate"]["used"] == "ets"
    assert rows["gross_margin"]["engine"] == "auto"
    assert aapl.get(_engines(aapl, scenario_id)).json() == response.json()


def test_another_company_s_scenario_is_a_404(aapl: TestClient) -> None:
    scenario_id = _main(aapl)

    assert aapl.get(_engines(aapl, scenario_id, "MSFT")).status_code == 404
    assert aapl.get(_engines(aapl, 999_999)).status_code == 404
    assert aapl.put(_engines(aapl, 999_999), json={"rows": []}).status_code == 404


@pytest.mark.parametrize(
    ("rows", "detail"),
    [
        ([{"driver_code": "nope", "engine": "ets"}], "nope is not a driver of the growth method"),
        (
            [{"driver_code": "revenue_growth", "engine": "stl"}],
            "STL applies to ratio and days drivers only: revenue_growth",
        ),
        (
            [
                {"driver_code": "tax_rate", "engine": "ets"},
                {"driver_code": "tax_rate", "engine": "mean"},
            ],
            "tax_rate is given twice",
        ),
    ],
)
def test_put_refuses_a_rule_break_with_a_422(
    aapl: TestClient, rows: list[dict[str, str]], detail: str
) -> None:
    scenario_id = _main(aapl)

    response = aapl.put(_engines(aapl, scenario_id), json={"rows": rows})

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert {r["engine"] for r in aapl.get(_engines(aapl, scenario_id)).json()["rows"]} == {"auto"}


@pytest.mark.parametrize(
    "body",
    [
        {"rows": [{"driver_code": "tax_rate", "engine": "prophet"}]},  # not an engine
        {"rows": [{"driver_code": "tax_rate", "engine": "ets", "extra": 1}]},
        {"rows": [], "extra": 1},
    ],
)
def test_put_refuses_an_unknown_engine_or_field_with_a_422(aapl: TestClient, body: Any) -> None:
    scenario_id = _main(aapl)

    assert aapl.put(_engines(aapl, scenario_id), json=body).status_code == 422


def test_the_grid_carries_the_engine_fields(aapl: TestClient) -> None:
    scenario_id = _main(aapl)
    aapl.put(
        _engines(aapl, scenario_id),
        json={"rows": [{"driver_code": "gross_margin", "engine": "stl"}]},
    )

    row = _row(_grid(aapl, scenario_id), "gross_margin")

    assert row["engine"] == "stl"
    assert row["engine_used"] in ("arima", "ets", "blend", "mean")
    assert row["seasonal"] is True
    assert row["check"] == [None] * len(row["values"])  # every year is an engine value
    growth = _row(_grid(aapl, scenario_id), "revenue_growth")
    assert growth["seasonal"] is False
    assert growth["engine"] == "auto"
    assert growth["engine_used"] in ("arima", "ets", "blend", "mean")
    assert set(_row(_grid(aapl, scenario_id), "tax_rate")["sources"]) == {"engine"}


def test_the_quarterly_grid_has_no_cross_check(aapl: TestClient) -> None:
    scenario_id = _main(aapl)

    response = aapl.get(
        f"{_base('AAPL')}/{scenario_id}/cases/base/drivers", params={"freq": "quarterly"}
    )

    row = _row(response.json(), "gross_margin")
    assert row["engine"] == "auto"
    assert row["check"] == [None] * len(row["values"])


def _set_margin(client: TestClient, scenario_id: int, year: int, value: str) -> dict[str, Any]:
    response = client.put(
        f"{_base('AAPL')}/{scenario_id}/cases/base/drivers",
        json={
            "rows": [
                {
                    "driver_code": "gross_margin",
                    "kind": "value",
                    "values": [{"fiscal_year": year, "value": value}],
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_manual_value_outside_the_90_percent_band_is_flagged(aapl: TestClient) -> None:
    scenario_id = _main(aapl)
    year = _grid(aapl, scenario_id)["forecast_years"][0]
    index = 0

    row = _row(_set_margin(aapl, scenario_id, year, "0.90"), "gross_margin")
    check = row["check"][index]

    assert check is not None
    assert check["engine"] in ("arima", "ets", "blend")
    assert D(check["p05"]) < D(check["p95"])
    assert check["outside"] is True
    assert row["check"][1] is None  # the other years are engine values

    center = (D(check["p05"]) + D(check["p95"])) / 2
    row = _row(
        _set_margin(aapl, scenario_id, year, str(center.quantize(D("0.0001")))), "gross_margin"
    )
    assert row["check"][index]["outside"] is False


def test_de_without_gross_margin_still_asks_for_it(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("DE")
    scenario_id = _main(authed_client, "DE")

    response = authed_client.get(
        f"{_base('DE')}/{scenario_id}/cases/base/forecast", params={"type": "IS", "freq": "annual"}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Set these drivers: gross_margin"}


@pytest.mark.parametrize(
    "route", ["forecast?type=IS&freq=annual", "compare?freq=annual", "valuation"]
)
def test_the_forecast_routes_answer_with_the_auto_defaults(aapl: TestClient, route: str) -> None:
    scenario_id = _main(aapl)
    prefix = f"{_base('AAPL')}/{scenario_id}"
    url = f"{prefix}/{route}" if route.startswith("compare") else f"{prefix}/cases/base/{route}"

    response = aapl.get(url)

    assert response.status_code == 200, response.text
