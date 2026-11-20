"""The snapshot taken before a new 10-K or 10-Q is stored (FR-ACC-05; docs/erd/accountability.md
"Automatic snapshots"), on the recorded fixtures with the newest filing withheld."""

import copy
import logging
from collections.abc import Callable, Generator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.backtest.snapshot import incoming_reports
from bedrock.ingest.parse import FilingRecord
from bedrock.ingest.protocol import CompanyRef, EdgarPayload
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.models.forecast_run import ForecastSnapshot
from bedrock.models.scenario import Scenario
from bedrock.repositories import runs as runs_repo
from bedrock.services import snapshots as snapshots_service
from bedrock.services.refresh import refresh_company
from bedrock.services.snapshots import create_snapshot, snapshot_before

from .accountability_data import withhold_filings
from .fakes import FakeEdgar, FakePrices
from .seed import follow
from .valuation_api import main_id, scenarios_url

CUTOFF = date(2026, 5, 1)  # AAPL's newest recorded filing, the Q3 FY26 10-Q, is filed after it
Q3_FY26 = FilingRecord(
    "0000320193-26-000020", "10-Q", date(2026, 7, 31), 2026, "Q3", date(2026, 6, 27)
)
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def _filing(accession: str, form: str, filed: date) -> FilingRecord:
    return FilingRecord(accession, form, filed, 2026, "Q3", filed)


# --- incoming_reports (pure) -------------------------------------------------------------------


def test_incoming_reports_are_the_unstored_10ks_and_10qs_oldest_first() -> None:
    parsed = [
        _filing("c", "10-K", date(2026, 10, 30)),
        _filing("old", "10-Q", date(2026, 5, 1)),
        _filing("a", "10-Q", date(2026, 7, 31)),
        _filing("b", "8-K", date(2026, 8, 1)),
        _filing("d", "10-K/A", date(2026, 11, 2)),
        _filing("e", "10-Q/A", date(2026, 11, 3)),
    ]

    incoming = incoming_reports(parsed, {"old", "zzz"})

    assert [f.accession_no for f in incoming] == ["a", "c"]


def test_incoming_reports_on_the_same_day_are_ordered_by_accession() -> None:
    day = date(2026, 7, 31)
    parsed = [_filing("b", "10-Q", day), _filing("a", "10-K", day)]

    assert [f.accession_no for f in incoming_reports(parsed, {"x"})] == ["a", "b"]


def test_nothing_new_is_no_incoming_report() -> None:
    parsed = [_filing("a", "10-Q", date(2026, 7, 31))]

    assert incoming_reports(parsed, {"a"}) == []
    assert incoming_reports([], {"a"}) == []


def test_a_company_with_no_stored_filing_has_no_incoming_report() -> None:
    """The first load: there is no forecast to freeze."""
    parsed = [_filing("a", "10-Q", date(2026, 7, 31))]

    assert incoming_reports(parsed, set()) == []


# --- snapshot_before (service) -----------------------------------------------------------------


@pytest.fixture
def session(
    seed_db: Callable[..., None], app: FastAPI, authed_client: TestClient
) -> Generator[Session, None, None]:
    seed_db("AAPL")
    with app.state.session_factory() as opened:
        withhold_filings(opened, CUTOFF)
        yield opened


def _aapl(session: Session) -> Company:
    return session.scalars(select(Company).where(Company.ticker == "AAPL")).one()


def _snapshots(session: Session) -> list[ForecastSnapshot]:
    return list(session.scalars(select(ForecastSnapshot).order_by(ForecastSnapshot.id)))


def test_snapshot_before_freezes_the_default_scenario_as_auto(session: Session) -> None:
    company = _aapl(session)

    view = snapshot_before(session, company, [Q3_FY26], NOW)

    assert view is not None
    assert view.origin == "auto"
    assert view.scenario_name == "Main"
    assert view.note == "Before the 10-Q filed 2026-07-31"
    assert view.data_as_of == CUTOFF
    (stored,) = _snapshots(session)
    assert stored.id == view.id
    assert stored.origin == "auto"
    assert stored.trigger_accession == Q3_FY26.accession_no


def test_a_company_with_no_scenario_gets_main_and_its_snapshot(session: Session) -> None:
    company = _aapl(session)
    assert session.scalar(select(func.count()).select_from(Scenario)) == 0

    view = snapshot_before(session, company, [Q3_FY26], NOW)

    (main,) = session.scalars(select(Scenario).where(Scenario.company_id == company.id))
    assert main.name == "Main" and main.is_default
    assert view is not None and view.scenario_id == main.id


def test_several_reports_at_once_are_named_by_the_newest(session: Session) -> None:
    q2 = FilingRecord("0000320193-26-000013", "10-Q", date(2026, 5, 1), 2026, "Q2", CUTOFF)

    view = snapshot_before(session, _aapl(session), [q2, Q3_FY26], NOW)

    assert view is not None
    assert view.note == "Before 2 filings, the newest the 10-Q filed 2026-07-31"
    assert _snapshots(session)[0].trigger_accession == Q3_FY26.accession_no


def test_a_repeated_trigger_takes_no_second_snapshot(session: Session) -> None:
    company = _aapl(session)
    assert snapshot_before(session, company, [Q3_FY26], NOW) is not None

    assert snapshot_before(session, company, [Q3_FY26], NOW) is None
    assert len(_snapshots(session)) == 1


def test_nothing_incoming_takes_no_snapshot(session: Session) -> None:
    assert snapshot_before(session, _aapl(session), [], NOW) is None
    assert _snapshots(session) == []


def test_has_trigger_is_per_company_and_accession(session: Session) -> None:
    company = _aapl(session)
    snapshot_before(session, company, [Q3_FY26], NOW)

    assert runs_repo.has_trigger(session, company.id, Q3_FY26.accession_no)
    assert not runs_repo.has_trigger(session, company.id, "0000320193-26-000013")
    assert not runs_repo.has_trigger(session, company.id + 1, Q3_FY26.accession_no)


def test_an_automatic_snapshot_records_the_classification_mode(session: Session) -> None:
    company = _aapl(session)
    company.classification_mode = "accepted"
    session.commit()

    view = snapshot_before(session, company, [Q3_FY26], NOW)

    assert view is not None and view.classification_mode == "accepted"
    assert _snapshots(session)[0].classification_mode == "accepted"


def test_a_manual_snapshot_reads_manual_with_no_trigger(session: Session) -> None:
    company = _aapl(session)
    snapshot_before(session, company, [Q3_FY26], NOW)  # creates Main
    main = session.scalars(select(Scenario).where(Scenario.company_id == company.id)).one()

    view = create_snapshot(session, company, main.id, None, NOW)

    assert view.origin == "manual"
    stored = session.get(ForecastSnapshot, view.id)
    assert stored is not None and stored.trigger_accession is None


# --- refresh_company ---------------------------------------------------------------------------


class RelabelledEdgar(FakeEdgar):
    """The recorded companyfacts with one filing's form changed (an 8-K or an amendment)."""

    def __init__(self, accession_no: str, form: str) -> None:
        super().__init__()
        self.accession_no, self.form = accession_no, form

    def fetch(self, company: CompanyRef, since: date | None) -> EdgarPayload:
        payload = super().fetch(company, since)
        doc: dict[str, Any] = copy.deepcopy(payload.companyfacts)
        for concepts in doc["facts"].values():
            for body in concepts.values():
                for rows in body["units"].values():
                    for row in rows:
                        if row.get("accn") == self.accession_no:
                            row["form"] = self.form
        return EdgarPayload(companyfacts=doc, fetched_at=payload.fetched_at)


def _sources(edgar: FakeEdgar | None = None) -> Sources:
    return Sources(edgar=edgar or FakeEdgar(), prices=FakePrices())


def _stored(session: Session, accession_no: str) -> bool:
    stmt = select(Filing.id).where(Filing.accession_no == accession_no)
    return session.execute(stmt).first() is not None


def test_a_refresh_bringing_a_new_10q_snapshots_before_storing_it(session: Session) -> None:
    result = refresh_company(session, _sources(), "AAPL", NOW)

    (snapshot,) = _snapshots(session)
    assert result.snapshot_id == snapshot.id
    assert result.new_filings == 1 and result.warnings == []
    assert snapshot.origin == "auto"
    assert snapshot.trigger_accession == Q3_FY26.accession_no
    assert snapshot.data_as_of is not None and snapshot.data_as_of < Q3_FY26.filed_at
    assert _stored(session, Q3_FY26.accession_no)


def test_the_automatic_snapshot_is_scored_against_the_new_actual(session: Session) -> None:
    result = refresh_company(session, _sources(), "AAPL", NOW)
    assert result.snapshot_id is not None

    view = snapshots_service.detail(session, _aapl(session), result.snapshot_id)

    base = next(c for c in view.cases if c.case == "base")
    revenue = next(line for line in base.lines if line.code == "revenue")
    q3 = next(c for c in revenue.cells if (c.fiscal_year, c.fiscal_period) == (2026, "Q3"))
    assert q3.horizon == 1
    assert q3.actual is not None and q3.actual > 0
    assert q3.pct_error == (q3.forecast - q3.actual) / abs(q3.actual)


def test_a_refresh_with_nothing_new_takes_no_snapshot(session: Session) -> None:
    refresh_company(session, _sources(), "AAPL", NOW)

    again = refresh_company(session, _sources(), "AAPL", NOW)

    assert again.snapshot_id is None
    assert len(_snapshots(session)) == 1


@pytest.mark.parametrize("form", ["8-K", "10-Q/A"])
def test_a_refresh_bringing_only_an_8k_or_an_amendment_takes_no_snapshot(
    session: Session, form: str
) -> None:
    edgar = RelabelledEdgar(Q3_FY26.accession_no, form)

    result = refresh_company(session, _sources(edgar), "AAPL", NOW)

    assert result.snapshot_id is None and result.new_filings == 1
    assert _snapshots(session) == []


def test_the_first_load_takes_no_snapshot(db_session: Session) -> None:
    follow(db_session, FakeEdgar(), "AAPL")

    result = refresh_company(db_session, _sources(), "AAPL", NOW)

    assert result.snapshot_id is None and result.new_filings > 0
    assert _snapshots(db_session) == []


def test_a_forecast_that_cannot_run_is_a_warning_and_the_filing_is_still_stored(
    session: Session, authed_client: TestClient
) -> None:
    main = main_id(authed_client)
    switch = {"revenue_method": "segments", "segment_dimension": "business"}
    assert authed_client.put(f"{scenarios_url('AAPL')}/{main}", json=switch).status_code == 200

    result = refresh_company(session, _sources(), "AAPL", NOW)

    assert result.snapshot_id is None
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("forecast not snapshotted: ")
    assert "segments have no" in result.warnings[0]
    assert result.new_filings == 1 and _stored(session, Q3_FY26.accession_no)
    assert _snapshots(session) == []


def test_any_other_snapshot_failure_is_logged_and_the_refresh_goes_on(
    session: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An unexpected error (a bug, a locked database) stands in for one the data cannot cause."""

    def broken(*_: object) -> None:
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(snapshots_service, "snapshot_before", broken)

    with caplog.at_level(logging.ERROR):
        result = refresh_company(session, _sources(), "AAPL", NOW)

    assert result.warnings == ["forecast not snapshotted: disk I/O error"]
    assert result.snapshot_id is None
    assert _stored(session, Q3_FY26.accession_no)
    assert any(r.exc_info for r in caplog.records)


def test_a_refresh_retried_after_the_snapshot_takes_no_second_one(session: Session) -> None:
    """A refresh that failed after its snapshot committed leaves the filing unstored."""
    company = _aapl(session)
    snapshot_before(session, company, [Q3_FY26], NOW)

    result = refresh_company(session, _sources(), "AAPL", NOW)

    assert result.snapshot_id is None and result.new_filings == 1
    assert len(_snapshots(session)) == 1
