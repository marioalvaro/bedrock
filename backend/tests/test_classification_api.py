"""The six classification routes (M7d S3, docs/erd/face-tree.md "Routes"): status, the company's
lines and answers, a run from its confirmation, the decisions and the mode. No key, no feature;
no GET builds a classifier. Every classifier here is a fake."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.classify import pricing, registry
from bedrock.classify.protocol import LineClassifier
from bedrock.core.config import Settings
from bedrock.models.classification_run import ClassificationRun
from bedrock.models.company import Company
from bedrock.repositories import classifications as repo
from bedrock.repositories.numeric import plain
from bedrock.services.classification import ClassificationRunner

from .classification_support import HAIKU, JEV, SONNET, Hungry, answering, open_lines, parse_filings

BASE = "/api/v1/companies/AAPL"


@pytest.fixture
def aapl(db_session: Session, seed_db: Callable[..., None], authed_client: TestClient) -> Company:
    seed_db("AAPL")
    return parse_filings(db_session)


class Factory:
    """Stands in for `registry.get` on `app.state`, and counts how often it is called."""

    def __init__(self, classifier: LineClassifier) -> None:
        self.classifier = classifier
        self.calls: list[str] = []

    def __call__(self, name: str, settings: Settings) -> LineClassifier:
        self.calls.append(name)
        return self.classifier


def use(app: FastAPI, classifier: LineClassifier) -> Factory:
    factory = Factory(classifier)
    app.state.classifier_factory = factory
    return factory


def run(client: TestClient, app: FastAPI, confirm: int, name: str = HAIKU) -> Any:
    response = client.post(
        f"{BASE}/classifications/run", json={"classifier": name, "confirm_lines": confirm}
    )
    app.state.classifications.join(timeout=30)
    return response


# --- the app ---------------------------------------------------------------------------------


def test_the_app_holds_the_registry_and_a_runner(app: FastAPI) -> None:
    assert app.state.classifier_factory is registry.get
    assert isinstance(app.state.classifications, ClassificationRunner)


# --- status ----------------------------------------------------------------------------------


def test_status_without_a_key_lists_every_classifier_as_not_configured(
    authed_client: TestClient,
) -> None:
    body = authed_client.get("/api/v1/classification/status").json()

    assert body == {
        "classifiers": [
            {"name": HAIKU, "configured": False},
            {"name": SONNET, "configured": False},
            {"name": JEV, "configured": False},
            {"name": "openrouter:openai/gpt-6-luna", "configured": False},
            {"name": "openrouter:nvidia/nemotron-3.5-super-vl:free", "configured": False},
        ],
        "daily_tokens": 300_000,
        "monthly_tokens": 3_000_000,
        "used_today": 0,
        "used_month": 0,
        "cost_month_usd": "0",
        "max_lines_per_run": 300,
        "min_confidence": 0.9,
    }


def test_status_with_keys_and_usage(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient, settings: Settings
) -> None:
    app.state.settings = settings.model_copy(update={"anthropic_api_key": "a"})
    now = datetime.now(UTC).replace(tzinfo=None)  # the columns hold naive UTC
    repo.add_run(
        db_session,
        ClassificationRun(
            company_id=aapl.id,
            classifier=HAIKU,
            status="done",
            started_at=now - timedelta(seconds=5),
            lines_asked=1,
            input_tokens=900,
            output_tokens=100,
            cost_usd=Decimal("0.000140"),
        ),
    )
    db_session.commit()

    body = authed_client.get("/api/v1/classification/status").json()

    assert [c["configured"] for c in body["classifiers"]] == [True, True, False, False, False]
    assert (body["used_today"], body["used_month"], body["cost_month_usd"]) == (
        1000,
        1000,
        "0.00014",
    )


# --- the company's lines and answers ---------------------------------------------------------


def test_the_classifications_of_a_company_are_its_open_lines(
    db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    lines = open_lines(db_session, aapl)

    body = authed_client.get(f"{BASE}/classifications").json()

    assert {k: body[k] for k in ("mode", "source", "run", "to_ask", "estimate")} == {
        "mode": "off",
        "source": None,
        "run": None,
        "to_ask": None,
        "estimate": None,
    }
    assert len(body["lines"]) == len(lines)
    first, asked = body["lines"][0], lines[0]
    assert first == {
        "statement": asked.question.statement,
        "taxonomy": asked.question.taxonomy,
        "concept": asked.question.concept,
        "label": asked.question.label,
        "latest_value": str(asked.question.value),
        "latest_period_end": asked.question.period_end.isoformat(),
        "block": {"code": asked.line.block_code, "label": asked.question.block_label},
        "candidates": [{"code": c.code, "label": c.label} for c in asked.question.candidates],
        "effective": None,
        "answers": [],
    }


def test_a_line_without_a_block_has_a_null_block(
    db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    lines = open_lines(db_session, aapl)
    body = authed_client.get(f"{BASE}/classifications").json()

    for shown, asked in zip(body["lines"], lines, strict=True):
        assert (shown["block"] is None) == (asked.line.block_code is None)


def test_naming_a_classifier_adds_what_a_run_would_ask_and_its_estimate(
    db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    lines = open_lines(db_session, aapl)
    estimate = registry.estimator(HAIKU).estimate([ln.question for ln in lines])

    body = authed_client.get(f"{BASE}/classifications", params={"classifier": HAIKU}).json()

    assert body["to_ask"] == len(lines)
    assert body["estimate"] == {
        "input_tokens": estimate.input_tokens,
        "output_tokens": estimate.output_tokens,
        "cost_usd": str(plain(pricing.cost(HAIKU, estimate).quantize(Decimal("0.000001")))),
    }


def test_no_get_builds_a_classifier(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    factory = use(app, answering(open_lines(db_session, aapl)))

    assert authed_client.get("/api/v1/classification/status").status_code == 200
    assert authed_client.get(f"{BASE}/classifications").status_code == 200
    for name in registry.NAMES:
        response = authed_client.get(f"{BASE}/classifications", params={"classifier": name})
        assert response.status_code == 200
    assert authed_client.get(BASE).status_code == 200
    assert authed_client.get("/api/v1/companies").status_code == 200

    assert factory.calls == []


def test_an_unknown_classifier_name_is_409_on_the_get_too(
    aapl: Company, authed_client: TestClient
) -> None:
    response = authed_client.get(f"{BASE}/classifications", params={"classifier": "gpt"})

    assert response.status_code == 409
    assert response.json()["code"] == "classifier_unavailable"


# --- a run -----------------------------------------------------------------------------------


def test_without_a_key_a_run_is_409_classifier_unavailable(
    db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    # the real registry: no key is set, so nothing can be started
    response = authed_client.post(
        f"{BASE}/classifications/run", json={"classifier": HAIKU, "confirm_lines": 1}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "classifier_unavailable"
    assert HAIKU in response.json()["detail"]
    assert db_session.query(ClassificationRun).count() == 0


def test_a_confirmed_run_is_202_and_fills_the_proposals(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    lines = open_lines(db_session, aapl)
    factory = use(app, answering(lines, skip=1))

    response = run(authed_client, app, len(lines))

    assert response.status_code == 202
    started = response.json()
    assert (started["classifier"], started["status"], started["lines_asked"]) == (
        HAIKU,
        "running",
        len(lines),
    )
    assert factory.calls == [HAIKU]
    body = authed_client.get(f"{BASE}/classifications", params={"classifier": HAIKU}).json()
    assert body["run"]["id"] == started["id"]
    assert (body["run"]["status"], body["run"]["error"]) == (
        "done",
        f"{len(lines) - 1} of {len(lines)} lines got a usable answer. "
        "The others can be asked again.",
    )
    assert (body["run"]["lines_answered"], body["run"]["input_tokens"]) == (
        len(lines) - 1,
        100 * len(lines),
    )
    assert body["run"]["output_tokens"] == 10 * len(lines)
    assert Decimal(body["run"]["cost_usd"]) > 0
    assert body["run"]["finished_at"] is not None and body["run"]["started_at"].endswith("Z")
    assert body["to_ask"] == 1  # the failed line is asked again
    assert body["lines"][0]["answers"] == []
    (answer,) = body["lines"][1]["answers"]
    assert answer == {
        "id": answer["id"],
        "classifier": HAIKU,
        "codes": [lines[1].question.candidates[0].code],
        "confidence": "0.95",
        "status": "proposed",
    }


def test_a_second_click_after_a_finished_run_is_409_nothing_to_classify(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    lines = open_lines(db_session, aapl)
    factory = use(app, answering(lines))
    assert run(authed_client, app, len(lines)).status_code == 202
    asked = len(factory.classifier.calls)  # type: ignore[attr-defined]

    again = run(authed_client, app, 0)

    assert (again.status_code, again.json()["code"]) == (409, "nothing_to_classify")
    assert len(factory.classifier.calls) == asked  # type: ignore[attr-defined]
    body = authed_client.get(f"{BASE}/classifications", params={"classifier": HAIKU}).json()
    assert body["to_ask"] == 0


def test_a_number_other_than_the_one_confirmed_is_409_stale_estimate(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    lines = open_lines(db_session, aapl)
    factory = use(app, answering(lines))

    response = run(authed_client, app, len(lines) + 1)

    assert (response.status_code, response.json()["code"]) == (409, "stale_estimate")
    assert str(len(lines)) in response.json()["detail"]
    assert factory.classifier.calls == []  # type: ignore[attr-defined]


def test_an_estimate_over_the_budget_is_409_budget_exceeded(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    use(app, answering(lines))
    app.state.settings = settings.model_copy(update={"classify_daily_tokens": 10})

    response = run(authed_client, app, len(lines))

    assert (response.status_code, response.json()["code"]) == (409, "budget_exceeded")
    assert "daily" in response.json()["detail"]


def test_a_run_while_one_runs_is_409_classification_running(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient
) -> None:
    lines = open_lines(db_session, aapl)
    use(app, answering(lines))
    repo.add_run(
        db_session,
        ClassificationRun(
            company_id=aapl.id,
            classifier=JEV,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            lines_asked=1,
        ),
    )
    db_session.commit()

    response = run(authed_client, app, len(lines))

    assert (response.status_code, response.json()["code"]) == (409, "classification_running")
    shown = authed_client.get(f"{BASE}/classifications").json()["run"]
    assert (shown["classifier"], shown["status"]) == (JEV, "running")


def test_a_run_stopped_by_the_budget_shows_its_reason(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    use(app, Hungry(answering(lines).answers, name=HAIKU, batch_size=5))
    app.state.settings = settings.model_copy(
        update={"classify_daily_tokens": 110 * len(lines) + 100}
    )

    assert run(authed_client, app, len(lines)).status_code == 202

    shown = authed_client.get(f"{BASE}/classifications").json()["run"]
    assert shown["status"] == "stopped" and "daily budget" in shown["error"]
    assert shown["lines_answered"] == 5


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"classifier": HAIKU},
        {"classifier": HAIKU, "confirm_lines": -1},
        {"classifier": HAIKU, "confirm_lines": "many"},
        {"classifier": "", "confirm_lines": 1},
    ],
)
def test_a_run_needs_a_classifier_and_a_confirmed_number(
    aapl: Company, authed_client: TestClient, body: dict[str, Any]
) -> None:
    assert authed_client.post(f"{BASE}/classifications/run", json=body).status_code == 422


# --- decisions -------------------------------------------------------------------------------


@pytest.fixture
def proposed(
    app: FastAPI, db_session: Session, aapl: Company, authed_client: TestClient
) -> list[dict[str, Any]]:
    """The lines of AAPL after a Haiku run that answered every line."""
    lines = open_lines(db_session, aapl)
    use(app, answering(lines))
    assert run(authed_client, app, len(lines)).status_code == 202
    body = authed_client.get(f"{BASE}/classifications").json()
    return body["lines"]  # type: ignore[no-any-return]


def test_a_decision_sets_the_status_and_returns_the_row(
    authed_client: TestClient, proposed: list[dict[str, Any]]
) -> None:
    answer = proposed[0]["answers"][0]

    response = authed_client.put(
        f"{BASE}/classifications/{answer['id']}", json={"status": "accepted"}
    )

    assert response.status_code == 200
    assert response.json() == {**answer, "status": "accepted"}
    shown = authed_client.get(f"{BASE}/classifications").json()["lines"][0]
    assert shown["answers"][0]["status"] == "accepted"
    assert shown["effective"] is None  # the mode is still off
    for status in ("rejected", "proposed"):
        again = authed_client.put(f"{BASE}/classifications/{answer['id']}", json={"status": status})
        assert again.json()["status"] == status


def test_a_decision_on_an_unknown_row_is_404_and_an_unknown_status_422(
    authed_client: TestClient, proposed: list[dict[str, Any]]
) -> None:
    answer = proposed[0]["answers"][0]

    missing = authed_client.put(f"{BASE}/classifications/999999", json={"status": "accepted"})
    invalid = authed_client.put(f"{BASE}/classifications/{answer['id']}", json={"status": "maybe"})

    assert (missing.status_code, invalid.status_code) == (404, 422)


def test_the_users_own_answer_is_stored_accepted(
    authed_client: TestClient, proposed: list[dict[str, Any]]
) -> None:
    line = proposed[0]
    place = {k: line[k] for k in ("statement", "taxonomy", "concept")}
    second = line["candidates"][1]["code"]

    response = authed_client.put(f"{BASE}/classifications", json={**place, "codes": [second]})

    assert response.status_code == 200
    mine = response.json()
    assert {k: mine[k] for k in ("classifier", "codes", "confidence", "status")} == {
        "classifier": "user",
        "codes": [second],
        "confidence": "1",
        "status": "accepted",
    }
    other = authed_client.put(f"{BASE}/classifications", json={**place, "codes": []})
    assert (other.json()["id"], other.json()["codes"]) == (mine["id"], [])
    answers = authed_client.get(f"{BASE}/classifications").json()["lines"][0]["answers"]
    assert [(a["classifier"], a["status"]) for a in answers] == [
        (HAIKU, "proposed"),
        ("user", "accepted"),
    ]


def test_an_answer_that_is_not_a_candidate_or_not_an_open_line_is_422(
    authed_client: TestClient, proposed: list[dict[str, Any]]
) -> None:
    place = {k: proposed[0][k] for k in ("statement", "taxonomy", "concept")}

    wrong_code = authed_client.put(
        f"{BASE}/classifications", json={**place, "codes": ["total_assets"]}
    )
    wrong_line = authed_client.put(
        f"{BASE}/classifications",
        json={"statement": "BS", "taxonomy": "us-gaap", "concept": "Assets", "codes": []},
    )
    wrong_statement = authed_client.put(
        f"{BASE}/classifications", json={**place, "statement": "EQ", "codes": []}
    )

    assert (wrong_code.status_code, wrong_line.status_code, wrong_statement.status_code) == (
        422,
        422,
        422,
    )
    assert "total_assets" in wrong_code.json()["detail"]


# --- the mode --------------------------------------------------------------------------------


def test_a_company_starts_with_the_layer_off(aapl: Company, authed_client: TestClient) -> None:
    company = authed_client.get(BASE).json()
    (listed,) = authed_client.get("/api/v1/companies").json()

    for body in (company, listed):
        assert (body["classification_mode"], body["classification_source"]) == ("off", None)


def test_the_mode_is_set_per_company_and_puts_answers_in_force(
    authed_client: TestClient, proposed: list[dict[str, Any]]
) -> None:
    answer = proposed[0]["answers"][0]
    authed_client.put(f"{BASE}/classifications/{answer['id']}", json={"status": "accepted"})

    accepted = authed_client.put(
        f"{BASE}/classification-mode", json={"mode": "accepted", "source": None}
    )

    assert accepted.status_code == 200
    assert (accepted.json()["ticker"], accepted.json()["classification_mode"]) == (
        "AAPL",
        "accepted",
    )
    lines = authed_client.get(f"{BASE}/classifications").json()["lines"]
    assert [ln["effective"] for ln in lines[:2]] == [answer["codes"], None]

    everything = authed_client.put(
        f"{BASE}/classification-mode", json={"mode": "all", "source": HAIKU}
    )
    assert everything.json()["classification_source"] == HAIKU
    body = authed_client.get(f"{BASE}/classifications").json()
    assert (body["mode"], body["source"]) == ("all", HAIKU)
    assert all(ln["effective"] is not None for ln in body["lines"])
    assert len(body["lines"]) == len(lines)  # the open lines stay listed under any mode
    assert authed_client.get(BASE).json()["classification_mode"] == "all"


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "all", "source": None},
        {"mode": "all", "source": "gpt"},
        {"mode": "sometimes", "source": None},
        {"source": HAIKU},
    ],
)
def test_a_mode_that_cannot_be_used_is_422(
    aapl: Company, authed_client: TestClient, body: dict[str, Any]
) -> None:
    assert authed_client.put(f"{BASE}/classification-mode", json=body).status_code == 422
    assert authed_client.get(BASE).json()["classification_mode"] == "off"


def test_the_decisions_are_in_the_audit_trail(
    authed_client: TestClient, proposed: list[dict[str, Any]]
) -> None:
    answer = proposed[0]["answers"][0]
    authed_client.put(f"{BASE}/classifications/{answer['id']}", json={"status": "accepted"})
    authed_client.put(f"{BASE}/classification-mode", json={"mode": "accepted", "source": None})

    rows = authed_client.get(f"{BASE}/audit").json()["rows"]
    by_line = authed_client.get(f"{BASE}/audit", params={"entity": "line_classification"})

    assert {(r["entity"], r["action"], r["field"]) for r in rows} == {
        ("line_classification", "edit", "status"),
        ("company", "mode", "mode"),
    }
    assert [r["new_value"] for r in by_line.json()["rows"]] == ["accepted"]


# --- every route ---------------------------------------------------------------------------


ROUTES = [
    ("GET", "/api/v1/classification/status", None),
    ("GET", "/api/v1/companies/ZZZZ/classifications", None),
    (
        "POST",
        "/api/v1/companies/ZZZZ/classifications/run",
        {"classifier": HAIKU, "confirm_lines": 1},
    ),
    ("PUT", "/api/v1/companies/ZZZZ/classifications/1", {"status": "accepted"}),
    (
        "PUT",
        "/api/v1/companies/ZZZZ/classifications",
        {"statement": "BS", "taxonomy": "us-gaap", "concept": "Assets", "codes": []},
    ),
    ("PUT", "/api/v1/companies/ZZZZ/classification-mode", {"mode": "off", "source": None}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_needs_a_session(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), ROUTES[1:])
def test_a_company_that_is_not_followed_is_404(
    app: FastAPI, authed_client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    use(app, answering([]))

    assert authed_client.request(method, path, json=body).status_code == 404
