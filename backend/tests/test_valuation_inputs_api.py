"""A case's valuation inputs through the API (FR-VAL-01, docs/erd/valuation.md "API"), on the
recorded AAPL, MSFT and DE fixtures."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bedrock.valuation.inputs import INPUTS

from .valuation_api import case_url, main_id, ok, put_inputs, set_gross_margin


@pytest.fixture
def client(seed_db: Callable[..., None], authed_client: TestClient) -> TestClient:
    seed_db("AAPL", "MSFT", "DE")
    return authed_client


def url(scenario_id: int, case: str = "base", tail: str = "valuation-inputs") -> str:
    return case_url("AAPL", scenario_id, case, tail)


def row(body: dict[str, Any], code: str) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in body["rows"] if r["code"] == code)
    return found


def test_the_routes_require_a_session(client: TestClient) -> None:
    main = main_id(client)
    client.cookies.clear()

    assert client.get(url(main)).status_code == 401
    assert client.put(url(main), json={"rows": []}).status_code == 401
    assert client.post(url(main, tail="valuation-inputs/reset")).status_code == 401


def test_get_lists_the_catalog_with_sources_and_the_forecast_years(client: TestClient) -> None:
    main = main_id(client)

    body = ok(client.get(url(main)))

    assert (body["scenario_id"], body["case"]) == (main, "base")
    assert [r["code"] for r in body["rows"]] == [d.code for d in INPUTS]
    assert [y["index"] for y in body["forecast_years"]] == [1, 2, 3, 4, 5]
    assert body["warnings"] == []
    beta = row(body, "beta")
    assert beta == {
        "code": "beta",
        "label": "Beta",
        "group": "Discount rate",
        "unit": "x",
        "kind": "number",
        "choices": None,
        "value": "1",
        "source": "default",
        "own": None,
        "note": None,
    }
    assert row(body, "discount_method")["choices"] == ["wacc", "direct"]
    assert row(body, "tax_rate")["source"] == "derived"
    assert row(body, "comps_set_id")["value"] is None


def test_put_sets_and_null_clears_and_bull_inherits(client: TestClient) -> None:
    main = main_id(client)

    stored = ok(put_inputs(client, main, "base", beta="1.2"))
    assert (row(stored, "beta")["value"], row(stored, "beta")["source"]) == ("1.2", "own")
    bull = ok(client.get(url(main, "bull")))
    assert (row(bull, "beta")["value"], row(bull, "beta")["source"]) == ("1.2", "base")
    assert row(bull, "beta")["own"] is None

    cleared = ok(put_inputs(client, main, "base", beta=None))
    assert row(cleared, "beta")["source"] == "default"


def test_reset_clears_the_case_and_the_driver_reset_leaves_inputs_alone(
    client: TestClient,
) -> None:
    main = main_id(client)
    put_inputs(client, main, "bull", beta="1.5")

    drivers_reset = client.post(url(main, "bull", "reset"))
    assert drivers_reset.status_code == 200
    assert row(ok(client.get(url(main, "bull"))), "beta")["own"] == "1.5"

    reset = ok(client.post(url(main, "bull", "valuation-inputs/reset")))
    assert row(reset, "beta")["own"] is None


def test_another_company_s_scenario_is_a_404(client: TestClient) -> None:
    msft = main_id(client, "MSFT")

    assert client.get(url(msft)).status_code == 404
    assert client.put(url(msft), json={"rows": []}).status_code == 404
    assert client.post(url(msft, tail="valuation-inputs/reset")).status_code == 404


def test_an_unknown_case_is_a_422(client: TestClient) -> None:
    assert client.get(url(main_id(client), "worst")).status_code == 422


def _comps_set_of_msft(client: TestClient) -> int:
    created = client.post(
        "/api/v1/companies/MSFT/comps-sets", json={"name": "Peers", "members": []}
    )
    assert created.status_code == 201, created.text
    return int(created.json()["id"])


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([{"code": "nope", "value": "1"}], "Unknown valuation input 'nope'"),
        ([{"code": "beta", "value": "1"}, {"code": "beta", "value": "2"}], "beta given twice"),
        ([{"code": "beta", "value": "1e400"}], "beta must be a number"),
        ([{"code": "beta", "value": "6"}], "beta must be in [0, 5]"),
        ([{"code": "terminal_method", "value": "perpetual"}], "must be one of gordon"),
        ([{"code": "comps_set_id", "value": "424242"}], "No such comps set"),
    ],
)
def test_a_bad_put_is_a_422_with_its_detail_and_writes_nothing(
    client: TestClient, rows: list[dict[str, str]], message: str
) -> None:
    main = main_id(client)

    response = client.put(url(main), json={"rows": [{"code": "mid_year", "value": "false"}, *rows]})

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert row(ok(client.get(url(main))), "mid_year")["own"] is None


def test_a_comps_set_of_another_company_a_json_infinity_and_an_extra_field_are_422(
    client: TestClient,
) -> None:
    main = main_id(client)
    other = _comps_set_of_msft(client)

    assert put_inputs(client, main, "base", comps_set_id=str(other)).status_code == 422
    infinity = client.put(
        url(main),
        content=b'{"rows": [{"code": "beta", "value": 1e400}]}',
        headers={"content-type": "application/json"},
    )
    assert infinity.status_code == 422
    extra = client.put(url(main), json={"rows": [], "other": 1})
    assert extra.status_code == 422
    extra_row = client.put(url(main), json={"rows": [{"code": "beta", "value": "1", "x": 1}]})
    assert extra_row.status_code == 422


def test_a_forecast_that_cannot_run_still_lists_inputs_without_derived_values(
    client: TestClient,
) -> None:
    de = main_id(client, "DE")

    body = ok(client.get(case_url("DE", de, "base", "valuation-inputs")))

    assert body["warnings"] == ["Set these drivers: gross_margin"]
    assert row(body, "tax_rate")["value"] is None
    assert row(body, "debt_weight")["value"] is None
    assert row(body, "beta")["value"] == "1"

    set_gross_margin(client, de, "DE", "0.25")
    fixed = ok(client.get(case_url("DE", de, "base", "valuation-inputs")))
    assert fixed["warnings"] == [] and row(fixed, "tax_rate")["value"] is not None
