"""The quality-of-earnings flags route over followed companies (recorded fixtures, no network).
FR-ANL-05."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.analysis.qoe import DEFAULT_RULES_PATH
from bedrock.models.qoe_custom_rule import QoeCustomRule
from bedrock.models.qoe_threshold import QoeThreshold

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
    "custom",
    "warn_formula",
    "alert_formula",
    "warn_levels",
    "alert_levels",
    "error",
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
def msft_db(seed_db: Callable[..., None]) -> None:
    seed_db("MSFT")


@pytest.fixture
def msft_client(msft_db: None, authed_client: TestClient) -> TestClient:
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


# --- custom rules and formula levels (FR-ANL-10) ---------------------------------------------

CUSTOM = "/api/v1/qoe-custom-rules"
ACCRUALS = {
    "label": "Accruals (mine)",
    "formula": "(net_income - cfo) / avg(total_assets)",
    "direction": "above",
    "unit": "pct",
    "warn": "0.05",
    "alert": "0.10",
}


@pytest.mark.parametrize("freq", ["annual", "ttm"])
def test_a_custom_rule_matches_the_built_in_it_copies(msft_client: TestClient, freq: str) -> None:
    created = msft_client.post(CUSTOM, json=ACCRUALS)
    assert created.status_code == 201, created.text

    body = get_flags(msft_client, freq=freq)

    assert body["rules"][-1]["code"] == created.json()["code"]
    mine = body["rules"][-1]
    builtin = rule(body, "accruals_ratio")
    assert mine["custom"] is True and builtin["custom"] is False
    assert mine["values"] == builtin["values"]
    assert mine["severity"] == builtin["severity"]
    assert mine["error"] is None
    n = len(body["periods"])
    judged = [v is not None for v in mine["values"]]
    assert mine["warn_levels"] == ["0.05" if j else None for j in judged]
    assert mine["alert_levels"] == ["0.1" if j else None for j in judged]
    assert len(mine["warn_levels"]) == len(mine["alert_levels"]) == len(mine["severity"]) == n


def test_a_formula_level_is_judged_per_period(msft_client: TestClient) -> None:
    put = msft_client.put(SBC_RULE, json={"warn": "prev(sbc / revenue) + 1%", "alert": None})
    assert put.status_code == 200, put.text

    body = get_flags(msft_client)
    sbc = rule(body, "sbc_to_revenue")

    assert sbc["warn_formula"] == "prev(sbc / revenue) + 1%"
    assert sbc["warn"] is None
    values = [None if v is None else Decimal(v) for v in sbc["values"]]
    levels = [None if v is None else Decimal(v) for v in sbc["warn_levels"]]
    assert levels[0] is None
    for i in range(1, len(values)):
        previous = values[i - 1]
        if previous is None:
            assert levels[i] is None
        else:
            # the level is prev(sbc / revenue) + 1 % quantized once; the value is quantized first
            assert abs(levels[i] - (previous + Decimal("0.01"))) <= Decimal("0.000001")
    for value, level, severity in zip(values, levels, sbc["severity"], strict=True):
        if value is None:
            assert severity is None
        else:
            assert severity == ("warn" if level is not None and value > level else "none")
    # non-vacuity: some level is judged. No period is a "warn": MSFT's SBC share never rises by more
    # than one point year on year (real values), so every judged severity is "none"; the warn
    # branch of the loop above is covered by the unit test in test_qoe.py (sbc_inputs).
    assert any(level is not None for level in levels)
    assert any(v is not None for v in values) and "none" in sbc["severity"]


def test_a_deleted_custom_rule_leaves_the_flags(msft_client: TestClient) -> None:
    created = msft_client.post(CUSTOM, json=ACCRUALS).json()
    assert created["code"] in [r["code"] for r in get_flags(msft_client)["rules"]]

    assert msft_client.delete(f"{CUSTOM}/{created['id']}").status_code == 204

    assert [r["code"] for r in get_flags(msft_client)["rules"]] == YAML_CODES


def test_a_stored_broken_custom_rule_is_an_error_row_not_a_failure(
    msft_client: TestClient, db_session: Session
) -> None:
    db_session.add(QoeCustomRule(label="Broken", formula="revenu / 2", direction="above", unit="x"))
    db_session.commit()

    body = get_flags(msft_client)

    mine = body["rules"][-1]
    assert mine["custom"] is True
    assert mine["error"] == "Unknown name 'revenu' at 0"
    n = len(body["periods"])
    for key in ("values", "severity", "warn_levels", "alert_levels"):
        assert mine[key] == [None] * n, key
    assert rule(body, "accruals_ratio")["error"] is None


def test_a_stored_broken_override_is_an_error_row_not_a_failure(
    msft_client: TestClient, db_session: Session
) -> None:
    db_session.add(QoeThreshold(rule_code="sbc_to_revenue", warn_formula="revenu"))
    db_session.commit()

    body = get_flags(msft_client)

    sbc = rule(body, "sbc_to_revenue")
    assert sbc["error"] is not None and "revenu" in sbc["error"]
    n = len(body["periods"])
    assert sbc["values"] == [None] * n and sbc["severity"] == [None] * n
    assert rule(body, "accruals_ratio")["error"] is None


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
