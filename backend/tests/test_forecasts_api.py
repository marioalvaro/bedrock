"""A scenario case's forecast and the comparison of a scenario's cases through the API
(FR-FCST-01, -02, -04, -06; docs/erd/forecasting.md "Scenarios and cases"), on the recorded
fixtures."""

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


def _main(client: TestClient, ticker: str = "AAPL") -> int:
    """The id of the company's default scenario "Main"."""
    response = client.get(_scenarios_url(ticker))
    assert response.status_code == 200, response.text
    return int(next(s["id"] for s in response.json() if s["name"] == "Main"))


def _forecast(
    client: TestClient,
    scenario_id: int,
    case: str,
    type_: str,
    freq: str,
    ticker: str = "AAPL",
) -> Any:
    return client.get(
        f"{_scenarios_url(ticker)}/{scenario_id}/cases/{case}/forecast",
        params={"type": type_, "freq": freq},
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
    forecast = client.get(f"{url}/1/cases/base/forecast", params={"type": "IS", "freq": "annual"})
    assert forecast.status_code == 401
    assert client.get(f"{url}/1/compare").status_code == 401


@pytest.mark.parametrize("case", ["base", "bull", "bear"])
@pytest.mark.parametrize("type_", ["IS", "BS", "CF"])
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_aapl_forecasts_balance_and_follow_the_actuals(
    aapl_client: TestClient, case: str, type_: str, freq: str
) -> None:
    scenario_id = _main(aapl_client)

    started = time.perf_counter()
    body = _ok(_forecast(aapl_client, scenario_id, case, type_, freq))
    elapsed = time.perf_counter() - started

    assert elapsed < 2  # NFR-02: a recompute < 2 s
    assert (body["ticker"], body["statement"], body["freq"], body["basis"]) == (
        "AAPL",
        type_,
        freq,
        "normalized",
    )
    assert (body["scenario_id"], body["case"]) == (scenario_id, case)
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
    main = _main(aapl_client)

    revenue = {
        case: _forecast_values(_ok(_forecast(aapl_client, main, case, "IS", "annual")), "revenue")
        for case in ("base", "bull", "bear")
    }

    for bull, base, bear in zip(revenue["bull"], revenue["base"], revenue["bear"], strict=True):
        assert bull > base > bear


def test_the_three_cases_of_a_segments_scenario_run_on_segments(
    aapl_client: TestClient,
) -> None:
    """The cases share one revenue build, the scenario's (user, 2026-10-31). AAPL's fixtures hold
    no segment series, so every case refuses with the segments method's own error."""
    main = _main(aapl_client)
    switch = {"revenue_method": "segments", "segment_dimension": "business"}
    assert aapl_client.put(f"{_scenarios_url('AAPL')}/{main}", json=switch).status_code == 200

    for case in ("base", "bull", "bear"):
        forecast = _forecast(aapl_client, main, case, "IS", "annual")
        assert forecast.status_code == 422
        assert "segments have no" in forecast.json()["detail"]
        grid = aapl_client.get(f"{_scenarios_url('AAPL')}/{main}/cases/{case}/drivers").json()
        assert "revenue_growth" not in [r["code"] for r in grid["rows"]]


def test_the_first_forecast_year_grows_on_the_last_actual_year(aapl_client: TestClient) -> None:
    body = _ok(_forecast(aapl_client, _main(aapl_client), "base", "IS", "annual"))
    revenue = _row(body, "revenue")
    first = [p["is_forecast"] for p in body["periods"]].index(True)

    assert revenue["yoy"][first] is not None
    assert revenue["common_size"][first] == "1.000000"


def test_de_base_needs_gross_margin_then_runs(authed_client: TestClient) -> None:
    assert authed_client.post("/api/v1/companies", json={"ticker": "DE"}).status_code == 201
    base = _main(authed_client, "DE")

    unavailable = _forecast(authed_client, base, "base", "IS", "annual", "DE")
    assert unavailable.status_code == 422
    assert unavailable.json() == {"detail": "Set these drivers: gross_margin"}

    path = f"{_scenarios_url('DE')}/{base}/cases/base/drivers"
    years = authed_client.get(path).json()["forecast_years"]
    row = {
        "driver_code": "gross_margin",
        "kind": "value",
        "values": [{"fiscal_year": y, "value": "0.25"} for y in years],
    }
    put = authed_client.put(path, json={"rows": [row]})
    assert put.status_code == 200, put.text

    body = _ok(_forecast(authed_client, base, "base", "BS", "annual", "DE"))
    assert all(c["ok"] for c in body["integrity"])


def test_ttm_and_an_unknown_type_are_422(aapl_client: TestClient) -> None:
    main = _main(aapl_client)

    assert _forecast(aapl_client, main, "base", "IS", "ttm").status_code == 422
    assert _forecast(aapl_client, main, "base", "XX", "annual").status_code == 422
    assert _forecast(aapl_client, main, "worst", "IS", "annual").status_code == 422


def test_another_company_s_scenario_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    other = _main(aapl_client, "MSFT")

    assert _forecast(aapl_client, other, "base", "IS", "annual").status_code == 404
    assert _forecast(aapl_client, 999_999, "base", "IS", "annual").status_code == 404


def test_the_forecast_runs_on_the_normalized_history(aapl_client: TestClient) -> None:
    base = _main(aapl_client)
    before = _ok(_forecast(aapl_client, base, "base", "IS", "annual"))
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

    after = _ok(_forecast(aapl_client, base, "base", "IS", "annual"))

    column = [p["key"] for p in after["periods"]].index(last_actual["key"])
    old, new = (D(_row(b, "sga")["values"][column]) for b in (before, after))
    assert new == old - 5_000_000_000
    assert _row(after, "sga")["provenance"][column] == "normalized"
    # a lower SG&A % revenue default lowers every forecast year's SG&A
    for a, b in zip(_forecast_values(after, "sga"), _forecast_values(before, "sga"), strict=True):
        assert a < b


# --- compare ----------------------------------------------------------------------------------


def _compare(client: TestClient, scenario_id: int | None = None, **params: str) -> Any:
    scenario = _main(client) if scenario_id is None else scenario_id
    return client.get(f"{_scenarios_url('AAPL')}/{scenario}/compare", params=params)


def test_compare_gives_the_three_cases_on_the_default_codes(aapl_client: TestClient) -> None:
    main = _main(aapl_client)

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
    assert set(body) == {"periods", "codes", "cases"}
    assert [(c["case"], c["label"]) for c in body["cases"]] == [
        ("base", "Base"),
        ("bull", "Bull"),
        ("bear", "Bear"),
    ]
    base = body["cases"][0]
    assert base["error"] is None
    assert set(base["values"]) == {c["code"] for c in body["codes"]}
    assert all(len(v) == 5 for v in base["values"].values())
    forecast = _ok(_forecast(aapl_client, main, "base", "IS", "annual"))
    assert [D(v) for v in base["values"]["revenue"]] == _forecast_values(forecast, "revenue")


def test_compare_lists_only_the_picked_scenario_s_cases(aapl_client: TestClient) -> None:
    other = aapl_client.post(_scenarios_url("AAPL"), json={"name": "Other"}).json()["id"]
    gm = {
        "driver_code": "gross_margin",
        "kind": "value",
        "values": [],
    }
    years = aapl_client.get(f"{_scenarios_url('AAPL')}/{other}/cases/base/drivers").json()[
        "forecast_years"
    ]
    gm["values"] = [{"fiscal_year": y, "value": "0.3"} for y in years]
    put = aapl_client.put(
        f"{_scenarios_url('AAPL')}/{other}/cases/base/drivers", json={"rows": [gm]}
    )
    assert put.status_code == 200, put.text

    main_body = _ok(_compare(aapl_client, freq="annual", codes="net_income"))
    other_body = _ok(_compare(aapl_client, other, freq="annual", codes="net_income"))

    assert len(main_body["cases"]) == len(other_body["cases"]) == 3
    assert main_body["cases"][0]["values"] != other_body["cases"][0]["values"]
    forecast = _ok(_forecast(aapl_client, other, "bull", "IS", "annual"))
    assert [D(v) for v in other_body["cases"][1]["values"]["net_income"]] == _forecast_values(
        forecast, "net_income"
    )


def test_compare_spans_the_five_forecast_years_of_every_case(aapl_client: TestClient) -> None:
    body = _ok(_compare(aapl_client, freq="annual", codes="revenue,cash"))

    assert len(body["periods"]) == 5
    assert [c["code"] for c in body["codes"]] == ["revenue", "cash"]
    for case in body["cases"]:
        assert all(v is not None for v in case["values"]["revenue"])


def test_compare_quarterly_has_the_forecast_quarters(aapl_client: TestClient) -> None:
    body = _ok(_compare(aapl_client, freq="quarterly"))

    assert len(body["periods"]) >= 4
    assert all(p["fiscal_period"] != "FY" for p in body["periods"])


def test_a_scenario_whose_cases_cannot_run_carries_the_error_on_each(
    aapl_client: TestClient,
) -> None:
    main = _main(aapl_client)
    switch = {"revenue_method": "segments", "segment_dimension": "business"}
    assert aapl_client.put(f"{_scenarios_url('AAPL')}/{main}", json=switch).status_code == 200

    response = _compare(aapl_client, freq="annual")

    body = _ok(response)
    for case in body["cases"]:
        assert case["error"] is not None and "segments have no" in case["error"]
        assert case["values"] == {}


def test_compare_refuses_an_unknown_code_and_ttm(aapl_client: TestClient) -> None:
    response = _compare(aapl_client, freq="annual", codes="revenue,magic")

    assert response.status_code == 422
    assert "magic" in response.json()["detail"]
    assert _compare(aapl_client, freq="ttm").status_code == 422


def test_the_horizon_is_fixed_at_five_years_and_eight_quarters(
    aapl_client: TestClient,
) -> None:
    """User decision 2026-10-31: no scenario setting; every forecast has 5 years and 8 quarters."""
    base = _main(aapl_client)

    annual = _ok(_forecast(aapl_client, base, "base", "IS", "annual"))
    quarterly = _ok(_forecast(aapl_client, base, "base", "BS", "quarterly"))

    years = [p for p in annual["periods"] if p["is_forecast"]]
    assert len(years) == 5
    assert [p["fiscal_year"] for p in years] == list(
        range(years[0]["fiscal_year"], years[0]["fiscal_year"] + 5)
    )
    quarters = [p for p in quarterly["periods"] if p["is_forecast"]]
    # 8 quarters after the opening, extended to the end of that fiscal year
    assert 8 <= len(quarters) <= 11
    assert quarters[-1]["fiscal_period"] == "Q4"
    assert all(c["ok"] for c in annual["integrity"] + quarterly["integrity"])


def test_compare_lists_a_repeated_code_once(aapl_client: TestClient) -> None:
    body = _ok(_compare(aapl_client, freq="annual", codes="revenue,cash,revenue"))

    assert [c["code"] for c in body["codes"]] == ["revenue", "cash"]


def test_a_quarter_override_changes_that_quarter_and_its_year_only(
    aapl_client: TestClient,
) -> None:
    scenario_id = _main(aapl_client)
    url = f"{_scenarios_url('AAPL')}/{scenario_id}/cases/bull"
    plain = _ok(_forecast(aapl_client, scenario_id, "bull", "IS", "quarterly"))
    quarters = [p for p in plain["periods"] if p["is_forecast"]]
    first = quarters[0]
    put = aapl_client.put(
        f"{url}/drivers",
        json={
            "rows": [
                {
                    "driver_code": "gross_margin",
                    "kind": "value",
                    "freq": "quarterly",
                    "values": [
                        {
                            "fiscal_year": first["fiscal_year"],
                            "fiscal_period": first["fiscal_period"],
                            "value": "0.9",
                        }
                    ],
                }
            ]
        },
    )
    assert put.status_code == 200, put.text

    changed = _ok(_forecast(aapl_client, scenario_id, "bull", "IS", "quarterly"))

    assert all(c["ok"] for c in changed["integrity"])
    before = dict(
        zip(
            (p["key"] for p in plain["periods"]), _row(plain, "gross_profit")["values"], strict=True
        )
    )
    after = dict(
        zip(
            (p["key"] for p in changed["periods"]),
            _row(changed, "gross_profit")["values"],
            strict=True,
        )
    )
    revenue = dict(
        zip((p["key"] for p in changed["periods"]), _row(changed, "revenue")["values"], strict=True)
    )
    differing = [k for k in after if after[k] != before[k]]
    assert differing[0] == first["key"]
    assert D(after[first["key"]]) == D(revenue[first["key"]]) * D("0.9")
    # the quarters after it are untouched, as the annual model carries no margin forward
    other_quarters = [p["key"] for p in quarters[1:] if p["fiscal_year"] == first["fiscal_year"]]
    assert all(after[k] == before[k] for k in other_quarters)
    annual = _ok(_forecast(aapl_client, scenario_id, "bull", "IS", "annual"))
    assert all(c["ok"] for c in annual["integrity"])
