"""The guidance log through the API (FR-ANL-09), on the recorded AAPL fixtures."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.guidance import Guidance

API = "/api/v1"
COMPANY = f"{API}/companies/AAPL"
GUIDANCE = f"{COMPANY}/guidance"
METRICS = f"{GUIDANCE}/metrics"
BILLION = Decimal(1_000_000_000)

REVENUE_FY2024 = Decimal(391_035_000_000)  # AAPL FY2024 10-K: net sales of 391,035 million

ENTRY = {
    "metric": "revenue",
    "fiscal_year": 2024,
    "fiscal_period": "FY",
    "low": "380000000000",
    "high": "390000000000",
    "basis": "reported",
    "given_on": "2024-01-15",
}


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post(f"{API}/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def post(client: TestClient, **override: Any) -> dict[str, Any]:
    response = client.post(GUIDANCE, json={**ENTRY, **override})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def log(client: TestClient) -> dict[str, Any]:
    response = client.get(GUIDANCE)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def statement_value(client: TestClient, statement: str, freq: str, code: str, period: str) -> Any:
    response = client.get(
        f"{COMPANY}/statements", params={"type": statement, "freq": freq, "basis": "reported"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    row = next(r for r in body["rows"] if r["code"] == code)
    value = row["values"][[p["key"] for p in body["periods"]].index(period)]
    return None if value is None else Decimal(value)


def _count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(Guidance)).scalar_one()


# --- guards ----------------------------------------------------------------------------------


def test_every_guidance_route_requires_a_session(client: TestClient) -> None:
    assert client.get(GUIDANCE).status_code == 401
    assert client.get(METRICS).status_code == 401
    assert client.post(GUIDANCE, json=ENTRY).status_code == 401
    assert client.put(f"{GUIDANCE}/1", json=ENTRY).status_code == 401
    assert client.delete(f"{GUIDANCE}/1").status_code == 401


def test_an_unfollowed_ticker_is_a_404_on_every_route(authed_client: TestClient) -> None:
    assert authed_client.get(GUIDANCE).status_code == 404
    assert authed_client.get(METRICS).status_code == 404
    assert authed_client.post(GUIDANCE, json=ENTRY).status_code == 404
    assert authed_client.put(f"{GUIDANCE}/1", json=ENTRY).status_code == 404
    assert authed_client.delete(f"{GUIDANCE}/1").status_code == 404


def test_an_empty_log_has_an_empty_summary(aapl_client: TestClient) -> None:
    body = log(aapl_client)
    assert body["ticker"] == "AAPL" and body["entries"] == [] and body["by_metric"] == []
    assert body["summary"] == {"beat": 0, "in_range": 0, "miss": 0, "pending": 0, "hit_rate": None}


# --- verdicts on reported actuals ------------------------------------------------------------


@pytest.mark.parametrize(
    ("low", "high", "verdict"),
    [
        (380, 390, "beat"),
        (390, 395, "in_range"),
        (395, 400, "miss"),
        (391.035, 391.035, "in_range"),  # a point guidance equal to the actual
    ],
)
def test_aapl_fy2024_revenue_is_judged_against_the_range(
    aapl_client: TestClient, low: float, high: float, verdict: str
) -> None:
    created = post(
        aapl_client, low=str(Decimal(str(low)) * BILLION), high=str(Decimal(str(high)) * BILLION)
    )
    assert Decimal(created["actual"]) == REVENUE_FY2024
    assert created["verdict"] == verdict
    assert created["latest"] is True


def test_the_created_entry_carries_every_field(aapl_client: TestClient) -> None:
    created = post(aapl_client, source_note="  Q4 call  ")
    assert set(created) == {
        "id",
        "metric",
        "label",
        "unit",
        "fiscal_year",
        "fiscal_period",
        "low",
        "high",
        "basis",
        "direction",
        "given_on",
        "source_note",
        "actual",
        "verdict",
        "surprise",
        "latest",
        "created_at",
        "updated_at",
    }
    assert (created["label"], created["unit"]) == ("Revenue", "USD")
    assert (created["direction"], created["given_on"]) == ("higher", "2024-01-15")
    assert created["source_note"] == "Q4 call"
    assert Decimal(created["low"]) == 380 * BILLION
    # (391.035 - 385) / 385 B
    assert Decimal(created["surprise"]) == Decimal("0.015675")


def test_a_blank_source_note_is_stored_as_null(aapl_client: TestClient) -> None:
    assert post(aapl_client, source_note="   ")["source_note"] is None
    assert post(aapl_client, metric="sga", low="1", high="2")["source_note"] is None


def test_a_cost_line_defaults_to_lower_is_better_and_flips_the_verdict(
    aapl_client: TestClient,
) -> None:
    sga = statement_value(aapl_client, "IS", "annual", "sga", "FY2024")
    above = {"metric": "sga", "low": str(sga - 2 * BILLION), "high": str(sga - BILLION)}
    below = {"metric": "sga", "low": str(sga + BILLION), "high": str(sga + 2 * BILLION)}

    expensive = post(aapl_client, **above)  # the actual is over the range: bad for a cost
    assert (expensive["direction"], expensive["verdict"]) == ("lower", "miss")
    cheap = post(aapl_client, **below)
    assert cheap["verdict"] == "beat"
    # the same range judged as a higher-is-better one
    flipped = post(aapl_client, **above, direction="higher")
    assert (flipped["direction"], flipped["verdict"]) == ("higher", "beat")


def test_a_normalized_entry_changes_verdict_after_an_adjustment_and_a_reported_one_does_not(
    aapl_client: TestClient,
) -> None:
    sga = statement_value(aapl_client, "IS", "annual", "sga", "FY2024")
    band = {"metric": "sga", "low": str(sga - BILLION // 2), "high": str(sga + BILLION // 2)}
    reported = post(aapl_client, **band, basis="reported")
    normalized = post(aapl_client, **band, basis="normalized")
    assert (reported["verdict"], normalized["verdict"]) == ("in_range", "in_range")
    assert Decimal(normalized["actual"]) == sga

    adjustment = {
        "canonical_code": "sga",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "amount": str(-BILLION),
        "category": "one-off",
        "reason": "test",
    }
    assert aapl_client.post(f"{COMPANY}/adjustments", json=adjustment).status_code == 201

    entries = {e["basis"]: e for e in log(aapl_client)["entries"]}
    assert (entries["reported"]["verdict"], Decimal(entries["reported"]["actual"])) == (
        "in_range",
        sga,
    )
    assert (entries["normalized"]["verdict"], Decimal(entries["normalized"]["actual"])) == (
        "beat",
        sga - BILLION,
    )


# --- ratios, quarters, KPIs ------------------------------------------------------------------


def test_an_annual_ratio_is_read_from_the_annual_ratio_table(aapl_client: TestClient) -> None:
    table = aapl_client.get(f"{COMPANY}/ratios", params={"freq": "annual"}).json()
    margin = next(r for r in table["rows"] if r["code"] == "gross_margin")
    expected = Decimal(margin["values"][[p["key"] for p in table["periods"]].index("FY2024")])
    created = post(aapl_client, metric="gross_margin", low="0.4", high="0.45")
    assert Decimal(created["actual"]) == expected
    assert (created["unit"], created["verdict"]) == ("pct", "beat")


def test_a_quarterly_margin_is_that_quarters_numerator_over_its_revenue(
    aapl_client: TestClient,
) -> None:
    revenue = statement_value(aapl_client, "IS", "quarterly", "revenue", "FY2024Q4")
    gross = statement_value(aapl_client, "IS", "quarterly", "gross_profit", "FY2024Q4")
    created = post(aapl_client, metric="gross_margin", fiscal_period="Q4", low="0.45", high="0.46")
    assert Decimal(created["actual"]) == (gross / revenue).quantize(Decimal("0.000001"))
    assert created["verdict"] in {"beat", "in_range", "miss"}


def test_a_quarterly_line_is_read_from_the_quarterly_table(aapl_client: TestClient) -> None:
    revenue = statement_value(aapl_client, "IS", "quarterly", "revenue", "FY2024Q3")
    created = post(aapl_client, fiscal_period="Q3", low="1", high="2")
    assert (Decimal(created["actual"]), created["verdict"]) == (revenue, "beat")


def test_a_balance_sheet_line_is_read_from_the_balance_sheet(aapl_client: TestClient) -> None:
    cash = statement_value(aapl_client, "BS", "annual", "cash", "FY2024")
    created = post(aapl_client, metric="cash", low="1", high="2")
    assert Decimal(created["actual"]) == cash


def test_a_ratio_other_than_a_margin_cannot_be_guided_on_a_quarter(
    aapl_client: TestClient,
) -> None:
    response = aapl_client.post(GUIDANCE, json={**ENTRY, "metric": "roe", "fiscal_period": "Q2"})
    assert response.status_code == 422
    assert "roe" in response.json()["detail"]
    assert log(aapl_client)["entries"] == []


def test_a_period_without_data_is_pending(aapl_client: TestClient) -> None:
    created = post(aapl_client, fiscal_year=2031)
    assert (created["actual"], created["verdict"], created["surprise"]) == (None, "pending", None)


def test_a_kpi_entry_reads_the_kpi_series_and_is_pending_without_a_value(
    aapl_client: TestClient,
) -> None:
    series = aapl_client.post(
        f"{COMPANY}/segment-series",
        json={"dimension": "kpi", "name": "Stores", "metric": "stores", "unit": "count"},
    ).json()
    pending = post(aapl_client, metric="kpi:stores", low="520", high="530")
    assert (pending["actual"], pending["verdict"], pending["label"]) == (None, "pending", "Stores")
    assert pending["unit"] == "count"

    values = {"values": [{"fiscal_year": 2024, "fiscal_period": "FY", "value": "535"}]}
    response = aapl_client.put(f"{COMPANY}/segment-series/{series['id']}/values", json=values)
    assert response.status_code == 200

    (entry,) = log(aapl_client)["entries"]
    assert (Decimal(entry["actual"]), entry["verdict"]) == (Decimal(535), "beat")


def test_a_kpi_that_was_deleted_leaves_a_pending_entry_with_no_unit(
    aapl_client: TestClient,
) -> None:
    series = aapl_client.post(
        f"{COMPANY}/segment-series",
        json={"dimension": "kpi", "name": "Stores", "metric": "stores", "unit": "count"},
    ).json()
    post(aapl_client, metric="kpi:stores", low="1", high="2")
    assert aapl_client.delete(f"{COMPANY}/segment-series/{series['id']}").status_code == 204

    (entry,) = log(aapl_client)["entries"]
    assert (entry["verdict"], entry["unit"], entry["label"]) == ("pending", None, "kpi:stores")


# --- revisions and the summary ---------------------------------------------------------------


def test_the_summary_counts_only_the_latest_revision_of_each_key(aapl_client: TestClient) -> None:
    beat = post(aapl_client, given_on="2024-01-15")
    in_range = post(aapl_client, low="390000000000", high="395000000000", given_on="2024-04-15")
    miss = post(aapl_client, low="395000000000", high="400000000000", given_on="2024-07-15")
    assert beat["latest"] is True and in_range["latest"] is True  # latest when each was posted

    body = log(aapl_client)
    assert [(e["id"], e["latest"]) for e in body["entries"]] == [
        (beat["id"], False),
        (in_range["id"], False),
        (miss["id"], True),
    ]
    summary = body["summary"]
    assert (summary["beat"], summary["in_range"], summary["miss"], summary["pending"]) == (
        0,
        0,
        1,
        0,
    )
    assert Decimal(summary["hit_rate"]) == 0
    (revenue,) = body["by_metric"]
    assert (revenue["metric"], revenue["label"]) == ("revenue", "Revenue")
    assert (revenue["miss"], Decimal(revenue["hit_rate"])) == (1, Decimal(0))


def test_the_hit_rate_is_over_the_decided_latest_entries(aapl_client: TestClient) -> None:
    post(aapl_client)  # beat
    post(aapl_client, metric="net_income_common", low="1", high="1000000000000")  # in range
    post(aapl_client, metric="cost_of_revenue", low="1", high="2")  # lower: over the range
    post(aapl_client, fiscal_year=2031)  # pending
    summary = log(aapl_client)["summary"]
    assert {k: summary[k] for k in ("beat", "in_range", "miss", "pending")} == {
        "beat": 1,
        "in_range": 1,
        "miss": 1,
        "pending": 1,
    }
    assert Decimal(summary["hit_rate"]) == Decimal("0.666667")


def test_entries_are_ordered_by_year_period_metric_and_given_on(aapl_client: TestClient) -> None:
    ids = [
        post(aapl_client, fiscal_year=2025)["id"],
        post(aapl_client, fiscal_year=2024, fiscal_period="Q1")["id"],
        post(aapl_client, fiscal_year=2024, metric="sga", low="1", high="2")["id"],
        post(aapl_client, fiscal_year=2024, given_on="2024-03-01")["id"],
        post(aapl_client, fiscal_year=2024, given_on="2024-02-01")["id"],
    ]
    shown = [e["id"] for e in log(aapl_client)["entries"]]
    # 2024 FY: revenue (given Feb, Mar) then sga; then 2024 Q1; then 2025
    assert shown == [ids[4], ids[3], ids[2], ids[1], ids[0]]


# --- update and delete -----------------------------------------------------------------------


def test_update_replaces_the_entry_and_judges_it_again(aapl_client: TestClient) -> None:
    created = post(aapl_client)
    changed = {**ENTRY, "low": "395000000000", "high": "400000000000", "source_note": "revised"}
    response = aapl_client.put(f"{GUIDANCE}/{created['id']}", json=changed)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["id"], body["verdict"], body["source_note"]) == (created["id"], "miss", "revised")
    assert len(log(aapl_client)["entries"]) == 1


def test_update_can_move_an_entry_to_another_metric_and_basis(aapl_client: TestClient) -> None:
    created = post(aapl_client)
    changed = {**ENTRY, "metric": "sga", "basis": "normalized", "low": "1", "high": "2"}
    body = aapl_client.put(f"{GUIDANCE}/{created['id']}", json=changed).json()
    assert (body["metric"], body["basis"], body["direction"]) == ("sga", "normalized", "lower")


def test_delete_removes_the_entry_and_unknown_ids_are_404(aapl_client: TestClient) -> None:
    created = post(aapl_client)
    assert aapl_client.delete(f"{GUIDANCE}/{created['id']}").status_code == 204
    assert log(aapl_client)["entries"] == []
    assert aapl_client.delete(f"{GUIDANCE}/{created['id']}").status_code == 404
    assert aapl_client.put(f"{GUIDANCE}/9999", json=ENTRY).status_code == 404


def test_an_entry_of_another_company_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post(f"{API}/companies", json={"ticker": "MSFT"}).status_code == 201
    created = post(aapl_client)
    other = f"{API}/companies/MSFT/guidance/{created['id']}"
    assert aapl_client.put(other, json=ENTRY).status_code == 404
    assert aapl_client.delete(other).status_code == 404
    assert len(log(aapl_client)["entries"]) == 1
    assert aapl_client.get(f"{API}/companies/MSFT/guidance").json()["entries"] == []


def test_deleting_the_company_removes_its_guidance(
    aapl_client: TestClient, db_session: Session
) -> None:
    post(aapl_client)
    post(aapl_client, fiscal_year=2025)
    assert _count(db_session) == 2
    assert aapl_client.delete(COMPANY).status_code == 204
    assert _count(db_session) == 0


# --- validation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"metric": "not_a_metric"},
        {"metric": ""},
        {"metric": "kpi:nope"},
        {"metric": "kpi:"},
        {"low": "11", "high": "10"},
        {"low": "1e15", "high": "1e15"},
        {"low": "-1e15"},
        {"high": "1e400"},
        {"low": "NaN"},
        {"high": "Infinity"},
        {"fiscal_year": 99},
        {"fiscal_year": 10000},
        {"fiscal_period": "Q5"},
        {"basis": "adjusted"},
        {"direction": "up"},
        {"given_on": "not a date"},
        {"low": None},
    ],
)
def test_an_invalid_entry_is_a_422_and_nothing_is_stored(
    aapl_client: TestClient, db_session: Session, override: dict[str, Any]
) -> None:
    response = aapl_client.post(GUIDANCE, json={**ENTRY, **override})
    assert response.status_code == 422, response.text
    assert _count(db_session) == 0


def test_the_422_detail_says_what_is_wrong(aapl_client: TestClient) -> None:
    detail = aapl_client.post(GUIDANCE, json={**ENTRY, "metric": "revnue"}).json()["detail"]
    assert "revnue" in detail
    detail = aapl_client.post(GUIDANCE, json={**ENTRY, "low": "5", "high": "4"}).json()["detail"]
    assert "low" in detail.lower()


def test_an_invalid_update_leaves_the_entry_unchanged(aapl_client: TestClient) -> None:
    created = post(aapl_client)
    response = aapl_client.put(f"{GUIDANCE}/{created['id']}", json={**ENTRY, "metric": "nope"})
    assert response.status_code == 422
    (entry,) = log(aapl_client)["entries"]
    assert entry["metric"] == "revenue"


def test_the_boundary_values_are_accepted(aapl_client: TestClient) -> None:
    just_under = "999999999999999"
    assert post(aapl_client, low=just_under, high=just_under)["verdict"] == "miss"
    assert post(aapl_client, low="-" + just_under, high="0")["verdict"] == "beat"
    assert post(aapl_client, fiscal_year=1000)["verdict"] == "pending"
    assert post(aapl_client, fiscal_year=9999)["verdict"] == "pending"


# --- the metric list -------------------------------------------------------------------------


def test_the_metric_list_has_lines_ratios_and_the_companys_kpis(aapl_client: TestClient) -> None:
    aapl_client.post(
        f"{COMPANY}/segment-series",
        json={"dimension": "kpi", "name": "Paid subs", "metric": "paid_subs", "unit": "count"},
    )
    response = aapl_client.get(METRICS)
    assert response.status_code == 200
    metrics = response.json()
    by_code = {m["metric"]: m for m in metrics}
    assert len(by_code) == len(metrics)  # one choice per metric

    assert set(metrics[0]) == {
        "metric",
        "label",
        "group",
        "unit",
        "default_direction",
        "quarterly",
    }
    assert by_code["revenue"] == {
        "metric": "revenue",
        "label": "Revenue",
        "group": "line",
        "unit": "USD",
        "default_direction": "higher",
        "quarterly": True,
    }
    assert by_code["sga"]["default_direction"] == "lower"
    assert by_code["cash"]["group"] == "line"
    assert by_code["eps_diluted"]["group"] == "line"  # the statement line, not the ratio

    assert by_code["gross_margin"]["group"] == "ratio"
    assert by_code["gross_margin"]["quarterly"] is True
    assert by_code["roe"] == {**by_code["roe"], "group": "ratio", "unit": "pct", "quarterly": False}
    assert by_code["debt_to_ebitda"]["default_direction"] == "lower"
    assert by_code["pe"]["group"] == "ratio"

    assert by_code["kpi:paid_subs"] == {
        "metric": "kpi:paid_subs",
        "label": "Paid subs",
        "group": "kpi",
        "unit": "count",
        "default_direction": "higher",
        "quarterly": True,
    }
    groups = [m["group"] for m in metrics]
    assert groups == sorted(groups, key=["line", "ratio", "kpi"].index)  # lines, ratios, KPIs


def test_the_quarterly_flag_matches_what_a_quarter_accepts(aapl_client: TestClient) -> None:
    aapl_client.post(
        f"{COMPANY}/segment-series",
        json={"dimension": "kpi", "name": "Stores", "metric": "stores", "unit": "count"},
    )
    representatives: dict[tuple[str, str, bool], dict[str, Any]] = {}
    for metric in aapl_client.get(METRICS).json():
        key = (metric["group"], metric["unit"], metric["quarterly"])
        representatives.setdefault(key, metric)
    assert {k[0] for k in representatives} == {"line", "ratio", "kpi"}
    for metric in representatives.values():
        for period, accepted in (("FY", True), ("Q1", metric["quarterly"])):
            response = aapl_client.post(
                GUIDANCE, json={**ENTRY, "metric": metric["metric"], "fiscal_period": period}
            )
            assert response.status_code == (201 if accepted else 422), (metric, response.text)
