"""The tornado and the 2-D grid of a case's DCF value per share through the API (FR-VAL-04,
docs/erd/valuation.md "Sensitivity", "API"), on the recorded AAPL and MSFT fixtures."""

import time
from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from .valuation_api import case_url, main_id, ok, put_inputs

D = Decimal


@pytest.fixture
def client(seed_db: Callable[..., None], authed_client: TestClient) -> TestClient:
    seed_db("AAPL", "MSFT")
    return authed_client


def tornado_url(main: int, case: str = "base") -> str:
    return case_url("AAPL", main, case, "sensitivity/tornado")


def grid_url(main: int, case: str = "base") -> str:
    return case_url("AAPL", main, case, "sensitivity/grid")


def base_value(client: TestClient, main: int, case: str = "base") -> Decimal:
    body = ok(client.get(case_url("AAPL", main, case, "valuation")))
    dcf = next(r for r in body["results"] if r["key"] == "dcf_fcff")
    return D(dcf["value_per_share"])


def test_the_routes_require_a_session(client: TestClient) -> None:
    main = main_id(client)
    client.cookies.clear()

    assert client.get(tornado_url(main)).status_code == 401
    assert client.get(grid_url(main), params={"x": "beta", "y": "beta"}).status_code == 401


def test_the_tornado_ranks_the_inputs_by_their_effect_on_the_dcf_value(client: TestClient) -> None:
    main = main_id(client)

    started = time.perf_counter()
    body = ok(client.get(tornado_url(main)))
    elapsed = time.perf_counter() - started

    assert elapsed < 2
    assert (body["scenario_id"], body["case"]) == (main, "base")
    assert D(body["base_value"]) == base_value(client, main)
    bars = body["bars"]
    codes = [b["code"] for b in bars]
    assert {"revenue_growth", "gross_margin", "discount_rate", "terminal_growth"} <= set(codes)
    assert "exit_multiple" not in codes
    ranges = [D(b["range"]) for b in bars if b["range"] is not None]
    assert ranges == sorted(ranges, reverse=True)
    rate = next(b for b in bars if b["code"] == "discount_rate")
    assert (rate["kind"], rate["unit"], D(rate["step"]), rate["mode"]) == (
        "valuation", "pct", D("0.005"), "add",
    )  # fmt: skip
    assert D(rate["low_value"]) > D(rate["high_value"])  # a lower rate values higher
    assert D(rate["low_change"]) == D(rate["low_value"]) - D(body["base_value"])
    margin = next(b for b in bars if b["code"] == "gross_margin")
    assert (margin["kind"], margin["unit"], margin["mode"]) == ("driver", "pct", "add")


def test_the_exit_multiple_replaces_terminal_growth_when_it_is_the_terminal_method(
    client: TestClient,
) -> None:
    main = main_id(client)
    put_inputs(client, main, "base", terminal_method="exit_multiple")

    codes = [b["code"] for b in ok(client.get(tornado_url(main)))["bars"]]

    assert "exit_multiple" in codes and "terminal_growth" not in codes


def test_the_grid_center_is_the_base_value(client: TestClient) -> None:
    main = main_id(client)
    started = time.perf_counter()

    body = ok(client.get(grid_url(main), params={"x": "discount_rate", "y": "terminal_growth"}))

    assert time.perf_counter() - started < 2
    assert D(body["base_value"]) == base_value(client, main)
    assert len(body["values"]) == 5 and all(len(r) == 5 for r in body["values"])
    assert D(body["values"][2][2]) == D(body["base_value"])
    assert body["x"]["code"] == "discount_rate" and body["y"]["code"] == "terminal_growth"
    assert [D(s) for s in body["x"]["shifts"]] == [D(k) * D("0.005") for k in (-2, -1, 0, 1, 2)]
    assert len(body["x"]["points"]) == 5 and body["errors"][2][2] is None
    # a higher rate lowers the value along x; a higher growth raises it down y
    assert D(body["values"][2][0]) > D(body["values"][2][4])
    assert D(body["values"][0][2]) < D(body["values"][4][2])
    center_upside = body["upside"][2][2]
    assert D(center_upside) == pytest.approx(D(body["base_value"]) / D(body["price"]) - 1)


def test_a_grid_over_two_drivers(client: TestClient) -> None:
    main = main_id(client)

    body = ok(client.get(grid_url(main), params={"x": "revenue_growth", "y": "gross_margin"}))

    assert D(body["values"][2][2]) == D(body["base_value"])
    assert D(body["values"][2][4]) > D(body["values"][2][0])
    assert D(body["values"][4][2]) > D(body["values"][0][2])
    assert body["x"]["points"][2] is not None


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"x": "foo", "y": "beta"}, "Unknown sensitivity input 'foo'"),
        ({"x": "discount_rate", "y": "discount_rate"}, "Pick two different inputs"),
        ({"x": "exit_multiple", "y": "discount_rate"}, "Unknown sensitivity input 'exit_multiple'"),
    ],
)
def test_a_bad_grid_request_is_a_422(
    client: TestClient, params: dict[str, str], message: str
) -> None:
    main = main_id(client)

    response = client.get(grid_url(main), params=params)

    assert response.status_code == 422 and response.json() == {"detail": message}


def test_a_base_dcf_error_is_a_422_for_both_routes(client: TestClient) -> None:
    main = main_id(client)
    put_inputs(client, main, "base", discount_method="direct", discount_rate="0.03",
               terminal_growth="0.05")  # fmt: skip

    tornado = client.get(tornado_url(main))
    grid = client.get(grid_url(main), params={"x": "discount_rate", "y": "terminal_growth"})

    for response in (tornado, grid):
        assert response.status_code == 422
        assert "must exceed terminal growth" in response.json()["detail"]


def test_a_failed_point_is_a_null_cell_with_its_text(client: TestClient) -> None:
    main = main_id(client)
    put_inputs(client, main, "base", discount_method="direct", discount_rate="0.03",
               terminal_growth="0.02")  # fmt: skip

    body = ok(client.get(grid_url(main), params={"x": "discount_rate", "y": "terminal_growth"}))

    assert body["values"][4][0] is None and "must exceed terminal growth" in body["errors"][4][0]
    assert body["upside"][4][0] is None


def test_another_company_s_scenario_is_a_404(client: TestClient) -> None:
    msft = main_id(client, "MSFT")

    assert client.get(tornado_url(msft)).status_code == 404
    assert client.get(grid_url(msft), params={"x": "beta", "y": "tax_rate"}).status_code == 404


def test_the_same_input_twice_is_refused_before_the_base_is_valued(client: TestClient) -> None:
    main = main_id(client)
    put_inputs(client, main, "base", discount_method="direct", discount_rate="0.03",
               terminal_growth="0.05")  # fmt: skip

    response = client.get(grid_url(main), params={"x": "beta", "y": "beta"})

    assert response.status_code == 422
    assert response.json() == {"detail": "Pick two different inputs"}
