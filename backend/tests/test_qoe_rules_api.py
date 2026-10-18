"""Global quality-of-earnings threshold overrides through the API (FR-ANL-05)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.analysis.formula import parse
from bedrock.analysis.qoe import DEFAULT_RULES_PATH, Thresholds, formula_names
from bedrock.api.deps import get_clock
from bedrock.models.qoe_threshold import QoeThreshold
from bedrock.services import qoe as service

RULES = "/api/v1/qoe-rules"
SBC = f"{RULES}/sbc_to_revenue"
CFO = f"{RULES}/cfo_to_net_income"

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

YAML_RULES: list[dict[str, object]] = yaml.safe_load(DEFAULT_RULES_PATH.read_text())


def _level(raw: object) -> str | None:
    return None if raw is None else str(Decimal(str(raw)))


@pytest.fixture
def api(app: FastAPI, authed_client: TestClient) -> TestClient:
    app.dependency_overrides[get_clock] = lambda: NOW
    return authed_client


def _rule(api: TestClient, code: str) -> dict[str, object]:
    response = api.get(RULES)
    assert response.status_code == 200, response.text
    return next(r for r in response.json() if r["code"] == code)


def _stored(db_session: Session) -> list[QoeThreshold]:
    db_session.expire_all()
    return list(db_session.scalars(select(QoeThreshold)))


# --- guards ----------------------------------------------------------------------------------


def test_every_qoe_rules_route_requires_a_session(client: TestClient) -> None:
    assert client.get(RULES).status_code == 401
    assert client.put(SBC, json={"warn": "0.01", "alert": "0.02"}).status_code == 401
    assert client.delete(SBC).status_code == 401


def test_an_unknown_code_is_a_404(api: TestClient, db_session: Session) -> None:
    assert api.put(f"{RULES}/nope", json={"warn": "0.01", "alert": "0.02"}).status_code == 404
    assert api.delete(f"{RULES}/nope").status_code == 404
    assert _stored(db_session) == []


# --- list ------------------------------------------------------------------------------------


def test_the_list_has_every_rule_in_yaml_order_with_its_defaults(api: TestClient) -> None:
    response = api.get(RULES)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["code"] for r in body] == [e["code"] for e in YAML_RULES]
    assert len(body) == 8
    for row, entry in zip(body, YAML_RULES, strict=True):
        assert set(row) == {
            "code",
            "label",
            "rule",
            "direction",
            "unit",
            "warn",
            "alert",
            "default_warn",
            "default_alert",
            "overridden",
            "custom",
            "formula",
            "warn_formula",
            "alert_formula",
            "error",
        }
        assert row["label"] == entry["label"]
        assert row["rule"] == entry["rule"]
        assert row["direction"] == entry["direction"]
        assert row["unit"] == entry["unit"]
        assert row["warn"] == row["default_warn"] == _level(entry["warn"])
        assert row["alert"] == row["default_alert"] == _level(entry["alert"])
        assert row["overridden"] is False


# --- set -------------------------------------------------------------------------------------


def test_an_override_changes_the_effective_levels_only(
    api: TestClient, db_session: Session
) -> None:
    response = api.put(SBC, json={"warn": "0.01", "alert": "0.02"})

    assert response.status_code == 200, response.text
    expected = {
        "code": "sbc_to_revenue",
        "warn": "0.01",
        "alert": "0.02",
        "default_warn": "0.05",
        "default_alert": "0.1",
        "overridden": True,
    }
    assert {k: response.json()[k] for k in expected} == expected
    assert {k: _rule(api, "sbc_to_revenue")[k] for k in expected} == expected
    assert _rule(api, "sbc_to_cfo")["overridden"] is False
    [row] = _stored(db_session)
    assert row.updated_at == NOW.replace(tzinfo=None)


def test_a_second_override_replaces_the_first(api: TestClient, db_session: Session) -> None:
    assert api.put(SBC, json={"warn": "0.01", "alert": "0.02"}).status_code == 200
    response = api.put(SBC, json={"warn": "0.03", "alert": "0.04"})

    assert response.status_code == 200, response.text
    assert (response.json()["warn"], response.json()["alert"]) == ("0.03", "0.04")
    [row] = _stored(db_session)
    assert (row.rule_code, row.warn, row.alert) == (
        "sbc_to_revenue",
        Decimal("0.03"),
        Decimal("0.04"),
    )


def test_a_null_level_is_stored_as_no_such_level(api: TestClient, db_session: Session) -> None:
    response = api.put(SBC, json={"warn": "0.01", "alert": None})

    assert response.status_code == 200, response.text
    rule = _rule(api, "sbc_to_revenue")
    assert (rule["warn"], rule["alert"], rule["default_alert"]) == ("0.01", None, "0.1")
    [row] = _stored(db_session)
    assert row.alert is None


def test_both_levels_null_is_an_override_without_levels(
    api: TestClient, db_session: Session
) -> None:
    response = api.put(SBC, json={"warn": None, "alert": None})

    assert response.status_code == 200, response.text
    rule = _rule(api, "sbc_to_revenue")
    assert (rule["warn"], rule["alert"], rule["overridden"]) == (None, None, True)
    [row] = _stored(db_session)
    assert (row.warn, row.alert) == (None, None)


def test_equal_levels_are_allowed(api: TestClient) -> None:
    assert api.put(SBC, json={"warn": "0.02", "alert": "0.02"}).status_code == 200
    assert api.put(CFO, json={"warn": "0.5", "alert": "0.5"}).status_code == 200


@pytest.mark.parametrize(
    ("url", "body"),
    [
        (SBC, {"warn": "0.02", "alert": "0.01"}),  # above: alert < warn
        (CFO, {"warn": "0.5", "alert": "0.9"}),  # below: alert > warn
        (SBC, {"warn": "lots", "alert": "0.02"}),
        (SBC, {"warn": "0.01"}),
        (SBC, {"alert": "0.02"}),
        (SBC, {"warn": "NaN", "alert": "0.02"}),
        (SBC, {"warn": "0.01", "alert": "1E+30"}),  # beyond LEVEL_LIMIT (Gotcha G21)
        (SBC, {"warn": "0.12345678901", "alert": None}),  # more than 10 decimal places
    ],
)
def test_an_invalid_override_is_a_422_and_stores_nothing(
    api: TestClient, db_session: Session, url: str, body: dict[str, object]
) -> None:
    response = api.put(url, json=body)

    assert response.status_code == 422, response.text
    assert _stored(db_session) == []


def test_an_out_of_order_override_says_why(api: TestClient) -> None:
    response = api.put(CFO, json={"warn": "0.5", "alert": "0.9"})

    assert response.status_code == 422
    assert "alert <= warn" in response.text


# --- reset -----------------------------------------------------------------------------------


def test_reset_restores_the_defaults(api: TestClient, db_session: Session) -> None:
    assert api.put(SBC, json={"warn": "0.01", "alert": "0.02"}).status_code == 200

    assert api.delete(SBC).status_code == 204

    rule = _rule(api, "sbc_to_revenue")
    assert (rule["warn"], rule["alert"], rule["overridden"]) == ("0.05", "0.1", False)
    assert _stored(db_session) == []


def test_reset_without_an_override_is_still_a_204(api: TestClient) -> None:
    assert api.delete(SBC).status_code == 204


# --- service ---------------------------------------------------------------------------------


def test_effective_rules_reflect_the_stored_overrides(api: TestClient, db_session: Session) -> None:
    service.set_thresholds(db_session, "cfo_to_net_income", "1", "0.5", NOW)

    rules = {r.code: r for r in service.effective(db_session)}

    assert rules["cfo_to_net_income"].thresholds == Thresholds(Decimal("1"), Decimal("0.5"))
    assert rules["cfo_to_net_income"].default == Thresholds(Decimal("0.8"), Decimal("0"))
    assert rules["sbc_to_revenue"].thresholds == rules["sbc_to_revenue"].default


def test_an_overflowing_level_is_a_422_and_the_list_still_works(
    api: TestClient, db_session: Session
) -> None:
    # Gotcha G21: 1E+400 is a finite Decimal but overflows the SQLite column
    response = api.put(SBC, json={"warn": "0.01", "alert": "1E+400"})

    assert response.status_code == 422, response.text
    assert _stored(db_session) == []
    assert api.get(RULES).status_code == 200


# --- formula levels (FR-ANL-10) --------------------------------------------------------------


def test_a_formula_level_is_stored_as_text(api: TestClient, db_session: Session) -> None:
    response = api.put(SBC, json={"warn": " prev(sbc / revenue) + 1% ", "alert": "0.2"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["warn"], body["warn_formula"]) == (None, "prev(sbc / revenue) + 1%")
    assert (body["alert"], body["alert_formula"]) == ("0.2", None)
    [row] = _stored(db_session)
    assert (row.warn, row.warn_formula) == (None, "prev(sbc / revenue) + 1%")
    assert (row.alert, row.alert_formula) == (Decimal("0.2"), None)
    assert _rule(api, "sbc_to_revenue")["warn_formula"] == "prev(sbc / revenue) + 1%"


def test_a_constant_formula_level_is_stored_as_a_number(
    api: TestClient, db_session: Session
) -> None:
    response = api.put(SBC, json={"warn": "2% + 1%", "alert": None})

    assert response.status_code == 200, response.text
    assert (response.json()["warn"], response.json()["warn_formula"]) == ("0.03", None)
    [row] = _stored(db_session)
    assert (row.warn, row.warn_formula) == (Decimal("0.03"), None)


def test_an_invalid_formula_level_is_a_422_with_its_position(
    api: TestClient, db_session: Session
) -> None:
    response = api.put(SBC, json={"warn": "revenu / 2", "alert": None})

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown name 'revenu' at 0"
    assert _stored(db_session) == []


def test_a_broken_stored_override_formula_keeps_the_list_working(
    api: TestClient, db_session: Session
) -> None:
    db_session.add(
        QoeThreshold(
            rule_code="sbc_to_revenue",
            warn_formula="revenu * 2",
            updated_at=NOW.replace(tzinfo=None),
        )
    )
    db_session.commit()

    response = api.get(RULES)

    assert response.status_code == 200, response.text
    broken = _rule(api, "sbc_to_revenue")
    assert broken["error"] == "Unknown name 'revenu' at 0"
    assert broken["warn"] is None
    assert broken["warn_formula"] == "revenu * 2"
    assert broken["overridden"] is True


def test_service_levels_are_formula_objects_for_a_formula_text(db_session: Session) -> None:
    service.set_thresholds(db_session, "sbc_to_revenue", "cfo / 100", None, NOW)

    rules = {r.code: r for r in service.effective(db_session)}

    assert rules["sbc_to_revenue"].thresholds == Thresholds(
        parse("cfo / 100", formula_names()), None
    )
