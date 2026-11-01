"""Scenario CRUD, cases and the driver grid through the API (docs/erd/forecasting.md "Scenarios and
cases"), on the recorded AAPL fixtures."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

COMPANY = "/api/v1/companies/AAPL"
SCENARIOS = f"{COMPANY}/scenarios"
D = Decimal


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def _scenarios(client: TestClient) -> dict[str, dict[str, Any]]:
    response = client.get(SCENARIOS)
    assert response.status_code == 200, response.text
    return {s["name"]: s for s in response.json()}


def _grid(client: TestClient, scenario_id: int, case: str = "base") -> dict[str, Any]:
    response = client.get(f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _row(grid: dict[str, Any], code: str) -> dict[str, Any]:
    return next(r for r in grid["rows"] if r["code"] == code)


def _put(client: TestClient, scenario_id: int, case: str, *rows: dict[str, Any]) -> Any:
    return client.put(f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers", json={"rows": list(rows)})


def test_every_scenario_route_requires_a_session(client: TestClient) -> None:
    assert client.get(SCENARIOS).status_code == 401
    assert client.post(SCENARIOS, json={"name": "X"}).status_code == 401
    assert client.put(f"{SCENARIOS}/1", json={}).status_code == 401
    assert client.delete(f"{SCENARIOS}/1").status_code == 401
    case = f"{SCENARIOS}/1/cases/bull"
    assert client.get(f"{case}/drivers").status_code == 401
    assert client.put(f"{case}/drivers", json={"rows": []}).status_code == 401
    assert client.post(f"{case}/reset").status_code == 401


def test_an_unfollowed_ticker_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get("/api/v1/companies/ZZZZ/scenarios").status_code == 404
    assert (
        authed_client.get("/api/v1/companies/ZZZZ/scenarios/1/cases/base/drivers").status_code
        == 404
    )


def test_the_first_list_gives_the_default_scenario_main(aapl_client: TestClient) -> None:
    response = aapl_client.get(SCENARIOS)

    assert response.status_code == 200
    body = response.json()
    assert [s["name"] for s in body] == ["Main"]
    assert set(body[0]) == {
        "id",
        "name",
        "is_default",
        "revenue_method",
        "segment_dimension",
        "volume_kpi",
        "price_kpi",
        "created_at",
        "updated_at",
    }
    assert body[0]["is_default"] is True
    assert [s["id"] for s in aapl_client.get(SCENARIOS).json()] == [s["id"] for s in body]


def test_create_update_and_delete_a_scenario(aapl_client: TestClient) -> None:
    _scenarios(aapl_client)

    created = aapl_client.post(SCENARIOS, json={"name": "Mine"})
    assert created.status_code == 201, created.text
    mine = created.json()
    assert mine["name"] == "Mine"

    updated = aapl_client.put(f"{SCENARIOS}/{mine['id']}", json={"name": "Ours"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ours"

    assert aapl_client.delete(f"{SCENARIOS}/{mine['id']}").status_code == 204
    assert list(_scenarios(aapl_client)) == ["Main"]
    assert aapl_client.delete(f"{SCENARIOS}/{mine['id']}").status_code == 404


def test_conflicts_are_409(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    other = aapl_client.post(SCENARIOS, json={"name": "Other"}).json()

    duplicate = aapl_client.post(SCENARIOS, json={"name": "Other"})
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "The company already has a scenario named 'Other'"}
    assert aapl_client.put(f"{SCENARIOS}/{main['id']}", json={"name": "Other"}).status_code == 409
    assert aapl_client.put(f"{SCENARIOS}/{other['id']}", json={"name": "Main"}).status_code == 409
    default = aapl_client.delete(f"{SCENARIOS}/{main['id']}")
    assert (default.status_code, default.json()) == (
        409,
        {"detail": "The default scenario cannot be deleted"},
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        # the horizon is fixed (5 years, 8 quarters): a body that sets one is refused
        {"name": "A", "horizon_years": 5},
        {"name": "A", "horizon_quarters": 8},
        {"name": "A", "revenue_method": "segments"},
        {"name": "A", "revenue_method": "magic"},
        {"name": "A", "revenue_method": "volume_price", "volume_kpi": "u", "price_kpi": "p"},
    ],
)
def test_invalid_settings_are_422_and_store_nothing(
    aapl_client: TestClient, body: dict[str, Any]
) -> None:
    _scenarios(aapl_client)

    response = aapl_client.post(SCENARIOS, json=body)

    assert response.status_code == 422, response.text
    assert "detail" in response.json()
    assert len(_scenarios(aapl_client)) == 1


def test_another_company_s_scenario_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    other = aapl_client.post("/api/v1/companies/MSFT/scenarios", json={"name": "Theirs"}).json()[
        "id"
    ]
    _scenarios(aapl_client)

    assert aapl_client.put(f"{SCENARIOS}/{other}", json={"name": "X"}).status_code == 404
    assert aapl_client.delete(f"{SCENARIOS}/{other}").status_code == 404
    for case in ("base", "bull"):
        assert aapl_client.get(f"{SCENARIOS}/{other}/cases/{case}/drivers").status_code == 404
        assert _put(aapl_client, other, case).status_code == 404
        assert aapl_client.post(f"{SCENARIOS}/{other}/cases/{case}/reset").status_code == 404
    assert aapl_client.get(f"{SCENARIOS}/{other}/compare?freq=annual").status_code == 404


@pytest.mark.parametrize("case", ["base", "bull", "bear"])
def test_every_case_route_works_for_each_case(aapl_client: TestClient, case: str) -> None:
    main = _scenarios(aapl_client)["Main"]
    path = f"{SCENARIOS}/{main['id']}/cases/{case}"
    kind = "value" if case == "base" else "offset"
    year = _grid(aapl_client, main["id"], case)["forecast_years"][0]

    saved = _put(
        aapl_client,
        main["id"],
        case,
        {
            "driver_code": "tax_rate",
            "kind": kind,
            "values": [{"fiscal_year": year, "value": "0.02"}],
        },
    )
    reset = aapl_client.post(f"{path}/reset")

    assert saved.status_code == 200, saved.text
    assert (saved.json()["scenario_id"], saved.json()["case"]) == (main["id"], case)
    assert _row(saved.json(), "tax_rate")["own"][0] == "0.02"
    assert reset.status_code == 200, reset.text
    assert (reset.json()["scenario_id"], reset.json()["case"]) == (main["id"], case)
    assert _row(reset.json(), "tax_rate")["own"] == [None] * 5  # back to the defaults
    assert aapl_client.get(f"{path}/drivers").json() == reset.json()


def test_an_unknown_case_is_422_on_every_case_route(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    path = f"{SCENARIOS}/{main['id']}/cases/worst"

    assert aapl_client.get(f"{path}/drivers").status_code == 422
    assert aapl_client.put(f"{path}/drivers", json={"rows": []}).status_code == 422
    assert aapl_client.post(f"{path}/reset").status_code == 422
    assert aapl_client.get(f"{path}/drivers/export").status_code == 422
    assert aapl_client.get(f"{path}/forecast?type=IS&freq=annual").status_code == 422


def test_reset_restores_bull_s_default_offsets(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    year = _grid(aapl_client, main["id"], "bull")["forecast_years"][0]
    _put(
        aapl_client,
        main["id"],
        "bull",
        {
            "driver_code": "revenue_growth",
            "kind": "value",
            "values": [{"fiscal_year": year, "value": "0.2"}],
        },
    )

    response = aapl_client.post(f"{SCENARIOS}/{main['id']}/cases/bull/reset")

    growth = _row(response.json(), "revenue_growth")
    assert (growth["kind"], growth["own"]) == ("offset", ["0.03"] * 5)


def test_a_new_scenario_s_cases_start_from_the_defaults(aapl_client: TestClient) -> None:
    _scenarios(aapl_client)
    mine = aapl_client.post(SCENARIOS, json={"name": "Mine"}).json()

    bear = _grid(aapl_client, mine["id"], "bear")
    base = _grid(aapl_client, mine["id"], "base")

    assert _row(bear, "gross_margin")["own"] == ["-0.01"] * 5
    assert all(r["kind"] is None for r in base["rows"])


def test_the_grid_has_the_documented_shape(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]

    grid = _grid(aapl_client, main["id"], "bull")

    assert set(grid) == {
        "scenario_id",
        "case",
        "history_years",
        "forecast_years",
        "rows",
        "warnings",
    }
    assert (grid["scenario_id"], grid["case"]) == (main["id"], "bull")
    assert len(grid["history_years"]) == 5
    assert len(grid["forecast_years"]) == 5
    growth = _row(grid, "revenue_growth")
    assert set(growth) == {
        "code",
        "label",
        "group",
        "unit",
        "history",
        "values",
        "sources",
        "own",
        "kind",
    }
    assert (growth["unit"], growth["kind"]) == ("pct", "offset")
    assert len(growth["history"]) == 5 and all(isinstance(v, str) for v in growth["history"])
    assert growth["sources"] == ["offset"] * 5
    assert growth["own"] == ["0.03"] * 5  # plain decimals (G15)
    assert _row(grid, "tax_rate")["kind"] is None


def test_a_bull_edit_leaves_base_and_bear_alone(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    before = {c: _grid(aapl_client, main["id"], c) for c in ("base", "bear")}
    year = before["base"]["forecast_years"][0]

    response = _put(
        aapl_client,
        main["id"],
        "bull",
        {
            "driver_code": "revenue_growth",
            "kind": "value",
            "values": [{"fiscal_year": year, "value": "0.2"}],
        },
    )

    assert response.status_code == 200, response.text
    assert _row(response.json(), "revenue_growth")["values"][0] == "0.2"
    assert _row(response.json(), "revenue_growth")["sources"][0] == "own"
    assert {c: _grid(aapl_client, main["id"], c) for c in ("base", "bear")} == before


def test_a_base_edit_moves_bull_s_inherited_and_offset_values(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    year = _grid(aapl_client, main["id"])["forecast_years"][0]

    response = _put(
        aapl_client,
        main["id"],
        "base",
        {
            "driver_code": "gross_margin",
            "kind": "value",
            "values": [{"fiscal_year": year, "value": "0.4"}],
        },
        {
            "driver_code": "tax_rate",
            "kind": "value",
            "values": [{"fiscal_year": year, "value": "0.2"}],
        },
    )
    assert response.status_code == 200, response.text

    bull = _grid(aapl_client, main["id"], "bull")
    assert (_row(bull, "gross_margin")["values"][0], _row(bull, "gross_margin")["sources"][0]) == (
        "0.41",
        "offset",
    )
    assert (_row(bull, "tax_rate")["values"][0], _row(bull, "tax_rate")["sources"][0]) == (
        "0.2",
        "base",
    )


@pytest.mark.parametrize(
    ("row", "detail"),
    [
        ({"driver_code": "magic", "kind": "value", "values": []}, "Unknown driver 'magic'"),
        (
            {
                "driver_code": "tax_rate",
                "kind": "offset",
                "values": [{"fiscal_year": 0, "value": "0.1"}],
            },
            "Base cannot hold offsets",
        ),
        (
            {
                "driver_code": "tax_rate",
                "kind": "value",
                "values": [{"fiscal_year": 1999, "value": "0.1"}],
            },
            "FY1999 is not a forecast year",
        ),
        (
            {
                "driver_code": "tax_rate",
                "kind": "value",
                "values": [{"fiscal_year": 0, "value": "2"}],
            },
            "tax_rate must be in [0, 1]",
        ),
        (
            {
                "driver_code": "buybacks",
                "kind": "value",
                "values": [{"fiscal_year": 0, "value": "1e400"}],
            },
            "buybacks must be in [0, 10^15)",
        ),
        ({"driver_code": "tax_rate", "kind": "both", "values": []}, None),
        (
            {
                "driver_code": "tax_rate",
                "kind": "value",
                "values": [{"fiscal_year": 0, "value": "abc"}],
            },
            None,
        ),
    ],
)
def test_an_invalid_driver_put_is_422_and_stores_nothing(
    aapl_client: TestClient, row: dict[str, Any], detail: str | None
) -> None:
    base = _scenarios(aapl_client)["Main"]
    before = _grid(aapl_client, base["id"])
    first = before["forecast_years"][0]
    for value in row["values"]:
        value["fiscal_year"] = value["fiscal_year"] or first

    response = _put(aapl_client, base["id"], "base", row)

    assert response.status_code == 422, response.text
    if detail is not None:
        assert detail in response.json()["detail"]
    assert _grid(aapl_client, base["id"]) == before


def test_a_json_number_too_large_for_a_double_is_422(aapl_client: TestClient) -> None:
    base = _scenarios(aapl_client)["Main"]
    first = _grid(aapl_client, base["id"])["forecast_years"][0]
    raw = (
        '{"rows": [{"driver_code": "buybacks", "kind": "value", '
        f'"values": [{{"fiscal_year": {first}, "value": 1e400}}]}}]}}'
    )

    response = aapl_client.put(
        f"{SCENARIOS}/{base['id']}/cases/base/drivers",
        content=raw,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422, response.text
    assert _row(_grid(aapl_client, base["id"]), "buybacks")["own"] == [None] * 5
