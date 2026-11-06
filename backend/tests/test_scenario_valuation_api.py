"""A case's valuation and a scenario's three-case summary through the API (FR-VAL-01..03,
docs/erd/valuation.md "API"), on the recorded AAPL, MSFT and DE fixtures."""

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .valuation_api import case_url, main_id, ok, put_inputs, scenarios_url, set_gross_margin

D = Decimal


@pytest.fixture
def client(seed_db: Callable[..., None], authed_client: TestClient) -> TestClient:
    seed_db("AAPL", "MSFT", "DE")
    return authed_client


def valuation(client: TestClient, main: int, case: str, ticker: str = "AAPL") -> Any:
    return client.get(case_url(ticker, main, case, "valuation"))


def result(body: dict[str, Any], key: str) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in body["results"] if r["key"] == key)
    return found


def manual_targets(client: TestClient, main: int, case: str = "base") -> None:
    response = put_inputs(
        client, main, case,
        pe_source="manual", pe_multiple="25",
        ev_ebitda_source="manual", ev_ebitda_multiple="18",
    )  # fmt: skip
    assert response.status_code == 200, response.text


def test_the_routes_require_a_session(client: TestClient) -> None:
    main = main_id(client)
    client.cookies.clear()

    assert valuation(client, main, "base").status_code == 401
    assert client.get(f"{scenarios_url('AAPL')}/{main}/valuation").status_code == 401


def test_a_case_is_valued_by_dcf_and_the_manual_multiples_against_the_close(
    client: TestClient,
) -> None:
    main = main_id(client)
    manual_targets(client, main)

    body = ok(valuation(client, main, "base"))

    assert [r["key"] for r in body["results"]] == ["dcf_fcff", "multiple:pe", "multiple:ev_ebitda"]
    price = D(body["price"])
    assert body["price_date"] and body["valuation_date"] == body["price_date"]
    assert D(body["shares"]) > 0
    assert set(body["bridge"]) == {
        "total_debt", "cash", "short_term_investments", "minority_interest",
        "temporary_equity", "net_claims",
    }  # fmt: skip
    for key in ("dcf_fcff", "multiple:pe", "multiple:ev_ebitda"):
        r = result(body, key)
        assert r["error"] is None
        assert D(r["upside"]) == pytest.approx(D(r["value_per_share"]) / price - 1)
        assert D(r["enterprise_value"]) - D(r["equity_value"]) == D(body["bridge"]["net_claims"])
    dcf = result(body, "dcf_fcff")
    assert dcf["multiple"] is None and len(dcf["dcf"]["periods"]) == 5
    assert dcf["dcf"]["terminal"]["method"] == "gordon"
    assert dcf["dcf"]["discount"]["method"] == "wacc"
    pe = result(body, "multiple:pe")
    assert pe["dcf"] is None and pe["multiple"]["ratio_code"] == "pe"
    assert pe["multiple"]["source"] == "manual" and pe["multiple"]["comps_set"] is None


def test_the_default_own_history_target_reports_its_error_not_a_422(client: TestClient) -> None:
    main = main_id(client)

    body = ok(valuation(client, main, "base"))

    pe = result(body, "multiple:pe")
    assert pe["error"] == "P/E: fewer than 3 years of history"
    assert pe["value_per_share"] is None and pe["upside"] is None
    assert result(body, "dcf_fcff")["error"] is None


def test_bull_values_above_base_above_bear(client: TestClient) -> None:
    main = main_id(client)

    values = {
        case: D(result(ok(valuation(client, main, case)), "dcf_fcff")["value_per_share"])
        for case in ("base", "bull", "bear")
    }

    assert values["bull"] > values["base"] > values["bear"]


def test_a_direct_rate_and_an_exit_multiple_value(client: TestClient) -> None:
    main = main_id(client)
    put_inputs(
        client, main, "base",
        discount_method="direct", discount_rate="0.1",
        terminal_method="exit_multiple", exit_multiple="14",
    )  # fmt: skip

    dcf = result(ok(valuation(client, main, "base")), "dcf_fcff")

    assert dcf["error"] is None
    assert dcf["dcf"]["discount"]["method"] == "direct"
    assert D(dcf["dcf"]["discount"]["rate"]) == D("0.1")
    terminal = dcf["dcf"]["terminal"]
    assert terminal["method"] == "exit_multiple" and D(terminal["exit_multiple"]) == 14
    assert terminal["implied_growth"] is not None


def test_a_dcf_error_is_the_results_error_with_a_200(client: TestClient) -> None:
    main = main_id(client)
    put_inputs(client, main, "base", discount_method="direct", discount_rate="0.03",
               terminal_growth="0.05")  # fmt: skip

    dcf = result(ok(valuation(client, main, "base")), "dcf_fcff")

    assert dcf["error"] is not None and "must exceed terminal growth" in dcf["error"]
    assert dcf["value_per_share"] is None


def test_de_needs_its_gross_margin_then_values_with_the_debt_caveat(client: TestClient) -> None:
    de = main_id(client, "DE")

    unavailable = valuation(client, de, "base", "DE")
    assert unavailable.status_code == 422
    assert unavailable.json() == {"detail": "Set these drivers: gross_margin"}

    set_gross_margin(client, de, "DE", "0.25")
    body = ok(valuation(client, de, "base", "DE"))

    assert "John Deere Financial" in (result(body, "dcf_fcff")["caveat"] or "")


def test_the_summary_lists_the_three_cases_with_the_union_of_methods(client: TestClient) -> None:
    main = main_id(client)
    manual_targets(client, main)
    put_inputs(client, main, "bull", p_fcf_source="manual", p_fcf_multiple="30")

    body = ok(client.get(f"{scenarios_url('AAPL')}/{main}/valuation"))

    assert [c["case"] for c in body["cases"]] == ["base", "bull", "bear"]
    assert [m["key"] for m in body["methods"]] == [
        "dcf_fcff", "multiple:pe", "multiple:ev_ebitda", "multiple:p_fcf",
    ]  # fmt: skip
    assert body["methods"][0]["label"] == "DCF (FCFF)"
    base, bull, _ = body["cases"]
    assert base["error"] is None and "multiple:p_fcf" not in base["value_per_share"]
    assert bull["value_per_share"]["multiple:p_fcf"] is not None
    assert D(bull["value_per_share"]["dcf_fcff"]) > D(base["value_per_share"]["dcf_fcff"])
    price = D(body["price"])
    assert D(base["upside"]["dcf_fcff"]) == pytest.approx(
        D(base["value_per_share"]["dcf_fcff"]) / price - 1
    )


def test_a_case_error_is_in_the_summary_not_a_422(client: TestClient) -> None:
    de = main_id(client, "DE")

    body = ok(client.get(f"{scenarios_url('DE')}/{de}/valuation"))

    assert body["methods"] == []
    assert body["cases"][0] == {
        "case": "base", "label": "Base", "value_per_share": {}, "upside": {}, "errors": {},
        "error": "Set these drivers: gross_margin",
    }  # fmt: skip


def test_another_company_s_scenario_is_a_404(client: TestClient) -> None:
    msft = main_id(client, "MSFT")

    assert valuation(client, msft, "base").status_code == 404
    assert client.get(f"{scenarios_url('AAPL')}/{msft}/valuation").status_code == 404


def test_each_valuation_request_answers_within_two_seconds(client: TestClient) -> None:
    main = main_id(client)
    manual_targets(client, main)

    for url in (
        case_url("AAPL", main, "base", "valuation"),
        f"{scenarios_url('AAPL')}/{main}/valuation",
    ):
        started = time.perf_counter()
        ok(client.get(url))
        assert time.perf_counter() - started < 2
