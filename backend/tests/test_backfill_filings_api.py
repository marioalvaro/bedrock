"""`POST /companies/{ticker}/backfill-filings` and the filing progress on `CompanyOut` (M7b S6,
docs/erd/data-coverage.md "Flow")."""

import threading
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bedrock.ingest.protocol import CompanyRef
from bedrock.ingest.sources import Sources
from bedrock.models.filing import Filing
from bedrock.services.filings import BackfillRunner

from .fakes import FakeEdgar, FakeFilings, FakePrices

FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")


class BlockingFilings(FakeFilings):
    """Holds every fetch until `release` is set, so a backfill stays running."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def fetch(self, company: CompanyRef, accession_no: str) -> dict[str, bytes]:
        self.started.set()
        assert self.release.wait(timeout=10)
        return super().fetch(company, accession_no)


def _use(app: FastAPI, filings: FakeFilings) -> None:
    app.state.sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=filings)


def _four_forms(session: Session) -> int:
    stmt = select(func.count()).select_from(Filing).where(Filing.form.in_(FORMS))
    return session.execute(stmt).scalar_one()


def test_a_company_shows_how_many_of_its_filings_are_parsed(
    app: FastAPI,
    db_session: Session,
    seed_db: Callable[..., None],
    authed_client: TestClient,
) -> None:
    seed_db("AAPL")

    body = authed_client.get("/api/v1/companies/AAPL").json()

    assert (body["filings_parsed"], body["filings_total"]) == (0, _four_forms(db_session))
    listed = authed_client.get("/api/v1/companies").json()
    assert (listed[0]["filings_parsed"], listed[0]["filings_total"]) == (0, body["filings_total"])


def test_backfill_starts_in_the_background_and_parses_the_filings(
    app: FastAPI,
    db_session: Session,
    seed_db: Callable[..., None],
    authed_client: TestClient,
) -> None:
    seed_db("AAPL")
    _use(app, FakeFilings())

    response = authed_client.post("/api/v1/companies/aapl/backfill-filings")

    assert response.status_code == 202
    assert response.json()["ticker"] == "AAPL"
    app.state.backfills.join("AAPL", timeout=30)
    body = authed_client.get("/api/v1/companies/AAPL").json()
    assert body["filings_parsed"] == 4  # the four recorded AAPL filings (M7b S7)
    assert body["filings_total"] == _four_forms(db_session)


def test_a_second_backfill_while_one_runs_is_409_and_another_company_is_not_blocked(
    app: FastAPI,
    db_session: Session,
    seed_db: Callable[..., None],
    authed_client: TestClient,
) -> None:
    seed_db("AAPL", "MSFT")
    filings = BlockingFilings()
    _use(app, filings)

    assert authed_client.post("/api/v1/companies/AAPL/backfill-filings").status_code == 202
    assert filings.started.wait(timeout=10)
    try:
        again = authed_client.post("/api/v1/companies/AAPL/backfill-filings")
        other = authed_client.post("/api/v1/companies/MSFT/backfill-filings")
    finally:
        filings.release.set()
        app.state.backfills.join("AAPL", timeout=60)
        app.state.backfills.join("MSFT", timeout=60)

    assert again.status_code == 409
    assert "AAPL" in again.json()["detail"]
    assert other.status_code == 202
    # Once the first run is over, a new one may start.
    assert authed_client.post("/api/v1/companies/AAPL/backfill-filings").status_code == 202
    app.state.backfills.join("AAPL", timeout=60)


def test_backfill_of_a_company_that_is_not_followed_is_404(authed_client: TestClient) -> None:
    response = authed_client.post("/api/v1/companies/ZZZZ/backfill-filings")

    assert response.status_code == 404


def test_backfill_needs_a_session(client: TestClient) -> None:
    assert client.post("/api/v1/companies/AAPL/backfill-filings").status_code == 401


def test_a_run_that_cannot_start_does_not_block_the_next(
    db_session: Session, seed_db: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_db("AAPL")
    runner = BackfillRunner()
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=FakeFilings())
    factory = sessionmaker_for(db_session)
    original = threading.Thread.start

    def refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", refuse)
    with pytest.raises(RuntimeError):
        runner.start(db_session, factory, sources, "AAPL")
    monkeypatch.setattr(threading.Thread, "start", original)

    runner.start(db_session, factory, sources, "AAPL")
    runner.join("AAPL", timeout=60)


def sessionmaker_for(session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=session.get_bind())
