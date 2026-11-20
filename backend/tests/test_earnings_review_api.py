"""The earnings review through the API (FR-ACC-06; docs/erd/accountability.md "Earnings review"), on
the recorded filings: AAPL with its newest 10-Q withheld, snapshotted, then landed; the MSFT
FY2018 10-K restating FY2017 revenue; a manual company."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock
from bedrock.backtest.review import RESTATED_LIMIT
from bedrock.backtest.scoring import SCORED_CODES
from bedrock.models.company import Company
from bedrock.models.forecast_run import ForecastSnapshot
from bedrock.models.guidance import Guidance

from .accountability_data import withhold_filings
from .classification_support import parse_filings
from .test_statements_api import classify, set_mode
from .valuation_api import main_id, scenarios_url

API = "/api/v1/companies"
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
Q3_FY26 = {
    "accession_no": "0000320193-26-000020",
    "form": "10-Q",
    "filed_at": "2026-07-31",
    "period_end": "2026-06-27",
}
DRIVERS_NOTE = "Drivers are scored on full fiscal years: the next 10-K fills this."

KEYS = {
    "ticker",
    "filing",
    "period",
    "snapshot",
    "lines",
    "drivers",
    "drivers_note",
    "restated",
    "restated_total",
    "flags",
    "checkpoints",
}
LINE_KEYS = {
    "code",
    "label",
    "unit",
    "actual",
    "prior_year",
    "yoy",
    "forecast",
    "low",
    "high",
    "pct_error",
    "in_range",
    "consensus",
    "guidance",
}


@pytest.fixture
def clock(app: FastAPI) -> list[datetime]:
    moment = [NOW]
    app.dependency_overrides[get_clock] = lambda: moment[0]
    return moment


@pytest.fixture
def aapl(
    seed_db: Callable[..., None], clock: list[datetime], authed_client: TestClient
) -> TestClient:
    seed_db("AAPL")
    return authed_client


def review(client: TestClient, ticker: str = "AAPL") -> dict[str, Any]:
    response = client.get(f"{API}/{ticker}/earnings-review")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def line(body: dict[str, Any], code: str) -> dict[str, Any]:
    found: dict[str, Any] = next(row for row in body["lines"] if row["code"] == code)
    return found


def quarterly_value(client: TestClient, statement: str, code: str, key: str) -> Decimal | None:
    response = client.get(
        f"{API}/AAPL/statements",
        params={"type": statement, "freq": "quarterly", "basis": "reported"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    row = next(r for r in body["rows"] if r["code"] == code)
    value = row["values"][[p["key"] for p in body["periods"]].index(key)]
    return None if value is None else Decimal(value)


def snapshot(client: TestClient, note: str | None = None) -> dict[str, Any]:
    url = f"{scenarios_url('AAPL')}/{main_id(client)}/snapshots"
    response = client.post(url, json={"note": note})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(value)


# --- no report, no snapshot --------------------------------------------------------------------


def test_the_route_requires_a_session(client: TestClient) -> None:
    assert client.get(f"{API}/AAPL/earnings-review").status_code == 401


def test_an_unfollowed_ticker_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(f"{API}/ZZZZ/earnings-review").status_code == 404


def test_a_manual_company_has_no_report_and_every_list_empty(
    clock: list[datetime], authed_client: TestClient
) -> None:
    company = {"ticker": "ACME", "name": "Acme Corp", "fiscal_year_end_month": 12}
    assert authed_client.post(f"{API}/manual", json=company).status_code == 201

    assert review(authed_client, "ACME") == {
        "ticker": "ACME",
        "filing": None,
        "period": None,
        "snapshot": None,
        "lines": [],
        "drivers": [],
        "drivers_note": None,
        "restated": [],
        "restated_total": 0,
        "flags": [],
        "checkpoints": [],
    }


def test_a_10q_review_without_a_snapshot_has_the_actuals_and_null_forecasts(
    aapl: TestClient,
) -> None:
    body = review(aapl)

    assert set(body) == KEYS
    assert body["ticker"] == "AAPL"
    assert body["filing"] == Q3_FY26
    assert body["period"] == {"fiscal_year": 2026, "fiscal_period": "Q3", "label": "Q3 FY26"}
    assert body["snapshot"] is None
    assert [row["code"] for row in body["lines"]] == list(SCORED_CODES)
    assert all(set(row) == LINE_KEYS for row in body["lines"])

    revenue = line(body, "revenue")
    actual = quarterly_value(aapl, "IS", "revenue", "FY2026Q3")
    prior = quarterly_value(aapl, "IS", "revenue", "FY2025Q3")
    assert actual is not None and prior is not None
    assert (revenue["label"], revenue["unit"]) == ("Revenue", "USD")
    assert (dec(revenue["actual"]), dec(revenue["prior_year"])) == (actual, prior)
    assert dec(revenue["yoy"]) == (actual / prior - 1).quantize(Decimal("0.000001"))
    assert dec(line(body, "cash")["actual"]) == quarterly_value(aapl, "BS", "cash", "FY2026Q3")
    assert dec(line(body, "free_cash_flow")["actual"]) == quarterly_value(
        aapl, "CF", "free_cash_flow", "FY2026Q3"
    )
    for row in body["lines"]:
        assert (row["forecast"], row["low"], row["high"], row["pct_error"], row["in_range"]) == (
            None,
            None,
            None,
            None,
            None,
        )
        assert (row["consensus"], row["guidance"]) == (None, None)
    assert body["drivers"] == []
    assert body["drivers_note"] == DRIVERS_NOTE


# --- the snapshot taken before the report ------------------------------------------------------


def test_the_snapshot_before_the_report_is_set_beside_the_actuals(
    aapl: TestClient, db_session: Session
) -> None:
    restore = withhold_filings(db_session, date(2026, 5, 1))
    before = snapshot(aapl, "before Q3")
    checkpoint = aapl.post(
        f"{API}/AAPL/checkpoints", json={"statement": "gross_margin < 48.5%", "margin": "0.1%"}
    )
    assert checkpoint.status_code == 201, checkpoint.text
    restore()  # the Q3 FY26 10-Q lands
    snapshot(aapl, "after Q3")  # taken on the new data: not the one before the report

    body = review(aapl)

    assert body["snapshot"] == {
        "id": before["id"],
        "scenario_name": "Main",
        "origin": "manual",
        "created_at": before["created_at"],
        "data_as_of": "2026-05-01",
        "classification_mode": "off",
    }
    detail = aapl.get(f"{API}/AAPL/snapshots/{before['id']}").json()
    cases = {c["case"]: c for c in detail["cases"]}

    def cell(case: str, code: str) -> dict[str, Any]:
        series = next(s for s in cases[case]["lines"] if s["code"] == code)
        found: dict[str, Any] = next(
            c for c in series["cells"] if (c["fiscal_year"], c["fiscal_period"]) == (2026, "Q3")
        )
        return found

    revenue = line(body, "revenue")
    base = cell("base", "revenue")
    forecasts = [Decimal(cell(case, "revenue")["forecast"]) for case in ("base", "bull", "bear")]
    assert dec(revenue["forecast"]) == Decimal(base["forecast"])
    assert (dec(revenue["low"]), dec(revenue["high"])) == (min(forecasts), max(forecasts))
    assert dec(revenue["pct_error"]) == Decimal(base["pct_error"])
    assert revenue["in_range"] == base["in_range"]
    assert revenue["in_range"] is not None
    assert all(row["forecast"] is not None for row in body["lines"])

    assert body["drivers"] == []  # a 10-Q: drivers are annual
    assert body["drivers_note"] == DRIVERS_NOTE

    [changed] = body["checkpoints"]
    assert (changed["id"], changed["state"], changed["previous_state"]) == (
        checkpoint.json()["id"],
        "broken",
        "holding",
    )


def test_a_snapshot_with_no_data_is_never_the_one_before(
    aapl: TestClient, db_session: Session
) -> None:
    restore = withhold_filings(db_session, date(2026, 5, 1))
    taken = snapshot(aapl)
    restore()
    stored = db_session.get(ForecastSnapshot, taken["id"])
    assert stored is not None
    stored.data_as_of = None  # a snapshot of a company with no filing yet
    db_session.commit()

    assert review(aapl)["snapshot"] is None


# --- consensus and guidance --------------------------------------------------------------------


def test_consensus_and_management_guidance_show_with_their_verdicts(
    aapl: TestClient, db_session: Session
) -> None:
    actual = quarterly_value(aapl, "IS", "revenue", "FY2026Q3")
    assert actual is not None
    guidance = f"{API}/AAPL/guidance"
    entry = {"metric": "revenue", "fiscal_year": 2026, "fiscal_period": "Q3", "basis": "reported"}
    low, high = str(actual - 1_000_000_000), str(actual + 1_000_000_000)
    old = {**entry, "low": "1", "high": "2", "given_on": "2026-04-01"}
    management = {**entry, "low": low, "high": high, "given_on": "2026-05-01"}
    normalized = {**management, "basis": "normalized", "low": "1", "high": "2"}
    for body in (old, management, normalized):
        assert aapl.post(guidance, json=body).status_code == 201
    company = db_session.execute(select(Company).where(Company.ticker == "AAPL")).scalar_one()
    db_session.add(
        Guidance(
            company_id=company.id,
            metric="revenue",
            fiscal_year=2026,
            fiscal_period="Q3",
            low=actual * 2,
            high=actual * 2,
            basis="reported",
            direction="higher",
            given_on=date(2026, 7, 1),
            source="consensus",
        )
    )
    db_session.commit()

    revenue = line(review(aapl), "revenue")

    guided = revenue["guidance"]
    assert set(guided) == {"low", "high", "basis", "actual", "verdict", "surprise", "given_on"}
    assert (dec(guided["low"]), dec(guided["high"])) == (Decimal(low), Decimal(high))
    assert (guided["basis"], guided["verdict"], guided["given_on"]) == (
        "reported",
        "in_range",
        "2026-05-01",
    )
    assert (dec(guided["actual"]), dec(guided["surprise"])) == (actual, Decimal(0))
    consensus = revenue["consensus"]
    assert (consensus["verdict"], consensus["given_on"], dec(consensus["low"])) == (
        "miss",
        "2026-07-01",
        actual * 2,
    )
    assert line(review(aapl), "net_income")["guidance"] is None


def test_a_normalized_entry_shows_when_it_is_the_only_one(aapl: TestClient) -> None:
    entry = {
        "metric": "net_income",
        "fiscal_year": 2026,
        "fiscal_period": "Q3",
        "basis": "normalized",
        "low": "1",
        "high": "2",
        "given_on": "2026-05-01",
    }
    assert aapl.post(f"{API}/AAPL/guidance", json=entry).status_code == 201

    guided = line(review(aapl), "net_income")["guidance"]
    assert (guided["basis"], guided["verdict"]) == ("normalized", "beat")


# --- restated values, the MSFT golden ----------------------------------------------------------


def test_the_msft_fy2018_10k_restates_fy2017_revenue(
    seed_db: Callable[..., None],
    clock: list[datetime],
    authed_client: TestClient,
    db_session: Session,
) -> None:
    seed_db("MSFT")
    withhold_filings(db_session, date(2018, 8, 3))  # the FY2018 10-K is the newest report

    body = review(authed_client, "MSFT")

    assert body["filing"]["form"] == "10-K"
    assert body["filing"]["filed_at"] == "2018-08-03"
    assert body["period"] == {"fiscal_year": 2018, "fiscal_period": "FY", "label": "FY18"}
    assert body["drivers_note"] is None
    revenue = next(
        r
        for r in body["restated"]
        if (r["statement"], r["code"], r["fiscal_year"], r["fiscal_period"])
        == ("IS", "revenue", 2017, "FY")
    )
    assert (dec(revenue["before"]), dec(revenue["after"])) == (
        Decimal("89950000000"),
        Decimal("96571000000"),
    )
    assert dec(revenue["pct_change"]) == (Decimal(96571) - 89950) / 89950
    assert revenue["label"] == "Revenue" and revenue["unit"] == "USD"
    assert body["restated_total"] > RESTATED_LIMIT  # ASC 606 restated much of FY2016-17
    assert len(body["restated"]) == RESTATED_LIMIT
    changes = [abs(Decimal(r["pct_change"])) for r in body["restated"] if r["pct_change"]]
    assert changes == sorted(changes, reverse=True)
    assert all(r["fiscal_year"] <= 2017 for r in body["restated"])


# --- classifications never show as a change ----------------------------------------------------


def test_accepting_a_classification_changes_no_restatement_or_flag(
    aapl: TestClient, db_session: Session
) -> None:
    # The accepted answer classifies a line that only the new 10-Q presents; the two reads that
    # say what the filing changed apply no classification (docs/Gotcha.md G55).
    restore = withhold_filings(db_session, date(2026, 5, 1))
    taken = snapshot(aapl)
    restore()
    company = parse_filings(db_session)
    off = review(aapl)

    classify(db_session, company, status="accepted")  # fills AAPL's empty FY2025 goodwill
    set_mode(db_session, company, "accepted")
    accepted = review(aapl)

    assert accepted["restated"] == off["restated"]
    assert accepted["restated_total"] == off["restated_total"]
    assert accepted["flags"] == off["flags"]
    assert accepted["snapshot"]["id"] == taken["id"]
    assert accepted["snapshot"]["classification_mode"] == "off"  # the snapshot's, not the company's
