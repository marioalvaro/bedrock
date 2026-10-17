"""Custom quality-of-earnings rules through the API (FR-ANL-10)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock
from bedrock.models.qoe_custom_rule import QoeCustomRule

CUSTOM = "/api/v1/qoe-custom-rules"
RULES = "/api/v1/qoe-rules"

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

BODY: dict[str, Any] = {
    "label": "Accruals (mine)",
    "formula": "(net_income - cfo) / avg(total_assets)",
    "direction": "above",
    "unit": "pct",
    "warn": "0.05",
    "alert": "0.10",
}


@pytest.fixture
def clock(app: FastAPI) -> list[datetime]:
    moment = [NOW]
    app.dependency_overrides[get_clock] = lambda: moment[0]
    return moment


@pytest.fixture
def api(clock: list[datetime], authed_client: TestClient) -> TestClient:
    return authed_client


def _stored(db_session: Session) -> list[QoeCustomRule]:
    db_session.expire_all()
    return list(db_session.scalars(select(QoeCustomRule).order_by(QoeCustomRule.id)))


def _create(api: TestClient, **changes: Any) -> dict[str, Any]:
    response = api.post(CUSTOM, json={**BODY, **changes})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_every_custom_rule_route_requires_a_session(client: TestClient) -> None:
    assert client.get(CUSTOM).status_code == 401
    assert client.post(CUSTOM, json=BODY).status_code == 401
    assert client.put(f"{CUSTOM}/1", json=BODY).status_code == 401
    assert client.delete(f"{CUSTOM}/1").status_code == 401


def test_crud_round_trip(api: TestClient, clock: list[datetime], db_session: Session) -> None:
    first = _create(api)
    second = _create(api, label="Second", formula="cfo / net_income")

    assert first["code"] == f"custom_{first['id']}"
    assert (first["warn"], first["alert"]) == ("0.05", "0.1")
    assert (first["warn_formula"], first["alert_formula"], first["error"]) == (None, None, None)
    listed = api.get(CUSTOM).json()
    assert [r["id"] for r in listed] == [first["id"], second["id"]]

    clock[0] = NOW + timedelta(minutes=1)
    response = api.put(
        f"{CUSTOM}/{first['id']}",
        json={
            "label": "Renamed",
            "formula": "cfo / net_income",
            "direction": "below",
            "unit": "x",
            "warn": "1",
            "alert": None,
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert (updated["label"], updated["formula"], updated["direction"], updated["unit"]) == (
        "Renamed",
        "cfo / net_income",
        "below",
        "x",
    )
    assert (updated["warn"], updated["alert"]) == ("1", None)
    assert updated["created_at"] == first["created_at"]
    assert updated["updated_at"] != first["updated_at"]
    [row, _] = _stored(db_session)
    assert row.updated_at == (NOW + timedelta(minutes=1)).replace(tzinfo=None)

    assert api.delete(f"{CUSTOM}/{first['id']}").status_code == 204
    assert [r["id"] for r in api.get(CUSTOM).json()] == [second["id"]]


def test_the_label_is_stripped_and_a_blank_one_is_a_422(
    api: TestClient, db_session: Session
) -> None:
    assert _create(api, label="  Mine  ")["label"] == "Mine"
    before = len(_stored(db_session))

    response = api.post(CUSTOM, json={**BODY, "label": "   "})

    assert response.status_code == 422, response.text
    assert len(_stored(db_session)) == before


def test_an_unknown_name_in_the_formula_says_where(api: TestClient, db_session: Session) -> None:
    response = api.post(CUSTOM, json={**BODY, "formula": "revenu / 2"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown name 'revenu' at 0"
    assert _stored(db_session) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"warn": "revenu * 2"},
        {"warn": "0.2", "alert": "0.1"},  # above: alert < warn
        {"warn": "0.05", "alert": "1E+400"},
        {"warn": "1/0"},
    ],
)
def test_an_invalid_level_is_a_422_and_stores_nothing(
    api: TestClient, db_session: Session, changes: dict[str, Any]
) -> None:
    assert api.post(CUSTOM, json={**BODY, **changes}).status_code == 422
    assert _stored(db_session) == []


def test_a_failed_update_changes_nothing(api: TestClient, db_session: Session) -> None:
    created = _create(api)

    response = api.put(f"{CUSTOM}/{created['id']}", json={**BODY, "formula": "nope"})

    assert response.status_code == 422
    assert api.get(CUSTOM).json() == [created]


def test_an_unknown_id_is_a_404(api: TestClient) -> None:
    assert api.put(f"{CUSTOM}/99", json=BODY).status_code == 404
    assert api.put(f"{CUSTOM}/99", json={**BODY, "formula": "nope"}).status_code == 404
    assert api.delete(f"{CUSTOM}/99").status_code == 404


def test_levels_are_stored_as_numbers_or_as_formula_text(
    api: TestClient, db_session: Session
) -> None:
    created = _create(api, warn="5%", alert="prev(sbc / revenue) + 0.2")
    other = _create(api, warn="0.05", alert=None)

    assert (created["warn"], created["warn_formula"]) == ("0.05", None)
    assert (created["alert"], created["alert_formula"]) == (
        None,
        "prev(sbc / revenue) + 0.2",
    )
    assert (other["warn"], other["alert"]) == ("0.05", None)
    first, _ = _stored(db_session)
    assert (first.warn, first.warn_formula) == (Decimal("0.05"), None)
    assert (first.alert, first.alert_formula) == (None, "prev(sbc / revenue) + 0.2")


def test_a_broken_stored_formula_is_listed_with_an_error(
    api: TestClient, db_session: Session
) -> None:
    now = NOW.replace(tzinfo=None)
    db_session.add(
        QoeCustomRule(
            label="Broken",
            formula="revenu / 2",
            direction="above",
            unit="x",
            warn=Decimal("1"),
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()

    response = api.get(CUSTOM)

    assert response.status_code == 200, response.text
    [row] = response.json()
    assert row["error"] == "Unknown name 'revenu' at 0"
    listed = api.get(RULES)
    assert listed.status_code == 200
    mine = listed.json()[-1]
    assert (mine["custom"], mine["error"]) == (True, "Unknown name 'revenu' at 0")


def _store(db_session: Session, **fields: Any) -> None:
    now = NOW.replace(tzinfo=None)
    base: dict[str, Any] = {
        "label": "Stored",
        "formula": "cfo / net_income",
        "direction": "above",
        "unit": "x",
        "created_at": now,
        "updated_at": now,
    }
    db_session.add(QoeCustomRule(**{**base, **fields}))
    db_session.commit()


def test_a_broken_stored_level_is_listed_with_an_error_and_keeps_its_text(
    api: TestClient, db_session: Session
) -> None:
    _store(db_session, alert_formula="revenu")

    [row] = api.get(CUSTOM).json()

    assert row["error"] == "Unknown name 'revenu' at 0"
    assert row["alert_formula"] == "revenu"
    assert row["formula"] == "cfo / net_income"


def test_the_value_formula_error_wins_over_the_level_errors(
    api: TestClient, db_session: Session
) -> None:
    _store(db_session, formula="revenu / 2", warn_formula="cfoo", alert_formula="netincome")

    [row] = api.get(CUSTOM).json()

    assert row["error"] == "Unknown name 'revenu' at 0"
    _store(db_session, formula="cfo / net_income", warn_formula="cfoo", alert_formula="netincome")
    second = api.get(CUSTOM).json()[1]
    assert second["error"] == "Unknown name 'cfoo' at 0"  # warn before alert


@pytest.mark.parametrize(
    ("changes", "ending"),
    [
        ({"warn": "1/3"}, None),  # more than 10 decimal places
        ({"warn": "NaN"}, None),
        ({"formula": "a" * 501}, " at 500"),
        ({"formula": "(" * 33 + "cfo" + ")" * 33}, None),
        ({"direction": "sideways"}, None),
        ({"unit": "days"}, None),
    ],
    ids=["many-places", "nan", "long-formula", "deep-nesting", "direction", "unit"],
)
def test_an_out_of_contract_body_is_a_422_and_stores_nothing(
    api: TestClient, db_session: Session, changes: dict[str, Any], ending: str | None
) -> None:
    response = api.post(CUSTOM, json={**BODY, **changes})

    assert response.status_code == 422, response.text
    if ending is not None:
        assert str(response.json()["detail"]).endswith(ending)
    assert _stored(db_session) == []


def test_a_custom_rule_is_in_the_rule_list_after_the_built_ins(api: TestClient) -> None:
    created = _create(api)

    body = api.get(RULES).json()

    assert len(body) == 9
    last = body[-1]
    assert last["code"] == created["code"]
    assert last["custom"] is True
    assert last["formula"] == BODY["formula"]
    assert (last["default_warn"], last["default_alert"]) == (None, None)
    assert (last["warn"], last["alert"], last["overridden"]) == ("0.05", "0.1", False)
    assert last["error"] is None
    assert all(r["custom"] is False for r in body[:-1])


def test_a_custom_code_cannot_be_overridden_or_reset(api: TestClient) -> None:
    code = _create(api)["code"]

    assert api.put(f"{RULES}/{code}", json={"warn": "1", "alert": "2"}).status_code == 404
    assert api.delete(f"{RULES}/{code}").status_code == 404
