"""The quality-of-earnings flags route over followed companies (recorded fixtures, no network).
FR-ANL-05."""

from decimal import Decimal
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from bedrock.analysis.qoe import DEFAULT_RULES_PATH

COMPANIES = "/api/v1/companies"
MSFT = f"{COMPANIES}/MSFT"
FLAGS = f"{MSFT}/flags"
ITEMS = f"{MSFT}/off-balance-items"
SBC_RULE = "/api/v1/qoe-rules/sbc_to_revenue"

YAML_CODES: list[str] = [r["code"] for r in yaml.safe_load(DEFAULT_RULES_PATH.read_text())]
RULE_KEYS = {
    "code",
    "label",
    "rule",
    "direction",
    "unit",
    "warn",
    "alert",
    "values",
    "severity",
}
SEVERITIES = {"none", "warn", "alert"}

LEASE = {
    "kind": "lease",
    "description": "Data-center leases not yet commenced",
    "amount": "1500000000",
    "as_of": "2023-06-30",
    "source_note": "Note 14",
}

SGA_FY2024 = {
    "canonical_code": "sga",
    "fiscal_year": 2024,
    "fiscal_period": "FY",
    "amount": "-1000000000",
    "category": "one-off",
    "reason": "test",
}


@pytest.fixture
def msft_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post(COMPANIES, json={"ticker": "MSFT"}).status_code == 201
    return authed_client


def get_flags(client: TestClient, ticker: str = "MSFT", freq: str = "annual") -> dict[str, Any]:
    response = client.get(f"{COMPANIES}/{ticker}/flags", params={"freq": freq})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def rule(body: dict[str, Any], code: str) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in body["rules"] if r["code"] == code)
    return found


# --- guards ----------------------------------------------------------------------------------


def test_flags_require_a_session(client: TestClient) -> None:
    assert client.get(FLAGS, params={"freq": "annual"}).status_code == 401


def test_flags_of_an_unfollowed_company_are_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(FLAGS, params={"freq": "annual"}).status_code == 404


@pytest.mark.parametrize("params", [{"freq": "quarterly"}, {}], ids=["quarterly", "missing-freq"])
def test_bad_freq_is_a_422(msft_client: TestClient, params: dict[str, str]) -> None:
    assert msft_client.get(FLAGS, params=params).status_code == 422


# --- shape -----------------------------------------------------------------------------------


def assert_aligned(body: dict[str, Any]) -> None:
    n = len(body["periods"])
    assert n > 0
    assert [r["code"] for r in body["rules"]] == YAML_CODES
    assert len(YAML_CODES) == 8
    for r in body["rules"]:
        assert set(r) == RULE_KEYS
        assert len(r["values"]) == n and len(r["severity"]) == n
        for v, s in zip(r["values"], r["severity"], strict=True):
            if v is None:
                assert s is None
            else:
                assert s in SEVERITIES


def test_annual_flags_have_the_documented_shape(msft_client: TestClient) -> None:
    body = get_flags(msft_client)

    assert set(body) == {"ticker", "freq", "periods", "rules", "off_balance_items"}
    assert (body["ticker"], body["freq"]) == ("MSFT", "annual")
    assert body["off_balance_items"] == []
    assert all(p["fiscal_period"] == "FY" for p in body["periods"])
    assert_aligned(body)


def test_msft_annual_has_a_judged_flag_in_every_period(msft_client: TestClient) -> None:
    body = get_flags(msft_client)

    for i in range(len(body["periods"])):
        assert any(r["severity"][i] is not None for r in body["rules"]), body["periods"][i]


def test_ttm_flags_are_served(msft_client: TestClient) -> None:
    body = get_flags(msft_client, freq="ttm")

    assert body["freq"] == "ttm"
    assert all(p["key"].startswith("TTM-") for p in body["periods"])
    assert_aligned(body)


# --- pinned values --------------------------------------------------------------------------


def series(body: dict[str, Any], code: str) -> dict[str, tuple[str | None, str | None]]:
    r = rule(body, code)
    keys = [p["key"] for p in body["periods"]]
    return dict(zip(keys, zip(r["values"], r["severity"], strict=True), strict=True))


def test_msft_fy2012_goodwill_impairment_warns(msft_client: TestClient) -> None:
    # FY2012 impairment 6,193,000,000 (aQuantive) over FY2011 goodwill 12,581,000,000 (the
    # MSFT annual BS goodwill row from GET /companies/MSFT/statements?type=BS&freq=annual):
    # 6193 / 12581 = 0.4922502... by hand.
    impairment = series(get_flags(msft_client), "goodwill_impairment")

    assert impairment["FY2012"] == ("0.492250", "warn")
    assert impairment["FY2013"] == ("0.000000", "none")


def test_msft_sbc_to_revenue_is_pinned(msft_client: TestClient) -> None:
    # The default sbc_to_revenue levels are warn 0.05 / alert 0.10; FY2023 is 4.54 % of revenue.
    sbc = series(get_flags(msft_client), "sbc_to_revenue")

    assert sbc["FY2023"] == ("0.045353", "none")


# --- threshold overrides ---------------------------------------------------------------------


def test_an_override_changes_the_severities_until_it_is_reset(msft_client: TestClient) -> None:
    before = rule(get_flags(msft_client), "sbc_to_revenue")
    judged = [v for v in before["values"] if v is not None]
    assert judged and all(Decimal("0.02") <= Decimal(v) < Decimal("0.10") for v in judged)

    put = msft_client.put(SBC_RULE, json={"warn": "0.01", "alert": "0.02"})
    assert put.status_code == 200, put.text
    after = rule(get_flags(msft_client), "sbc_to_revenue")

    assert (Decimal(after["warn"]), Decimal(after["alert"])) == (Decimal("0.01"), Decimal("0.02"))
    assert after["values"] == before["values"]
    assert after["severity"] == [None if v is None else "alert" for v in before["values"]]
    assert after["severity"] != before["severity"]

    assert msft_client.delete(SBC_RULE).status_code == 204
    assert rule(get_flags(msft_client), "sbc_to_revenue") == before


# --- off-balance items -----------------------------------------------------------------------


def test_off_balance_items_are_listed_newest_first_and_per_company(
    msft_client: TestClient,
) -> None:
    assert msft_client.post(COMPANIES, json={"ticker": "AAPL"}).status_code == 201
    older = msft_client.post(ITEMS, json=LEASE)
    newer = msft_client.post(ITEMS, json={**LEASE, "kind": "guarantee", "as_of": "2024-06-30"})
    aapl = msft_client.post(f"{COMPANIES}/AAPL/off-balance-items", json=LEASE)
    assert {older.status_code, newer.status_code, aapl.status_code} == {201}

    items = get_flags(msft_client)["off_balance_items"]

    assert items == [newer.json(), older.json()]
    assert get_flags(msft_client, "AAPL")["off_balance_items"] == [aapl.json()]


# --- reported basis --------------------------------------------------------------------------


def test_flags_ignore_adjustments(msft_client: TestClient) -> None:
    before = get_flags(msft_client)

    created = msft_client.post(f"{MSFT}/adjustments", json=SGA_FY2024)
    assert created.status_code == 201, created.text

    assert get_flags(msft_client) == before
