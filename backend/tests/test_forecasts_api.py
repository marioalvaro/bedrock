"""A scenario's forecast and the scenario comparison through the API (FR-FCST-01, -02, -04, -06;
docs/erd/forecasting.md "API"), on the recorded fixtures."""

import time
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

D = Decimal


def _scenarios_url(ticker: str) -> str:
    return f"/api/v1/companies/{ticker}/scenarios"


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def _ids(client: TestClient, ticker: str = "AAPL") -> dict[str, int]:
    response = client.get(_scenarios_url(ticker))
    assert response.status_code == 200, response.text
    return {s["name"]: s["id"] for s in response.json()}


def _forecast(
    client: TestClient, scenario_id: int, type_: str, freq: str, ticker: str = "AAPL"
) -> Any:
    return client.get(
        f"{_scenarios_url(ticker)}/{scenario_id}/forecast", params={"type": type_, "freq": freq}
    )


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _row(body: dict[str, Any], code: str) -> dict[str, Any]:
    return next(r for r in body["rows"] if r["code"] == code)


def _forecast_values(body: dict[str, Any], code: str) -> list[Decimal]:
    row = _row(body, code)
    return [D(v) for v, p in zip(row["values"], body["periods"], strict=True) if p["is_forecast"]]


def test_forecast_routes_require_a_session(client: TestClient) -> None:
    url = _scenarios_url("AAPL")
    assert (
        client.get(f"{url}/1/forecast", params={"type": "IS", "freq": "annual"}).status_code == 401
    )
    assert client.get(f"{url}/compare").status_code == 401


@pytest.mark.parametrize("name", ["Base", "Bull", "Bear"])
@pytest.mark.parametrize("type_", ["IS", "BS", "CF"])
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_aapl_forecasts_balance_and_follow_the_actuals(
    aapl_client: TestClient, name: str, type_: str, freq: str
) -> None:
    scenario_id = _ids(aapl_client)[name]

    started = time.perf_counter()
    body = _ok(_forecast(aapl_client, scenario_id, type_, freq))
    elapsed = time.perf_counter() - started

    assert elapsed < 2  # NFR-02: a recompute < 2 s
    assert (body["ticker"], body["statement"], body["freq"], body["basis"]) == (
        "AAPL",
        type_,
        freq,
        "normalized",
    )
    assert body["scenario_id"] == scenario_id
    assert isinstance(body["warnings"], list)
    periods = body["periods"]
    flags = [p["is_forecast"] for p in periods]
    actual = 3 if freq == "annual" else 4
    assert flags[:actual] == [False] * actual
    assert all(flags[actual:]) and len(flags) > actual
    forecast_keys = [p["key"] for p in periods if p["is_forecast"]]
    if freq == "annual":
        assert len(forecast_keys) == 5
        assert all(p["fiscal_period"] == "FY" for p in periods)
        assert all(p["label"].endswith("E") for p in periods if p["is_forecast"])
    else:
        assert len(forecast_keys) >= 4
        assert all(p["fiscal_period"] != "FY" for p in periods)
    # every integrity check is ok, one per forecast period shown
    assert [c["period_key"] for c in body["integrity"]] == forecast_keys
    assert all(c["ok"] for c in body["integrity"])
    assert set(body["integrity"][0]) == {
        "period_key",
        "balance_diff",
        "cash_diff",
        "re_diff",
        "quarters_diff",
        "ok",
    }
    for row in body["rows"]:
        for provenance, flag in zip(row["provenance"], flags, strict=True):
            if flag:
                assert provenance in ("forecast", None)
            else:
                assert provenance != "forecast"
    if type_ == "BS":
        assert [c["period_key"] for c in body["balance_check"]] == [p["key"] for p in periods]
        assert all(c["ok"] for c in body["balance_check"])
    else:
        assert body["balance_check"] is None


def test_bull_revenue_is_above_base_above_bear_in_every_forecast_year(
    aapl_client: TestClient,
) -> None:
    ids = _ids(aapl_client)

    revenue = {
        name: _forecast_values(_ok(_forecast(aapl_client, ids[name], "IS", "annual")), "revenue")
        for name in ids
    }

    for bull, base, bear in zip(revenue["Bull"], revenue["Base"], revenue["Bear"], strict=True):
        assert bull > base > bear


def test_the_first_forecast_year_grows_on_the_last_actual_year(aapl_client: TestClient) -> None:
    body = _ok(_forecast(aapl_client, _ids(aapl_client)["Base"], "IS", "annual"))
    revenue = _row(body, "revenue")
    first = [p["is_forecast"] for p in body["periods"]].index(True)

    assert revenue["yoy"][first] is not None
    assert revenue["common_size"][first] == "1.000000"


def test_de_base_needs_gross_margin_then_runs(authed_client: TestClient) -> None:
    assert authed_client.post("/api/v1/companies", json={"ticker": "DE"}).status_code == 201
    base = _ids(authed_client, "DE")["Base"]

    unavailable = _forecast(authed_client, base, "IS", "annual", "DE")
    assert unavailable.status_code == 422
    assert unavailable.json() == {"detail": "Set these drivers: gross_margin"}

    years = authed_client.get(f"{_scenarios_url('DE')}/{base}/drivers").json()["forecast_years"]
    row = {
        "driver_code": "gross_margin",
        "kind": "value",
        "values": [{"fiscal_year": y, "value": "0.25"} for y in years],
    }
    put = authed_client.put(f"{_scenarios_url('DE')}/{base}/drivers", json={"rows": [row]})
    assert put.status_code == 200, put.text

    body = _ok(_forecast(authed_client, base, "BS", "annual", "DE"))
    assert all(c["ok"] for c in body["integrity"])


def test_ttm_and_an_unknown_type_are_422(aapl_client: TestClient) -> None:
    base = _ids(aapl_client)["Base"]

    assert _forecast(aapl_client, base, "IS", "ttm").status_code == 422
    assert _forecast(aapl_client, base, "XX", "annual").status_code == 422


def test_another_company_s_scenario_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    other = _ids(aapl_client, "MSFT")["Base"]

    assert _forecast(aapl_client, other, "IS", "annual").status_code == 404
    assert _forecast(aapl_client, 999_999, "IS", "annual").status_code == 404


def test_the_forecast_runs_on_the_normalized_history(aapl_client: TestClient) -> None:
    base = _ids(aapl_client)["Base"]
    before = _ok(_forecast(aapl_client, base, "IS", "annual"))
    last_actual = [p for p in before["periods"] if not p["is_forecast"]][-1]
    adjustment = {
        "canonical_code": "sga",
        "fiscal_year": last_actual["fiscal_year"],
        "fiscal_period": "FY",
        "amount": "-5000000000",
        "category": "one-off",
        "reason": "test",
    }
    added = aapl_client.post("/api/v1/companies/AAPL/adjustments", json=adjustment)
    assert added.status_code == 201, added.text

    after = _ok(_forecast(aapl_client, base, "IS", "annual"))

    column = [p["key"] for p in after["periods"]].index(last_actual["key"])
    old, new = (D(_row(b, "sga")["values"][column]) for b in (before, after))
    assert new == old - 5_000_000_000
    assert _row(after, "sga")["provenance"][column] == "normalized"
    # a lower SG&A % revenue default lowers every forecast year's SG&A
    for a, b in zip(_forecast_values(after, "sga"), _forecast_values(before, "sga"), strict=True):
        assert a < b


# --- compare ----------------------------------------------------------------------------------


def _compare(client: TestClient, **params: str) -> Any:
    return client.get(f"{_scenarios_url('AAPL')}/compare", params=params)


def test_compare_gives_every_scenario_on_the_default_codes(aapl_client: TestClient) -> None:
    ids = _ids(aapl_client)

    body = _ok(_compare(aapl_client, freq="annual"))

    assert [c["code"] for c in body["codes"]] == [
        "revenue",
        "operating_income",
        "net_income",
        "eps_diluted",
        "free_cash_flow",
        "cash",
        "total_debt",
    ]
    assert set(body["codes"][0]) == {"code", "label", "unit"}
    assert len(body["periods"]) == 5 and all(p["is_forecast"] for p in body["periods"])
    assert [s["name"] for s in body["scenarios"]] == ["Base", "Bull", "Bear"]
    assert [s["id"] for s in body["scenarios"]] == list(ids.values())
    base = body["scenarios"][0]
    assert base["error"] is None
    assert set(base["values"]) == {c["code"] for c in body["codes"]}
    assert all(len(v) == 5 for v in base["values"].values())
    forecast = _ok(_forecast(aapl_client, ids["Base"], "IS", "annual"))
    assert [D(v) for v in base["values"]["revenue"]] == _forecast_values(forecast, "revenue")


def test_compare_spans_the_union_of_horizons_with_nulls_where_a_scenario_stops(
    aapl_client: TestClient,
) -> None:
    ids = _ids(aapl_client)
    put = aapl_client.put(f"{_scenarios_url('AAPL')}/{ids['Bull']}", json={"horizon_years": 7})
    assert put.status_code == 200

    body = _ok(_compare(aapl_client, freq="annual", codes="revenue,cash"))

    assert len(body["periods"]) == 7
    assert [c["code"] for c in body["codes"]] == ["revenue", "cash"]
    by_name = {s["name"]: s for s in body["scenarios"]}
    assert all(v is not None for v in by_name["Bull"]["values"]["revenue"])
    assert by_name["Base"]["values"]["revenue"][5:] == [None, None]


def test_compare_quarterly_has_the_forecast_quarters(aapl_client: TestClient) -> None:
    body = _ok(_compare(aapl_client, freq="quarterly"))

    assert len(body["periods"]) >= 4
    assert all(p["fiscal_period"] != "FY" for p in body["periods"])


def test_a_scenario_that_cannot_run_carries_its_error(aapl_client: TestClient) -> None:
    ids = _ids(aapl_client)
    switch = {"revenue_method": "segments", "segment_dimension": "business"}
    assert (
        aapl_client.put(f"{_scenarios_url('AAPL')}/{ids['Bear']}", json=switch).status_code == 200
    )

    body = _ok(_compare(aapl_client, freq="annual"))

    bear = body["scenarios"][2]
    assert bear["error"] is not None and "segments have no" in bear["error"]
    assert bear["values"] == {}
    assert body["scenarios"][0]["error"] is None


def test_compare_refuses_an_unknown_code_and_ttm(aapl_client: TestClient) -> None:
    response = _compare(aapl_client, freq="annual", codes="revenue,magic")

    assert response.status_code == 422
    assert "magic" in response.json()["detail"]
    assert _compare(aapl_client, freq="ttm").status_code == 422


def test_a_ten_year_eight_quarter_horizon_extends_the_forecast_columns(
    aapl_client: TestClient,
) -> None:
    base = _ids(aapl_client)["Base"]
    put = aapl_client.put(
        f"{_scenarios_url('AAPL')}/{base}", json={"horizon_years": 10, "horizon_quarters": 8}
    )
    assert put.status_code == 200, put.text

    annual = _ok(_forecast(aapl_client, base, "IS", "annual"))
    quarterly = _ok(_forecast(aapl_client, base, "BS", "quarterly"))

    years = [p for p in annual["periods"] if p["is_forecast"]]
    assert len(years) == 10
    assert [p["fiscal_year"] for p in years] == list(
        range(years[0]["fiscal_year"], years[0]["fiscal_year"] + 10)
    )
    quarters = [p for p in quarterly["periods"] if p["is_forecast"]]
    # 8 quarters after the opening, extended to the end of that fiscal year
    assert 8 <= len(quarters) <= 11
    assert quarters[-1]["fiscal_period"] == "Q4"
    assert all(c["ok"] for c in annual["integrity"] + quarterly["integrity"])


def test_compare_lists_a_repeated_code_once(aapl_client: TestClient) -> None:
    body = _ok(_compare(aapl_client, freq="annual", codes="revenue,cash,revenue"))

    assert [c["code"] for c in body["codes"]] == ["revenue", "cash"]
