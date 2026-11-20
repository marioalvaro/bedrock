"""Archive, restore, deletion impact and the two-step delete (M7c S6, FR-WS-07; docs/erd/
workspace.md "Archive and permanent deletion")."""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock
from bedrock.models.company import Company
from bedrock.models.comps_set import CompsSet
from bedrock.models.filing import Filing
from bedrock.models.forecast_run import ForecastSnapshot
from bedrock.models.guidance import Guidance
from bedrock.models.note import Note
from bedrock.models.raw_fact import RawFact
from bedrock.models.scenario import Scenario
from bedrock.models.thesis_checkpoint import ThesisCheckpoint

ARCHIVED_AT = datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
LATER = datetime(2026, 11, 18, 15, 30, tzinfo=UTC)  # inside the session idle limit


def _tickers(client: TestClient, query: str = "") -> list[str]:
    response = client.get(f"/api/v1/companies{query}")
    assert response.status_code == 200, response.text
    return [c["ticker"] for c in response.json()]


def _count(session: Session, model: type, company_id: int) -> int:
    stmt = select(func.count()).select_from(model).where(model.company_id == company_id)  # type: ignore[attr-defined]
    return session.execute(stmt).scalar_one()


def _at(app: FastAPI, moment: datetime) -> None:
    app.dependency_overrides[get_clock] = lambda: moment


def test_archive_moves_a_company_to_the_archived_list_and_restore_brings_it_back(
    seed_db: Callable[..., None], app: FastAPI, authed_client: TestClient
) -> None:
    seed_db("AAPL", "MSFT")
    _at(app, ARCHIVED_AT)

    assert authed_client.post("/api/v1/companies/AAPL/archive").status_code == 204

    assert _tickers(authed_client) == ["MSFT"]
    archived = authed_client.get("/api/v1/companies?archived=true").json()
    assert [c["ticker"] for c in archived] == ["AAPL"]
    assert archived[0]["archived_at"] == "2026-11-18T14:30:00Z"
    assert _tickers(authed_client, "?archived=false") == ["MSFT"]
    # the page of an archived company still opens
    page = authed_client.get("/api/v1/companies/aapl")
    assert page.status_code == 200 and page.json()["archived_at"] == "2026-11-18T14:30:00Z"

    assert authed_client.post("/api/v1/companies/AAPL/restore").status_code == 204

    assert _tickers(authed_client) == ["AAPL", "MSFT"]
    assert _tickers(authed_client, "?archived=true") == []
    assert authed_client.get("/api/v1/companies/AAPL").json()["archived_at"] is None


def test_archiving_twice_keeps_the_first_time_and_restoring_a_followed_one_is_a_no_op(
    seed_db: Callable[..., None], app: FastAPI, authed_client: TestClient
) -> None:
    seed_db("AAPL")
    assert authed_client.post("/api/v1/companies/AAPL/restore").status_code == 204
    assert _tickers(authed_client) == ["AAPL"]

    _at(app, ARCHIVED_AT)
    authed_client.post("/api/v1/companies/AAPL/archive")
    _at(app, LATER)
    assert authed_client.post("/api/v1/companies/AAPL/archive").status_code == 204

    page = authed_client.get("/api/v1/companies/AAPL").json()
    assert page["archived_at"] == "2026-11-18T14:30:00Z"


def test_a_followed_company_has_no_archived_time(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL")
    [listed] = authed_client.get("/api/v1/companies").json()
    assert listed["archived_at"] is None


def test_unknown_tickers_are_a_404_on_every_new_route(authed_client: TestClient) -> None:
    for method, path in (
        ("post", "/api/v1/companies/ZZZZ/archive"),
        ("post", "/api/v1/companies/ZZZZ/restore"),
        ("get", "/api/v1/companies/ZZZZ/deletion-impact"),
    ):
        assert authed_client.request(method, path).status_code == 404, path


def test_the_new_routes_need_a_session(client: TestClient) -> None:
    for method, path in (
        ("post", "/api/v1/companies/AAPL/archive"),
        ("post", "/api/v1/companies/AAPL/restore"),
        ("get", "/api/v1/companies/AAPL/deletion-impact"),
    ):
        assert client.request(method, path).status_code == 401, path


def test_a_followed_company_cannot_be_deleted(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL")

    response = authed_client.delete("/api/v1/companies/AAPL")

    assert response.status_code == 409
    assert response.json()["detail"] == "Archive AAPL before deleting it permanently."
    assert _tickers(authed_client) == ["AAPL"]


def test_adding_an_archived_ticker_asks_to_restore_it_and_creates_nothing(
    seed_db: Callable[..., None], authed_client: TestClient, db_session: Session
) -> None:
    seed_db("AAPL")
    authed_client.post("/api/v1/companies/AAPL/archive")

    for path, body in (
        ("/api/v1/companies", {"ticker": "aapl"}),
        ("/api/v1/companies/manual", {"ticker": "AAPL", "name": "A", "fiscal_year_end_month": 9}),
    ):
        response = authed_client.post(path, json=body)
        assert response.status_code == 409, path
        assert response.json()["detail"] == "AAPL is archived. Restore it from the archived list."

    assert db_session.execute(select(func.count()).select_from(Company)).scalar_one() == 1


def test_adding_a_followed_ticker_is_still_already_followed(
    seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    seed_db("AAPL")
    response = authed_client.post("/api/v1/companies", json={"ticker": "AAPL"})
    assert response.status_code == 409
    assert response.json()["detail"] == "AAPL is already followed"


def test_deletion_impact_counts_the_rows_of_that_company_only(
    seed_db: Callable[..., None], authed_client: TestClient, db_session: Session
) -> None:
    seed_db("AAPL", "MSFT")
    for ticker in ("AAPL", "MSFT"):
        note = {"body_md": f"{ticker} thesis"}
        assert authed_client.post(f"/api/v1/companies/{ticker}/notes", json=note).status_code == 201
    authed_client.post("/api/v1/companies/AAPL/notes", json={"body_md": "second"})
    checkpoint = {"statement": "gross_margin > 40%"}
    assert (
        authed_client.post("/api/v1/companies/AAPL/checkpoints", json=checkpoint).status_code == 201
    )
    authed_client.get("/api/v1/companies/AAPL/scenarios")  # creates the default scenario
    aapl = db_session.execute(select(Company).where(Company.ticker == "AAPL")).scalar_one()

    response = authed_client.get("/api/v1/companies/aapl/deletion-impact")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "ticker",
        "filings",
        "facts",
        "notes",
        "scenarios",
        "snapshots",
        "guidance",
        "adjustments",
        "checkpoints",
        "comps_sets",
        "imports",
    }
    assert body["ticker"] == "AAPL"
    assert body["filings"] == _count(db_session, Filing, aapl.id) > 0
    assert body["facts"] == _count(db_session, RawFact, aapl.id) > 0
    assert body["notes"] == _count(db_session, Note, aapl.id) == 2
    assert body["checkpoints"] == _count(db_session, ThesisCheckpoint, aapl.id) == 1
    assert body["scenarios"] == _count(db_session, Scenario, aapl.id) == 1
    assert body["snapshots"] == _count(db_session, ForecastSnapshot, aapl.id)
    assert body["guidance"] == _count(db_session, Guidance, aapl.id)
    assert body["comps_sets"] == _count(db_session, CompsSet, aapl.id)
    assert body["adjustments"] == 0
    assert body["imports"] == 0


def test_deletion_impact_of_an_empty_manual_company_is_all_zero(authed_client: TestClient) -> None:
    body = {"ticker": "PRIV", "name": "Private Co", "fiscal_year_end_month": 12}
    assert authed_client.post("/api/v1/companies/manual", json=body).status_code == 201

    impact = authed_client.get("/api/v1/companies/PRIV/deletion-impact").json()

    assert impact == {
        "ticker": "PRIV",
        "filings": 0,
        "facts": 0,
        "notes": 0,
        "scenarios": 0,
        "snapshots": 0,
        "guidance": 0,
        "adjustments": 0,
        "checkpoints": 0,
        "comps_sets": 0,
        "imports": 0,
    }


def test_an_archived_company_is_deleted_with_everything_it_owns(
    seed_db: Callable[..., None], authed_client: TestClient, db_session: Session
) -> None:
    seed_db("AAPL", "MSFT")
    authed_client.post("/api/v1/companies/AAPL/notes", json={"body_md": "gone"})
    authed_client.post("/api/v1/companies/MSFT/notes", json={"body_md": "kept"})
    aapl_id = db_session.execute(select(Company.id).where(Company.ticker == "AAPL")).scalar_one()
    authed_client.post("/api/v1/companies/AAPL/archive")

    assert authed_client.delete("/api/v1/companies/AAPL").status_code == 204

    assert authed_client.get("/api/v1/companies/AAPL").status_code == 404
    assert _tickers(authed_client, "?archived=true") == []
    db_session.expire_all()
    for model in (Filing, RawFact, Note):
        assert _count(db_session, model, aapl_id) == 0, model
    assert [n.body_md for n in db_session.execute(select(Note)).scalars()] == ["kept"]
