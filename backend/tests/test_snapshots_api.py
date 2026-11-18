"""Frozen scenarios through the API (FR-ACC-01, -02; docs/erd/accountability.md "Snapshots",
"Scoring", "API"), on the recorded fixtures with the later filings withheld."""

from collections.abc import Callable, Generator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bedrock.backtest.scoring import SCORED_CODES
from bedrock.models.company import Company
from bedrock.models.corporate_action import CorporateAction

from .accountability_data import withhold_filings
from .valuation_api import case_url, main_id, scenarios_url, set_gross_margin

API = "/api/v1/companies"
CUTOFF = date(2024, 11, 1)
AAPL_FY2025_REVENUE = Decimal("416161000000")
Restore = Callable[[], None]
D = Decimal


def snapshots_url(ticker: str, scenario_id: int) -> str:
    return f"{scenarios_url(ticker)}/{scenario_id}/snapshots"


def take(client: TestClient, scenario_id: int, ticker: str = "AAPL", **body: Any) -> dict[str, Any]:
    response = client.post(snapshots_url(ticker, scenario_id), json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


@pytest.fixture
def aapl(seed_db: Callable[..., None], authed_client: TestClient) -> TestClient:
    seed_db("AAPL")
    return authed_client


@pytest.fixture
def session(app: FastAPI, aapl: TestClient) -> Generator[Session, None, None]:
    with app.state.session_factory() as opened:
        yield opened


@pytest.fixture
def restore(session: Session) -> Restore:
    """The filings after CUTOFF are withheld; calling this lets them land."""
    return withhold_filings(session, CUTOFF)


def test_the_routes_require_a_session(aapl: TestClient) -> None:
    main = main_id(aapl)
    aapl.cookies.clear()

    assert aapl.post(snapshots_url("AAPL", main), json={}).status_code == 401
    assert aapl.get(f"{API}/AAPL/snapshots").status_code == 401
    assert aapl.get(f"{API}/AAPL/snapshots/1").status_code == 401


def test_post_freezes_the_three_cases(aapl: TestClient, restore: Restore) -> None:
    main = main_id(aapl)

    created = take(aapl, main, note="  before the print  ")

    assert created["scenario_id"] == main
    assert created["scenario_name"] == "Main"
    assert created["note"] == "before the print"
    assert created["data_as_of"] == CUTOFF.isoformat()
    assert created["failed_cases"] == []
    assert created["scored_periods"] == 0
    assert created["revenue_mape"] is None
    assert created["created_at"]
    detail = aapl.get(f"{API}/AAPL/snapshots/{created['id']}").json()
    assert [c["case"] for c in detail["cases"]] == ["base", "bull", "bear"]
    assert all(c["error"] is None and c["lines"] for c in detail["cases"])


def test_a_note_of_500_characters_is_kept_and_one_longer_is_refused(aapl: TestClient) -> None:
    main = main_id(aapl)

    too_long = aapl.post(snapshots_url("AAPL", main), json={"note": "x" * 501})
    assert too_long.status_code == 422
    assert "500" in too_long.json()["detail"]
    assert aapl.get(f"{API}/AAPL/snapshots").json()["snapshots"] == []

    assert take(aapl, main, note="x" * 500)["note"] == "x" * 500


@pytest.mark.parametrize("note", ["", "   ", None])
def test_a_blank_note_is_null(aapl: TestClient, note: str | None) -> None:
    assert take(aapl, main_id(aapl), note=note)["note"] is None


def test_an_unknown_scenario_is_404(aapl: TestClient) -> None:
    assert aapl.post(snapshots_url("AAPL", 999_999), json={}).status_code == 404


def test_another_companys_scenario_is_404(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL", "MSFT")
    msft = main_id(authed_client, "MSFT")

    assert authed_client.post(snapshots_url("AAPL", msft), json={}).status_code == 404


def test_a_case_that_cannot_run_is_stored_with_its_error(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    """DE has no gross-margin default: with it set on Bull alone, Base and Bear cannot run."""
    seed_db("DE")
    main = main_id(authed_client, "DE")
    path = case_url("DE", main, "bull", "drivers")
    years = authed_client.get(path).json()["forecast_years"]
    row = {
        "driver_code": "gross_margin",
        "kind": "value",
        "values": [{"fiscal_year": y, "value": "0.3"} for y in years],
    }
    assert authed_client.put(path, json={"rows": [row]}).status_code == 200

    created = take(authed_client, main, "DE")

    assert created["failed_cases"] == ["base", "bear"]
    detail = authed_client.get(f"{API}/DE/snapshots/{created['id']}").json()
    by_case = {c["case"]: c for c in detail["cases"]}
    assert "gross_margin" in by_case["base"]["error"]
    assert by_case["base"]["lines"] == [] and by_case["base"]["valuation"] == []
    assert by_case["bull"]["error"] is None and by_case["bull"]["lines"]


def test_all_cases_failing_is_422_and_stores_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)
    switch = {"revenue_method": "segments", "segment_dimension": "business"}
    assert aapl.put(f"{scenarios_url('AAPL')}/{main}", json=switch).status_code == 200

    response = aapl.post(snapshots_url("AAPL", main), json={})

    assert response.status_code == 422
    assert "segments have no" in response.json()["detail"]
    assert aapl.get(f"{API}/AAPL/snapshots").json() == {"snapshots": [], "summary": []}


def detail_of(client: TestClient, snapshot_id: int, ticker: str = "AAPL") -> dict[str, Any]:
    response = client.get(f"{API}/{ticker}/snapshots/{snapshot_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def case_of(detail: dict[str, Any], case: str) -> dict[str, Any]:
    found: dict[str, Any] = next(c for c in detail["cases"] if c["case"] == case)
    return found


def cell(
    detail: dict[str, Any],
    case: str,
    code: str,
    year: int,
    period: str = "FY",
    group: str = "lines",
) -> dict[str, Any]:
    series = next(s for s in case_of(detail, case)[group] if s["code"] == code)
    found: dict[str, Any] = next(
        c for c in series["cells"] if (c["fiscal_year"], c["fiscal_period"]) == (year, period)
    )
    return found


def frozen(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """What a snapshot froze: all of its cases but the scores, which move with the actuals."""
    scores = {"actual", "pct_error", "in_range"}

    def cells(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {**s, "cells": [{k: v for k, v in c.items() if k not in scores} for c in s["cells"]]}
            for s in series
        ]

    return [
        {**c, "lines": cells(c["lines"]), "drivers": cells(c["drivers"])} for c in detail["cases"]
    ]


def test_an_unknown_or_another_companys_snapshot_is_404(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL", "MSFT")
    created = take(authed_client, main_id(authed_client))

    assert authed_client.get(f"{API}/AAPL/snapshots/999999").status_code == 404
    assert authed_client.get(f"{API}/MSFT/snapshots/{created['id']}").status_code == 404


def test_the_list_is_newest_first(aapl: TestClient) -> None:
    main = main_id(aapl)
    first, second = take(aapl, main), take(aapl, main)

    listed = aapl.get(f"{API}/AAPL/snapshots").json()["snapshots"]

    assert [s["id"] for s in listed] == [second["id"], first["id"]]


def test_the_detail_has_every_stored_line_and_the_frozen_valuations(aapl: TestClient) -> None:
    detail = detail_of(aapl, take(aapl, main_id(aapl))["id"])

    base = case_of(detail, "base")
    codes = {s["code"] for s in base["lines"]}
    assert set(SCORED_CODES) < codes and "total_assets" in codes
    revenue = next(s for s in base["lines"] if s["code"] == "revenue")
    assert (revenue["label"], revenue["unit"]) == ("Revenue", "USD")
    periods = [c["fiscal_period"] for c in revenue["cells"]]
    assert periods[:5] == ["FY"] * 5 and periods[5] != "FY"  # the years first
    assert periods.count("FY") == 5 and len(periods) > 5
    assert [c["horizon"] for c in revenue["cells"][:5]] == [1, 2, 3, 4, 5]
    assert revenue["cells"][0]["label"].startswith("FY")
    assert base["drivers"] and all(c["source"] for s in base["drivers"] for c in s["cells"])
    dcf = next(v for v in base["valuation"] if v["key"] == "dcf_fcff")
    assert D(dcf["value_per_share"]) > 0 and dcf["error"] is None


def test_a_snapshot_is_unchanged_by_everything_that_happens_later(
    aapl: TestClient, restore: Restore
) -> None:
    created = aapl.post(
        scenarios_url("AAPL"), json={"name": "Alt", "revenue_method": "growth"}
    ).json()
    alt = created["id"]
    snapshot = take(aapl, alt)
    before = detail_of(aapl, snapshot["id"])

    set_gross_margin(aapl, alt, "AAPL", "0.5")
    engines = {"rows": [{"driver_code": "gross_margin", "engine": "ets"}]}
    assert aapl.put(f"{scenarios_url('AAPL')}/{alt}/engines", json=engines).status_code == 200
    assert aapl.post(case_url("AAPL", alt, "bull", "reset")).status_code == 200
    restore()
    assert aapl.post(f"{API}/AAPL/refresh").status_code == 200
    assert aapl.delete(f"{scenarios_url('AAPL')}/{alt}").status_code == 204

    after = detail_of(aapl, snapshot["id"])
    assert frozen(after) == frozen(before)
    assert after["scenario_id"] is None
    assert after["scenario_name"] == "Alt"
    assert after["created_at"] == before["created_at"]


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_a_snapshot_cannot_be_written_to(aapl: TestClient, method: str) -> None:
    snapshot = take(aapl, main_id(aapl))

    response = getattr(aapl, method)(f"{API}/AAPL/snapshots/{snapshot['id']}")

    assert response.status_code == 405


def test_a_snapshot_is_scored_once_the_actuals_land(aapl: TestClient, restore: Restore) -> None:
    created = take(aapl, main_id(aapl))
    withheld = detail_of(aapl, created["id"])
    assert all(
        c["actual"] is None
        for case in withheld["cases"]
        for group in ("lines", "drivers")
        for series in case[group]
        for c in series["cells"]
    )
    assert withheld["scored_periods"] == 0 and withheld["revenue_mape"] is None
    assert aapl.get(f"{API}/AAPL/snapshots").json()["summary"] == []

    restore()

    detail = detail_of(aapl, created["id"])
    base = cell(detail, "base", "revenue", 2025)
    assert D(base["actual"]) == AAPL_FY2025_REVENUE
    expected = (D(base["forecast"]) - AAPL_FY2025_REVENUE) / AAPL_FY2025_REVENUE
    assert abs(D(base["pct_error"]) - expected) < D("0.000000001")
    bull, bear = cell(detail, "bull", "revenue", 2025), cell(detail, "bear", "revenue", 2025)
    low, high = sorted((D(bull["forecast"]), D(bear["forecast"])))
    assert low < high
    assert base["in_range"] is (low <= AAPL_FY2025_REVENUE <= high)
    assert bull["in_range"] is None and bear["in_range"] is None
    assert detail["scored_periods"] >= 1
    assert D(detail["revenue_mape"]) >= abs(expected) / detail["scored_periods"]


def test_a_drivers_range_is_its_engines_band(aapl: TestClient, restore: Restore) -> None:
    created = take(aapl, main_id(aapl))
    restore()

    margin = cell(detail_of(aapl, created["id"]), "base", "gross_margin", 2025, group="drivers")

    assert margin["source"] == "engine"
    low, high, actual = D(margin["p05"]), D(margin["p95"]), D(margin["actual"])
    assert low < high
    assert margin["in_range"] is (low <= actual <= high)


def test_the_summary_has_rows_by_metric_case_and_horizon(
    aapl: TestClient, restore: Restore
) -> None:
    take(aapl, main_id(aapl))
    restore()

    summary = aapl.get(f"{API}/AAPL/snapshots").json()["summary"]

    revenue = [
        r for r in summary if (r["kind"], r["code"], r["freq"]) == ("line", "revenue", "annual")
    ]
    assert {r["method"] for r in revenue} == {"base", "bull", "bear"}
    base = next(r for r in revenue if r["method"] == "base" and r["horizon"] == 1)
    assert (base["label"], base["unit"], base["n"], base["n_range"]) == ("Revenue", "USD", 1, 1)
    assert D(base["mape"]) >= 0 and D(base["hit_rate"]) in (0, 1)
    bull = next(r for r in revenue if r["method"] == "bull" and r["horizon"] == 1)
    assert bull["hit_rate"] is None and bull["n_range"] == 0
    assert {r["code"] for r in summary if r["kind"] == "line"} <= set(SCORED_CODES)
    assert any(r["kind"] == "driver" and r["code"] == "gross_margin" for r in summary)


def test_a_split_after_the_snapshot_restates_its_share_lines_only(
    aapl: TestClient, restore: Restore, session: Session
) -> None:
    created = take(aapl, main_id(aapl))
    restore()
    before = detail_of(aapl, created["id"])
    company_id: int = session.execute(select(Company.id)).scalar_one()
    session.add(
        CorporateAction(
            company_id=company_id,
            type="split",
            effective_date=date.fromisoformat(created["created_at"][:10]) + timedelta(days=1),
            ratio=D(2),
            source="manual",
        )
    )
    session.commit()

    after = detail_of(aapl, created["id"])

    was, now = cell(before, "base", "eps_diluted", 2025), cell(after, "base", "eps_diluted", 2025)
    assert abs(D(now["forecast"]) - D(was["forecast"]) / 2) < D("0.000001")
    assert abs(D(now["actual"]) - D(was["actual"]) / 2) < D("0.000001")
    assert abs(D(now["pct_error"]) - D(was["pct_error"])) < D("0.000001")
    assert (
        cell(after, "base", "revenue", 2025)["forecast"]
        == cell(before, "base", "revenue", 2025)["forecast"]
    )


def test_unfollowing_removes_the_snapshots(aapl: TestClient, session: Session) -> None:
    take(aapl, main_id(aapl))

    assert aapl.delete(f"{API}/AAPL").status_code == 204

    session.rollback()
    for table in ("forecast_snapshot", "forecast_run", "forecast_value", "valuation_run"):
        assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


# --- M7d S4: the classification mode a snapshot was taken under ---------------------------------


def test_a_snapshot_records_the_companys_classification_mode(
    aapl: TestClient, session: Session
) -> None:
    main = main_id(aapl)
    off = take(aapl, main)
    company = session.scalars(select(Company).where(Company.ticker == "AAPL")).one()
    company.classification_mode = "accepted"
    session.commit()

    accepted = take(aapl, main)

    assert off["classification_mode"] == "off"
    assert accepted["classification_mode"] == "accepted"
    listed = aapl.get(f"{API}/AAPL/snapshots").json()["snapshots"]
    assert [s["classification_mode"] for s in listed] == ["accepted", "off"]
    assert detail_of(aapl, accepted["id"])["classification_mode"] == "accepted"


def test_a_snapshot_older_than_the_mode_has_none(aapl: TestClient, session: Session) -> None:
    created = take(aapl, main_id(aapl))
    session.execute(
        text("UPDATE forecast_snapshot SET classification_mode = NULL WHERE id = :id"),
        {"id": created["id"]},
    )
    session.commit()

    assert detail_of(aapl, created["id"])["classification_mode"] is None
    listed = aapl.get(f"{API}/AAPL/snapshots").json()["snapshots"]
    assert listed[0]["classification_mode"] is None


def test_a_manual_snapshot_reads_origin_manual(aapl: TestClient) -> None:
    created = take(aapl, main_id(aapl))

    assert created["origin"] == "manual"
    assert aapl.get(f"{API}/AAPL/snapshots").json()["snapshots"][0]["origin"] == "manual"
    assert detail_of(aapl, created["id"])["origin"] == "manual"


def test_the_snapshot_a_refresh_takes_reads_origin_auto(aapl: TestClient, session: Session) -> None:
    withhold_filings(session, date(2026, 5, 1))  # the Q3 FY26 10-Q has not landed

    refreshed = aapl.post(f"{API}/AAPL/refresh").json()

    assert refreshed["snapshot_id"] is not None
    (listed,) = aapl.get(f"{API}/AAPL/snapshots").json()["snapshots"]
    assert listed["id"] == refreshed["snapshot_id"]
    assert listed["origin"] == "auto"
    assert listed["note"] == "Before the 10-Q filed 2026-07-31"
    assert detail_of(aapl, listed["id"])["origin"] == "auto"
