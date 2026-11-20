"""Thesis checkpoints through the API (FR-NOTE-03; docs/erd/workspace.md "Thesis checkpoints"):
CRUD, validation, the states on AAPL's recorded filings and the state before the newest report.
"""

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
from bedrock.models.thesis_checkpoint import ThesisCheckpoint

from .accountability_data import withhold_filings
from .classification_support import parse_filings
from .test_statements_api import classify, set_mode

API = "/api/v1/companies"
AAPL = f"{API}/AAPL/checkpoints"
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
LAST_10Q = date(2026, 7, 31)  # AAPL's newest stored report, Q3 FY2026

KEYS = {
    "id",
    "label",
    "statement",
    "freq",
    "margin",
    "state",
    "previous_state",
    "changed",
    "at_risk_by",
    "period",
    "left",
    "right",
    "gap",
    "unit",
    "error",
    "created_at",
    "updated_at",
}


@pytest.fixture
def clock(app: FastAPI) -> list[datetime]:
    moment = [NOW]
    app.dependency_overrides[get_clock] = lambda: moment[0]
    return moment


@pytest.fixture
def api(
    seed_db: Callable[..., None], clock: list[datetime], authed_client: TestClient
) -> TestClient:
    seed_db("AAPL")
    return authed_client


def create(api: TestClient, **body: Any) -> dict[str, Any]:
    response = api.post(AAPL, json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def listed(api: TestClient) -> dict[str, Any]:
    response = api.get(AAPL)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def stored(session: Session) -> list[ThesisCheckpoint]:
    session.expire_all()
    return list(session.execute(select(ThesisCheckpoint)).scalars())


# --- CRUD --------------------------------------------------------------------------------------


def test_an_empty_list_names_the_newest_report(api: TestClient) -> None:
    assert listed(api) == {
        "report": {"form": "10-Q", "filed_at": LAST_10Q.isoformat()},
        "checkpoints": [],
    }


def test_gross_margin_above_44_percent_holds_on_aapl(api: TestClient) -> None:
    created = create(api, statement="gross_margin > 44%", label="Pricing power")

    assert set(created) == KEYS
    assert created["label"] == "Pricing power"
    assert created["statement"] == "gross_margin > 44%"
    assert (created["freq"], created["margin"]) == ("ttm", None)
    assert (created["state"], created["previous_state"], created["changed"]) == (
        "holding",
        "holding",
        False,
    )
    assert created["at_risk_by"] is None
    assert created["period"] == {"fiscal_year": 2026, "fiscal_period": "Q3", "label": "TTM Q3 FY26"}
    assert Decimal(created["left"]) == Decimal("0.486529")
    assert Decimal(created["right"]) == Decimal("0.44")
    assert Decimal(created["gap"]) == Decimal("0.046529")
    assert created["error"] is None
    assert created["created_at"] == created["updated_at"]
    assert listed(api)["checkpoints"] == [created]


def test_annual_reads_the_last_fiscal_year(api: TestClient) -> None:
    created = create(api, statement="gross_margin > 44%", freq="annual")
    assert created["period"]["label"] == "FY25"
    assert Decimal(created["left"]) == Decimal("0.469052")


@pytest.mark.parametrize(
    ("statement", "unit"),
    [
        ("gross_margin > 44%", "pct"),
        ("revenue > 0", "USD"),
        ("pe < 40", "x"),
        ("gross_profit / revenue > 40%", None),
    ],
)
def test_the_unit_both_sides_are_in(api: TestClient, statement: str, unit: str | None) -> None:
    created = create(api, statement=statement)
    assert created["unit"] == unit
    assert listed(api)["checkpoints"][0]["unit"] == unit


def test_the_list_is_in_id_order(api: TestClient) -> None:
    ids = [create(api, statement=s)["id"] for s in ("revenue > 0", "gross_margin > 1%")]
    assert [c["id"] for c in listed(api)["checkpoints"]] == ids


def test_a_blank_label_becomes_the_canonical_statement(api: TestClient) -> None:
    created = create(api, statement="  gross_margin≥44 %  ", label="   ")
    assert created["statement"] == "gross_margin≥44 %"  # as typed, stripped
    assert created["label"] == "gross_margin >= 44%"


def test_update_replaces_every_field(
    api: TestClient, clock: list[datetime], db_session: Session
) -> None:
    created = create(api, statement="gross_margin > 44%", label="Pricing power", margin="1%")
    clock[0] = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)  # within the session's idle limit

    response = api.put(
        f"{AAPL}/{created['id']}", json={"statement": "revenue > 0", "freq": "annual"}
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert (updated["statement"], updated["label"], updated["freq"], updated["margin"]) == (
        "revenue > 0",
        "revenue > 0",
        "annual",
        None,
    )
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] != created["updated_at"]
    assert len(stored(db_session)) == 1


def test_delete_removes_the_checkpoint(api: TestClient, db_session: Session) -> None:
    created = create(api, statement="revenue > 0")
    assert api.delete(f"{AAPL}/{created['id']}").status_code == 204
    assert stored(db_session) == []


@pytest.mark.parametrize(
    ("method", "body"), [("put", {"statement": "revenue > 0"}), ("delete", None)]
)
def test_an_unknown_id_is_a_404(api: TestClient, method: str, body: Any) -> None:
    response = api.request(method, f"{AAPL}/999", json=body)
    assert response.status_code == 404


def test_another_companys_checkpoint_is_a_404(
    seed_db: Callable[..., None], clock: list[datetime], authed_client: TestClient
) -> None:
    seed_db("AAPL", "MSFT")
    created = authed_client.post(AAPL, json={"statement": "revenue > 0"}).json()
    other = f"{API}/MSFT/checkpoints/{created['id']}"
    assert authed_client.put(other, json={"statement": "revenue > 0"}).status_code == 404
    assert authed_client.delete(other).status_code == 404
    assert authed_client.get(f"{API}/MSFT/checkpoints").json()["checkpoints"] == []


def test_an_unfollowed_company_is_a_404(api: TestClient) -> None:
    assert api.get(f"{API}/ZZZZ/checkpoints").status_code == 404


# --- validation --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "detail"),
    [
        ("gross_margin", "A checkpoint compares two values: use >, >=, < or <= at 0"),
        ("gross_margin > revenu", "Unknown name 'revenu' at 15"),
        ("1 > 2", "A checkpoint needs a line, a metric or a ratio at 0"),
        ("a > b > c", "A checkpoint has one comparison at 6"),
    ],
)
def test_a_bad_statement_is_a_422_naming_the_position(
    api: TestClient, db_session: Session, statement: str, detail: str
) -> None:
    response = api.post(AAPL, json={"statement": statement})
    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert stored(db_session) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"label": "x" * 121},
        {"margin": "-0.01"},
        {"margin": "NaN"},
        {"margin": "Infinity"},
        {"margin": "1e400"},
        {"margin": "1000000"},
        {"margin": "0.00000000001"},
        {"margin": "revenue"},
        {"margin": "1/0"},
        {"margin": "abc"},
        {"margin": "1_0"},
        {"margin": "\u0661"},
        {"freq": "quarterly"},
    ],
)
def test_an_invalid_field_is_a_422_and_stores_nothing(
    api: TestClient, db_session: Session, changes: dict[str, Any]
) -> None:
    response = api.post(AAPL, json={"statement": "revenue > 0", **changes})
    assert response.status_code == 422, response.text
    assert stored(db_session) == []


def test_an_invalid_update_changes_nothing(api: TestClient, db_session: Session) -> None:
    created = create(api, statement="revenue > 0", label="Grows")
    response = api.put(f"{AAPL}/{created['id']}", json={"statement": "revenue >"})
    assert response.status_code == 422
    assert [c.statement for c in stored(db_session)] == ["revenue > 0"]


@pytest.mark.parametrize(
    ("margin", "stored_margin"),
    [("1%", "0.01"), ("0.02", "0.02"), (0.5, "0.5"), ("0", "0"), ("0.0000000001", "1E-10")],
)
def test_a_margin_may_be_a_number_or_a_percent(
    api: TestClient, margin: Any, stored_margin: str
) -> None:
    created = create(api, statement="revenue > 0", margin=margin)
    assert Decimal(created["margin"]) == Decimal(stored_margin)


def test_a_label_of_120_characters_is_kept(api: TestClient) -> None:
    assert create(api, statement="revenue > 0", label="x" * 120)["label"] == "x" * 120


# --- states ------------------------------------------------------------------------------------


def test_a_margin_makes_a_close_checkpoint_at_risk(api: TestClient) -> None:
    created = create(api, statement="gross_margin > 44%", margin="5%")
    assert (created["state"], created["at_risk_by"]) == ("at_risk", "margin")


def test_a_checkpoint_the_newest_10q_breaks_changes_state(
    api: TestClient, db_session: Session
) -> None:
    restore = withhold_filings(db_session, date(2026, 7, 30))
    created = create(api, statement="gross_margin < 48.5%", margin="0.1%")
    assert listed(api)["report"]["filed_at"] == "2026-05-01"
    assert (created["state"], created["previous_state"], created["changed"]) == (
        "holding",
        "holding",
        False,
    )

    restore()  # the 10-Q lands

    after = listed(api)["checkpoints"][0]
    assert listed(api)["report"] == {"form": "10-Q", "filed_at": LAST_10Q.isoformat()}
    assert (after["state"], after["previous_state"], after["changed"]) == (
        "broken",
        "holding",
        True,
    )
    assert after["period"]["fiscal_period"] == "Q3"


def test_an_annual_checkpoint_does_not_move_with_a_10q(api: TestClient) -> None:
    created = create(api, statement="gross_margin < 48.5%", freq="annual", margin="0.1%")
    assert (created["state"], created["previous_state"], created["changed"]) == (
        "holding",
        "holding",
        False,
    )


def test_a_stored_statement_that_no_longer_parses_lists_with_its_error(
    api: TestClient, db_session: Session
) -> None:
    good = create(api, statement="revenue > 0")
    broken = create(api, statement="revenue > 1")
    row = db_session.get(ThesisCheckpoint, broken["id"])
    assert row is not None
    row.statement = "revenu > 1"  # a renamed code
    db_session.commit()

    checkpoints = listed(api)["checkpoints"]

    assert checkpoints[0]["id"] == good["id"] and checkpoints[0]["error"] is None
    assert checkpoints[1]["statement"] == "revenu > 1"
    assert checkpoints[1]["error"] == "Unknown name 'revenu' at 0"
    assert (checkpoints[1]["state"], checkpoints[1]["previous_state"]) == ("unknown", None)
    assert checkpoints[1]["changed"] is False
    assert checkpoints[1]["period"] is None
    assert checkpoints[1]["unit"] is None


def test_a_manual_company_has_no_report_and_unknown_states(
    clock: list[datetime], authed_client: TestClient
) -> None:
    company = {"ticker": "ACME", "name": "Acme Corp", "fiscal_year_end_month": 12}
    assert authed_client.post(f"{API}/manual", json=company).status_code == 201
    url = f"{API}/ACME/checkpoints"

    created = authed_client.post(url, json={"statement": "revenue > 0"}).json()

    assert (created["state"], created["previous_state"], created["changed"]) == (
        "unknown",
        None,
        False,
    )
    assert authed_client.get(url).json()["report"] is None


def test_accepting_a_classification_never_shows_as_a_change(
    api: TestClient, db_session: Session
) -> None:
    # The accepted answer fills AAPL's empty FY2025 goodwill; both reads apply it, so the read
    # moves to FY2025 and yet nothing shows as changed.
    company = parse_filings(db_session)
    unclassified = create(api, statement="goodwill > 0", freq="annual")
    assert unclassified["period"]["label"] == "FY17"  # AAPL last tagged goodwill in FY2017

    classify(db_session, company, status="accepted")
    set_mode(db_session, company, "accepted")

    after = listed(api)["checkpoints"][0]
    assert after["period"]["label"] == "FY25"
    assert Decimal(after["left"]) == Decimal("11093000000")
    assert (after["state"], after["previous_state"], after["changed"]) == (
        "holding",
        "holding",
        False,
    )


def test_one_load_per_frequency_and_read_and_none_without_checkpoints(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bedrock.services import checkpoints as service

    calls: list[tuple[str, date | None]] = []
    real = service.ratio_inputs

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append((args[2], kwargs.get("as_of")))
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "ratio_inputs", spy)
    listed(api)
    assert calls == []

    for statement in ("revenue > 0", "gross_margin > 1%", "net_margin > 1%"):
        create(api, statement=statement)
    create(api, statement="revenue > 0", freq="annual")
    calls.clear()
    listed(api)
    assert sorted(calls, key=str) == sorted(
        [
            ("ttm", None),
            ("ttm", date(2026, 7, 30)),
            ("annual", None),
            ("annual", date(2026, 7, 30)),
        ],
        key=str,
    )
