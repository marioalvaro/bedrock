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
        "freq",
        "history_years",
        "forecast_years",
        "history_periods",
        "forecast_periods",
        "rows",
        "warnings",
    }
    assert grid["freq"] == "annual"
    # the periods mirror the years
    assert [p["fiscal_year"] for p in grid["history_periods"]] == grid["history_years"]
    assert [p["fiscal_year"] for p in grid["forecast_periods"]] == grid["forecast_years"]
    assert {p["fiscal_period"] for p in grid["forecast_periods"]} == {"FY"}
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


# --- quarterly drivers (docs/erd/forecasting.md "Quarterly drivers" -> API) ---------------------


def _qgrid(client: TestClient, scenario_id: int, case: str = "base") -> dict[str, Any]:
    response = client.get(
        f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers", params={"freq": "quarterly"}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _quarter(grid: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return grid["forecast_periods"][index]


def _qrow(code: str, kind: str, *values: tuple[int, str, str | None]) -> dict[str, Any]:
    return {
        "driver_code": code,
        "kind": kind,
        "freq": "quarterly",
        "values": [{"fiscal_year": y, "fiscal_period": q, "value": v} for y, q, v in values],
    }


def test_the_quarterly_grid_has_the_history_quarters_and_the_span(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]

    annual = _grid(aapl_client, main["id"], "bull")
    grid = _qgrid(aapl_client, main["id"], "bull")

    assert grid["freq"] == "quarterly"
    assert (grid["scenario_id"], grid["case"]) == (main["id"], "bull")
    assert len(grid["history_periods"]) == 8
    assert all(p["label"].endswith("A") for p in grid["history_periods"])
    assert 8 <= len(grid["forecast_periods"]) <= 11  # the fixed 8 quarters to the fiscal year end
    assert grid["forecast_periods"][-1]["fiscal_period"] == "Q4"
    assert all(p["label"].endswith("E") for p in grid["forecast_periods"])
    assert set(grid["forecast_periods"][0]) == {"fiscal_year", "fiscal_period", "label"}
    assert grid["history_years"] == annual["history_years"]  # the annual years stay
    n_forecast = len(grid["forecast_periods"])
    for row in grid["rows"]:
        assert len(row["history"]) == 8
        assert len(row["values"]) == len(row["sources"]) == len(row["own"]) == n_forecast
    assert [r["code"] for r in grid["rows"]] == [r["code"] for r in annual["rows"]]
    # Bull's annual offsets give every quarter Base's quarter plus the offset
    growth = _row(grid, "revenue_growth")
    assert set(growth["sources"]) == {"offset"}
    assert growth["own"] == [None] * n_forecast  # no quarter row of its own
    assert _row(grid, "tax_rate")["sources"] == ["year"] * n_forecast
    assert _row(annual, "tax_rate")["sources"] != ["year"] * 5  # the annual payload is as before


def test_the_annual_grid_is_unchanged_by_quarter_rows(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    before = _grid(aapl_client, main["id"], "bull")
    first = _quarter(_qgrid(aapl_client, main["id"], "bull"))

    put = _put(
        aapl_client,
        main["id"],
        "bull",
        _qrow("gross_margin", "offset", (first["fiscal_year"], first["fiscal_period"], "0.02")),
    )
    assert put.status_code == 200, put.text

    after = _grid(aapl_client, main["id"], "bull")
    assert after["rows"] == before["rows"]


def test_a_quarter_put_sets_that_quarter_only_and_replies_with_the_quarterly_grid(
    aapl_client: TestClient,
) -> None:
    main = _scenarios(aapl_client)["Main"]
    first = _quarter(_qgrid(aapl_client, main["id"], "bull"))
    year, quarter = first["fiscal_year"], first["fiscal_period"]

    put = _put(aapl_client, main["id"], "bull", _qrow("tax_rate", "value", (year, quarter, "0.30")))

    assert put.status_code == 200, put.text
    reply = put.json()
    assert reply["freq"] == "quarterly"
    tax = _row(reply, "tax_rate")
    assert tax["own"][0] == "0.3" and tax["values"][0] == "0.3" and tax["sources"][0] == "own"
    assert tax["sources"][1:] == ["year"] * (len(tax["sources"]) - 1)
    assert tax["kind"] == "value"
    assert reply == _qgrid(aapl_client, main["id"], "bull")
    forecast = aapl_client.get(
        f"{SCENARIOS}/{main['id']}/cases/bull/forecast", params={"type": "IS", "freq": "quarterly"}
    ).json()
    assert all(c["ok"] for c in forecast["integrity"])


def test_a_quarter_put_replaces_only_the_quarterly_rows_of_that_driver(
    aapl_client: TestClient,
) -> None:
    main = _scenarios(aapl_client)["Main"]
    grid = _qgrid(aapl_client, main["id"], "bull")
    (y1, q1), (y2, q2) = (
        (p["fiscal_year"], p["fiscal_period"]) for p in grid["forecast_periods"][:2]
    )
    first = _put(aapl_client, main["id"], "bull", _qrow("tax_rate", "value", (y1, q1, "0.30")))
    assert first.status_code == 200
    annual = _put(
        aapl_client,
        main["id"],
        "bull",
        {
            "driver_code": "tax_rate",
            "kind": "value",
            "values": [{"fiscal_year": y1, "value": "0.25"}],
        },
    )
    assert annual.status_code == 200
    assert _row(annual.json(), "tax_rate")["own"][0] == "0.25"  # the annual row
    assert _row(_qgrid(aapl_client, main["id"], "bull"), "tax_rate")["own"][0] == "0.3"  # kept

    second = _put(aapl_client, main["id"], "bull", _qrow("tax_rate", "value", (y2, q2, "0.31")))
    own = _row(second.json(), "tax_rate")["own"]
    assert own[0] is None and own[1] == "0.31"  # the earlier quarter row was replaced
    assert _row(_grid(aapl_client, main["id"], "bull"), "tax_rate")["own"][0] == "0.25"  # kept


def test_a_kind_change_drops_the_other_frequency_s_rows(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    first = _quarter(_qgrid(aapl_client, main["id"], "bull"))
    assert _row(_grid(aapl_client, main["id"], "bull"), "gross_margin")["kind"] == "offset"

    put = _put(
        aapl_client,
        main["id"],
        "bull",
        _qrow("gross_margin", "value", (first["fiscal_year"], first["fiscal_period"], "0.5")),
    )

    assert put.status_code == 200, put.text
    annual = _row(_grid(aapl_client, main["id"], "bull"), "gross_margin")
    assert annual["kind"] == "value" and annual["own"] == [None] * 5  # the annual offsets went


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (_qrow("tax_rate", "value", (1999, "Q1", "0.2")), "Q1 FY1999 is not a forecast quarter"),
        (_qrow("tax_rate", "value", (2030, "FY", "0.2")), "FY"),
        (_qrow("nope", "value", (2027, "Q1", "0.2")), "nope"),
        (_qrow("tax_rate", "value", (2027, "Q1", "1.5")), "tax_rate must be in [0, 1]"),
    ],
)
def test_an_invalid_quarterly_put_is_422_and_stores_nothing(
    aapl_client: TestClient, row: dict[str, Any], message: str
) -> None:
    main = _scenarios(aapl_client)["Main"]
    before = _qgrid(aapl_client, main["id"], "bull")
    if row["values"][0]["fiscal_year"] == 2027:  # a real span year: use the first quarter
        first = _quarter(before)
        row["values"][0].update(
            fiscal_year=first["fiscal_year"], fiscal_period=first["fiscal_period"]
        )

    response = _put(aapl_client, main["id"], "bull", row)

    assert response.status_code == 422, response.text
    assert message in str(response.json()["detail"])
    assert _qgrid(aapl_client, main["id"], "bull") == before


def test_year_and_quarter_values_cannot_be_mixed_in_a_row(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    first = _quarter(_qgrid(aapl_client, main["id"], "bull"))
    year_in_quarterly = {
        "driver_code": "tax_rate",
        "kind": "value",
        "freq": "quarterly",
        "values": [{"fiscal_year": first["fiscal_year"], "value": "0.2"}],
    }
    quarter_in_annual = {
        "driver_code": "tax_rate",
        "kind": "value",
        "values": [{"fiscal_year": first["fiscal_year"], "fiscal_period": "Q1", "value": "0.2"}],
    }

    a = _put(aapl_client, main["id"], "bull", year_in_quarterly)
    b = _put(aapl_client, main["id"], "bull", quarter_in_annual)

    assert (a.status_code, b.status_code) == (422, 422)
    assert "quarterly row" in a.json()["detail"] and "annual row" in b.json()["detail"]


def test_a_quarter_offset_on_base_is_422_and_an_unknown_freq_too(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    first = _quarter(_qgrid(aapl_client, main["id"], "base"))
    row = _qrow("tax_rate", "offset", (first["fiscal_year"], first["fiscal_period"], "0.01"))

    base = _put(aapl_client, main["id"], "base", row)
    freq = aapl_client.get(
        f"{SCENARIOS}/{main['id']}/cases/base/drivers", params={"freq": "monthly"}
    )

    assert base.status_code == 422 and "Base cannot hold offsets" in base.json()["detail"]
    assert freq.status_code == 422


def test_a_quarter_row_of_base_reaches_bull_as_base_s_quarter(aapl_client: TestClient) -> None:
    main = _scenarios(aapl_client)["Main"]
    first = _quarter(_qgrid(aapl_client, main["id"], "base"))
    year, quarter = first["fiscal_year"], first["fiscal_period"]
    put = _put(aapl_client, main["id"], "base", _qrow("tax_rate", "value", (year, quarter, "0.4")))
    assert put.status_code == 200

    bull = _row(_qgrid(aapl_client, main["id"], "bull"), "tax_rate")

    assert (bull["values"][0], bull["sources"][0], bull["own"][0]) == ("0.4", "base", None)
