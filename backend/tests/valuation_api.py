"""Helpers shared by the valuation API tests (scenario ids, URLs, input and driver PUTs)."""

from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1/companies"


def scenarios_url(ticker: str) -> str:
    return f"{API}/{ticker}/scenarios"


def main_id(client: TestClient, ticker: str = "AAPL") -> int:
    response = client.get(scenarios_url(ticker))
    assert response.status_code == 200, response.text
    return int(next(s["id"] for s in response.json() if s["name"] == "Main"))


def case_url(ticker: str, scenario_id: int, case: str, tail: str) -> str:
    return f"{scenarios_url(ticker)}/{scenario_id}/cases/{case}/{tail}"


def put_inputs(
    client: TestClient, scenario_id: int, case: str, ticker: str = "AAPL", **values: str | None
) -> Any:
    rows = [{"code": c, "value": v} for c, v in values.items()]
    return client.put(case_url(ticker, scenario_id, case, "valuation-inputs"), json={"rows": rows})


def ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def set_gross_margin(client: TestClient, scenario_id: int, ticker: str, value: str) -> None:
    path = case_url(ticker, scenario_id, "base", "drivers")
    years = client.get(path).json()["forecast_years"]
    row = {
        "driver_code": "gross_margin",
        "kind": "value",
        "values": [{"fiscal_year": y, "value": value} for y in years],
    }
    assert client.put(path, json={"rows": [row]}).status_code == 200
