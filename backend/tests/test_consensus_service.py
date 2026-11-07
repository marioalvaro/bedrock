"""Consensus guidance end to end: the yfinance frames, the stored rows, their placement on the
company's reported revenue, and `GET /companies/{ticker}/guidance/consensus`."""

import dataclasses
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.analysis.consensus import ConsensusRow
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources.yfinance import YFinanceConsensus
from bedrock.models.company import Company
from bedrock.models.guidance import Guidance
from bedrock.services import consensus as service
from bedrock.services import guidance as guidance_service
from bedrock.services.consensus import HISTORY_NOTE
from bedrock.services.statements import statement_tables

from .fakes import FakeConsensus

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures" / "consensus"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        if symbol != "AAPL":
            raise RuntimeError("unknown")

    @property
    def revenue_estimate(self) -> pd.DataFrame:
        return pd.read_csv(FIXTURES / "AAPL_revenue_estimate.csv", index_col="period")

    @property
    def earnings_estimate(self) -> pd.DataFrame:
        return pd.read_csv(FIXTURES / "AAPL_earnings_estimate.csv", index_col="period")

    @property
    def earnings_history(self) -> pd.DataFrame:
        frame = pd.read_csv(FIXTURES / "AAPL_earnings_history.csv", index_col="quarter")
        frame.index = pd.to_datetime(frame.index)  # yfinance gives Timestamps
        return frame


def test_the_yfinance_consensus_reads_both_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    rows = YFinanceConsensus().fetch(CompanyRef("AAPL", None))
    history = YFinanceConsensus().history(CompanyRef("AAPL", None))

    assert len(rows) == 8
    assert [h.quarter_end for h in history][0] == date(2025, 9, 30)
    with pytest.raises(SourceUnavailable):
        YFinanceConsensus().fetch(CompanyRef("NOPE", None))
    with pytest.raises(SourceUnavailable):
        YFinanceConsensus().history(CompanyRef("NOPE", None))


def _aapl(session: Session) -> Company:
    return session.execute(select(Company).where(Company.ticker == "AAPL")).scalar_one()


def test_stored_consensus_is_placed_on_the_reported_revenue(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    # The recorded AAPL filings end at FY25: the 0y row (year-ago FY25) is FY26.
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    estimates = service.consensus(db_session, company)

    fy26 = next(
        e
        for e in estimates
        if (e.metric, e.fiscal_year, e.fiscal_period) == ("revenue", 2026, "FY")
    )
    assert (fy26.low, fy26.high, fy26.analysts) == (D("476002000000"), D("484000000000"), 37)
    assert any(e.metric == "eps_diluted" and e.fiscal_year == 2027 for e in estimates)


def test_a_refresh_replaces_the_company_s_rows(seed_db: Any, db_session: Session) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    assert len(service.consensus(db_session, company)) == len(
        {(e.metric, e.fiscal_year, e.fiscal_period) for e in service.consensus(db_session, company)}
    )


def test_without_stored_consensus_there_are_no_estimates(seed_db: Any, db_session: Session) -> None:
    seed_db("AAPL")
    assert service.consensus(db_session, _aapl(db_session)) == []


def test_the_route_lists_the_placed_estimates(
    seed_db: Any, db_session: Session, authed_client: TestClient
) -> None:
    seed_db("AAPL")
    service.refresh_consensus(db_session, FakeConsensus(), _aapl(db_session), NOW)

    response = authed_client.get("/api/v1/companies/AAPL/guidance/consensus")

    assert response.status_code == 200
    body = response.json()
    fy26 = next(
        e
        for e in body
        if e["metric"] == "revenue" and e["fiscal_period"] == "FY" and e["fiscal_year"] == 2026
    )
    assert fy26 == {
        "metric": "revenue",
        "fiscal_year": 2026,
        "fiscal_period": "FY",
        "low": "476002000000",
        "avg": "477692148210",
        "high": "484000000000",
        "analysts": 37,
        "as_of": "2026-11-07",
    }


# --- consensus guidance: the refresh logs each placed estimate (erd/analysis.md) ---------------

NOTE = "Analyst consensus (Yahoo, 37 analysts, as of 2026-11-07)"


def _recorded() -> list[ConsensusRow]:
    return FakeConsensus().fetch(CompanyRef("AAPL", None))


def _consensus_entries(session: Session, company: Company) -> list[Guidance]:
    return [
        e.stored
        for e in guidance_service.guidance_log(session, company).entries
        if e.stored.source == "consensus"
    ]


def _forward(session: Session, company: Company) -> list[Guidance]:
    """The consensus entries logged from the estimates, without the backfilled past quarters."""
    return [g for g in _consensus_entries(session, company) if g.source_note != HISTORY_NOTE]


def _keys(entries: list[Guidance]) -> set[tuple[str, int, str, str]]:
    return {(g.metric, g.fiscal_year, g.fiscal_period, g.basis) for g in entries}


def _with_range(low: str, high: str) -> list[ConsensusRow]:
    """The recorded rows with 0y revenue moved to [low, high]."""
    return [
        dataclasses.replace(r, low=D(low), high=D(high))
        if (r.period, r.metric) == ("0y", "revenue")
        else r
        for r in _recorded()
    ]


def test_a_refresh_logs_every_placed_estimate_as_consensus_guidance(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)

    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    entries = _forward(db_session, company)
    # EPS is judged on the normalized basis (Yahoo's EPS is the street's adjusted figure). The
    # recorded filings reach FY26 Q1, so the quarters place too.
    assert _keys(entries) == {
        (metric, year, period, basis)
        for metric, basis in (("revenue", "reported"), ("eps_diluted", "normalized"))
        for year, period in ((2026, "FY"), (2027, "FY"), (2027, "Q1"), (2027, "Q2"))
    }
    fy26 = next(g for g in entries if (g.metric, g.fiscal_year) == ("revenue", 2026))
    assert (fy26.low, fy26.high, fy26.direction) == (
        D("476002000000"),
        D("484000000000"),
        "higher",
    )
    assert (fy26.given_on, fy26.source_note) == (date(2026, 11, 7), NOTE)


def test_an_unchanged_consensus_adds_nothing(seed_db: Any, db_session: Session) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    service.refresh_consensus(db_session, FakeConsensus(), company, NOW + timedelta(days=1))

    assert len(_forward(db_session, company)) == 8


def test_a_changed_range_on_a_later_day_is_a_new_revision(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)
    moved = FakeConsensus(rows=_with_range("478000000000", "486000000000"))

    service.refresh_consensus(db_session, moved, company, NOW + timedelta(days=1))

    log = guidance_service.guidance_log(db_session, company).entries
    fy26 = [
        e
        for e in log
        if (e.stored.source, e.stored.metric, e.stored.fiscal_year)
        == ("consensus", "revenue", 2026)
    ]
    assert [(e.stored.low, e.stored.given_on, e.result.latest) for e in fy26] == [
        (D("476002000000"), date(2026, 11, 7), False),
        (D("478000000000"), date(2026, 11, 8), True),
    ]
    assert len(_forward(db_session, company)) == 9


def test_a_changed_range_on_the_same_day_replaces_that_day_s_entry(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)
    moved = FakeConsensus(rows=_with_range("478000000000", "486000000000"))

    service.refresh_consensus(db_session, moved, company, NOW + timedelta(hours=3))

    entries = _forward(db_session, company)
    assert len(entries) == 8
    fy26 = next(g for g in entries if (g.metric, g.fiscal_year) == ("revenue", 2026))
    assert (fy26.low, fy26.high) == (D("478000000000"), D("486000000000"))


def test_an_estimate_for_a_reported_period_is_not_logged(seed_db: Any, db_session: Session) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    # Yahoo lagging the FY25 10-K: 0y's year-ago is FY24 (391,035 M), so 0y is FY25, which is
    # already reported, and +1y is FY26.
    lagging = [
        dataclasses.replace(r, year_ago_revenue=D("391035000000")) if r.period == "0y" else r
        for r in _recorded()
    ]

    service.refresh_consensus(db_session, FakeConsensus(rows=lagging), company, NOW)

    years = {
        (g.metric, g.fiscal_year)
        for g in _consensus_entries(db_session, company)
        if g.fiscal_period == "FY"
    }
    assert years == {("revenue", 2026), ("eps_diluted", 2026)}


def test_an_estimate_for_a_reported_quarter_is_not_logged(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    # Yahoo lagging a 10-Q: 0q's year-ago is FY25 Q3, so 0q is FY26 Q3 (already reported, the
    # latest stored quarter) and +1q is FY26 Q4.
    (table,) = statement_tables(db_session, company, [("IS", "quarterly")]).values()
    revenue = next(r for r in table.rows if r.code == "revenue")
    fy25_q3 = next(
        v
        for p, v in zip(table.periods, revenue.values, strict=True)
        if (p.fiscal_year, p.fiscal_period) == (2025, "Q3")
    )
    assert fy25_q3 is not None
    lagging = [
        dataclasses.replace(r, year_ago_revenue=fy25_q3) if r.period == "0q" else r
        for r in _recorded()
    ]

    service.refresh_consensus(db_session, FakeConsensus(rows=lagging), company, NOW)

    quarters = {
        (g.metric, g.fiscal_year, g.fiscal_period)
        for g in _consensus_entries(db_session, company)
        if g.fiscal_period != "FY"
    }
    assert quarters == {("revenue", 2026, "Q4"), ("eps_diluted", 2026, "Q4")}


def test_the_refresh_leaves_management_guidance_alone(seed_db: Any, db_session: Session) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    guidance_service.create_entry(
        db_session,
        company,
        guidance_service.GuidanceInput(
            "revenue",
            2026,
            "FY",
            D("470000000000"),
            D("480000000000"),
            "reported",
            None,
            date(2026, 10, 30),
            "Q4 call",
        ),
        NOW,
    )

    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    log = guidance_service.guidance_log(db_session, company).entries
    managed = [e for e in log if e.stored.source == "management"]
    assert [(e.stored.low, e.result.latest) for e in managed] == [(D("470000000000"), True)]


# --- backfill: the past year's quarterly EPS consensus from Yahoo's earnings history ---------


def _past(entries: list[Guidance]) -> list[Guidance]:
    return [g for g in entries if g.fiscal_year == 2026 and g.fiscal_period in ("Q1", "Q2", "Q3")]


def test_a_refresh_backfills_the_past_year_s_quarterly_eps_consensus(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")  # quarters stored to FY26 Q3; FY25 Q4 ended more than a year before NOW
    company = _aapl(db_session)

    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    past = sorted(_past(_consensus_entries(db_session, company)), key=lambda g: g.fiscal_period)
    assert [(g.metric, g.fiscal_period, g.low, g.high, g.basis) for g in past] == [
        ("eps_diluted", "Q1", D("2.6708"), D("2.6708"), "normalized"),
        ("eps_diluted", "Q2", D("1.94275"), D("1.94275"), "normalized"),
        ("eps_diluted", "Q3", D("1.89243"), D("1.89243"), "normalized"),
    ]
    q1 = past[0]
    assert q1.given_on == date(2025, 12, 27)  # the quarter's end: the average stood before
    assert q1.source_note == "Analyst consensus before the report (Yahoo earnings history, average)"
    assert {
        g.fiscal_year for g in _consensus_entries(db_session, company) if g.fiscal_year < 2026
    } == set()


def test_the_backfill_is_judged_against_the_reported_quarter(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    log = guidance_service.guidance_log(db_session, company).entries
    q1 = next(
        e
        for e in log
        if (e.stored.source, e.stored.fiscal_year, e.stored.fiscal_period)
        == ("consensus", 2026, "Q1")
    )
    assert q1.result.actual is not None and q1.result.verdict in ("beat", "miss", "in_range")


def test_the_backfill_is_added_once(seed_db: Any, db_session: Session) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    service.refresh_consensus(db_session, FakeConsensus(), company, NOW + timedelta(days=1))

    assert len(_past(_consensus_entries(db_session, company))) == 3


def test_a_quarter_with_consensus_already_logged_is_not_backfilled(
    seed_db: Any, db_session: Session
) -> None:
    seed_db("AAPL")
    company = _aapl(db_session)
    db_session.add(
        Guidance(
            company_id=company.id,
            metric="eps_diluted",
            fiscal_year=2026,
            fiscal_period="Q2",
            low=D("1.9"),
            high=D("2.0"),
            basis="normalized",
            direction="higher",
            given_on=date(2026, 1, 30),
            source="consensus",
            created_at=datetime(2026, 1, 30),
            updated_at=datetime(2026, 1, 30),
        )
    )
    db_session.commit()

    service.refresh_consensus(db_session, FakeConsensus(), company, NOW)

    q2 = [g for g in _past(_consensus_entries(db_session, company)) if g.fiscal_period == "Q2"]
    assert [(g.low, g.high) for g in q2] == [(D("1.9"), D("2.0"))]
