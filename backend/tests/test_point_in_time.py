"""Point-in-time history (FR-ACC-03, docs/erd/accountability.md "Point-in-time history"): a past
date sees only what was known on it. Runs on the recorded filings through the real database."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bedrock.forecast.history import ForecastHistory
from bedrock.ingest.sources import Sources
from bedrock.models.adjustment import Adjustment
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.models.imported_fact import ImportedFact
from bedrock.models.raw_fact import RawFact
from bedrock.models.statement_import import StatementImport
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import filing_lines as lines_repo
from bedrock.services.filings import ingest_filings
from bedrock.services.scenarios import load_history
from bedrock.services.statements import statement_tables
from bedrock.statements.build import StatementTable

from .fakes import FakeEdgar, FakeFilings, FakePrices

AAPL_FY2019_10K = date(2019, 10, 31)  # the filing date of AAPL's FY2019 10-K


def company(session: Session, ticker: str) -> Company:
    found = companies_repo.get_by_ticker(session, ticker)
    assert found is not None
    return found


def cell(table: StatementTable, code: str, key: str) -> Decimal | None:
    column = [p.key for p in table.periods].index(key)
    return next(r for r in table.rows if r.code == code).values[column]


def income(session: Session, who: Company, as_of: date | None = None) -> StatementTable:
    return statement_tables(session, who, [("IS", "annual")], "normalized", as_of=as_of)[
        ("IS", "annual")
    ]


def drop_filings_after(session: Session, who: Company, day: date) -> None:
    late = select(Filing.id).where(Filing.company_id == who.id, Filing.filed_at > day)
    session.execute(delete(RawFact).where(RawFact.filing_id.in_(late)))
    session.execute(delete(Filing).where(Filing.company_id == who.id, Filing.filed_at > day))
    session.commit()


def assert_same_history(left: ForecastHistory, right: ForecastHistory) -> None:
    assert left.latest_fy_end == right.latest_fy_end
    assert left.annual == right.annual
    assert left.quarterly == right.quarterly


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        # FY2017 as first filed, then the ASC 606 restatement in the FY2018 10-K
        (date(2017, 8, 2), Decimal("89950000000")),
        (date(2018, 8, 3), Decimal("96571000000")),
        (None, Decimal("96571000000")),
    ],
)
def test_msft_fy2017_revenue_is_the_figure_known_on_the_date(
    db_session: Session, seed_db: Callable[..., None], as_of: date | None, expected: Decimal
) -> None:
    seed_db("MSFT")
    table = income(db_session, company(db_session, "MSFT"), as_of)
    assert cell(table, "revenue", "FY2017") == expected


def test_a_past_eps_is_in_todays_shares(db_session: Session, seed_db: Callable[..., None]) -> None:
    seed_db("AAPL")
    table = income(db_session, company(db_session, "AAPL"), AAPL_FY2019_10K)
    assert cell(table, "eps_diluted", "FY2019") == Decimal("2.9725")


def test_a_filing_counts_on_its_filing_date_and_not_the_day_before(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    on_the_day = [p.key for p in income(db_session, who, AAPL_FY2019_10K).periods]
    the_day_before = [p.key for p in income(db_session, who, date(2019, 10, 30)).periods]
    assert "FY2019" in on_the_day
    assert "FY2019" not in the_day_before


@pytest.mark.parametrize(
    ("ticker", "day"),
    [("AAPL", date(2019, 10, 31)), ("AAPL", date(2016, 2, 1)), ("DE", date(2018, 12, 20))],
)
def test_no_period_ends_after_the_date(
    db_session: Session, seed_db: Callable[..., None], ticker: str, day: date
) -> None:
    seed_db(ticker)
    history = load_history(db_session, company(db_session, ticker), as_of=day)
    tables = [*history.annual.values(), *history.quarterly.values()]
    assert tables[0].periods
    assert all(p.end <= day for table in tables for p in table.periods)


@pytest.mark.parametrize(
    ("ticker", "day"),
    [("AAPL", date(2019, 10, 31)), ("DE", date(2019, 12, 17)), ("DE", date(2023, 12, 15))],
)
def test_a_past_date_equals_a_database_without_the_later_filings(
    db_session: Session, seed_db: Callable[..., None], ticker: str, day: date
) -> None:
    seed_db(ticker)
    who = company(db_session, ticker)
    cut = load_history(db_session, who, as_of=day)
    drop_filings_after(db_session, who, day)
    assert_same_history(cut, load_history(db_session, who))


def add_adjustment(session: Session, who: Company, created: datetime) -> None:
    session.add(
        Adjustment(
            company_id=who.id,
            canonical_code="revenue",
            fiscal_year=2018,
            fiscal_period="FY",
            amount=Decimal("1000000"),
            category="one-off",
            reason="test",
            created_at=created,
        )
    )
    session.commit()


@pytest.mark.parametrize(
    ("created", "applied"),
    [
        (datetime(2019, 10, 31, 23, 59), True),  # the whole of the day counts
        (datetime(2019, 11, 1, 0, 0), False),
    ],
)
def test_an_adjustment_counts_only_from_the_day_it_was_created(
    db_session: Session, seed_db: Callable[..., None], created: datetime, applied: bool
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    before = cell(income(db_session, who, AAPL_FY2019_10K), "revenue", "FY2018")
    assert before is not None
    add_adjustment(db_session, who, created)
    after = cell(income(db_session, who, AAPL_FY2019_10K), "revenue", "FY2018")
    assert after == (before + Decimal("1000000") if applied else before)


def add_import(session: Session, who: Company, imported: datetime) -> None:
    upload = StatementImport(
        company_id=who.id,
        filename="values.csv",
        format="csv",
        scale="units",
        imported_at=imported,
        cells=1,
    )
    session.add(upload)
    session.flush()
    session.add(
        ImportedFact(
            company_id=who.id,
            import_id=upload.id,
            line_code="goodwill_impairment",
            fiscal_year=2018,
            fiscal_period="FY",
            period_start=date(2017, 10, 1),
            period_end=date(2018, 9, 29),
            value=Decimal("7000000"),
        )
    )
    session.commit()


@pytest.mark.parametrize(
    ("imported", "expected"),
    [
        (datetime(2019, 10, 31, 23, 59), Decimal("7000000")),
        (datetime(2019, 11, 1, 0, 0), None),
    ],
)
def test_an_imported_value_counts_only_from_the_day_it_was_imported(
    db_session: Session, seed_db: Callable[..., None], imported: datetime, expected: Decimal | None
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    assert cell(income(db_session, who, AAPL_FY2019_10K), "goodwill_impairment", "FY2018") is None
    add_import(db_session, who, imported)
    value = cell(income(db_session, who, AAPL_FY2019_10K), "goodwill_impairment", "FY2018")
    assert value == expected


def test_a_cover_page_share_count_filed_later_is_ignored(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    tables = statement_tables(
        db_session, who, [("BS", "quarterly")], "normalized", as_of=AAPL_FY2019_10K
    )
    cut = tables[("BS", "quarterly")]
    drop_filings_after(db_session, who, AAPL_FY2019_10K)
    assert (
        cut
        == statement_tables(db_session, who, [("BS", "quarterly")], "normalized")[
            ("BS", "quarterly")
        ]
    )


def test_a_past_date_has_no_segment_series(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    assert (
        load_history(db_session, company(db_session, "AAPL"), as_of=AAPL_FY2019_10K).segment_series
        == ()
    )


def test_no_date_equals_the_call_without_one(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    assert_same_history(load_history(db_session, who, as_of=None), load_history(db_session, who))


def test_annual_filing_dates_are_the_distinct_10k_dates_ascending(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    filed = list(
        db_session.execute(
            select(Filing.filed_at).where(Filing.company_id == who.id, Filing.form == "10-K")
        ).scalars()
    )
    dates = facts_repo.annual_filing_dates(db_session, who.id)
    assert dates == sorted(set(filed))
    assert AAPL_FY2019_10K in dates


def test_annual_filing_dates_leave_out_amendments(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    before = facts_repo.annual_filing_dates(db_session, who.id)
    db_session.add(
        Filing(
            company_id=who.id,
            accession_no="AMENDMENT",
            form="10-K/A",
            filed_at=date(2030, 1, 2),
            fiscal_year=2029,
            fiscal_period="FY",
            period_end=date(2029, 9, 30),
        )
    )
    db_session.commit()
    assert facts_repo.annual_filing_dates(db_session, who.id) == before


def test_latest_filing_date_is_the_newest_of_any_form(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    newest = max(
        db_session.execute(select(Filing.filed_at).where(Filing.company_id == who.id)).scalars()
    )
    assert facts_repo.latest_filing_date(db_session, who.id) == newest
    db_session.execute(delete(RawFact).where(RawFact.company_id == who.id))
    db_session.execute(delete(Filing).where(Filing.company_id == who.id))
    db_session.commit()
    assert facts_repo.latest_filing_date(db_session, who.id) is None
    assert facts_repo.annual_filing_dates(db_session, who.id) == []


def test_the_lines_of_a_parsed_filing_are_known_from_its_filing_date(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    seed_db("AAPL")
    who = company(db_session, "AAPL")
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=FakeFilings())
    ingest_filings(db_session, sources, who, limit=None)

    before = lines_repo.lines_for(db_session, who.id, as_of=date(2024, 10, 31))
    on_the_day = lines_repo.lines_for(db_session, who.id, as_of=date(2024, 11, 1))

    assert set(before["accession_no"]) == {"0001193125-10-238044"}
    assert set(on_the_day["accession_no"]) == {"0001193125-10-238044", "0000320193-24-000123"}


def test_the_structure_rules_read_only_the_filings_known_on_the_date(
    db_session: Session, seed_db: Callable[..., None]
) -> None:
    from bedrock.services.statements import load_inputs

    seed_db("AAPL")
    who = company(db_session, "AAPL")
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=FakeFilings())
    ingest_filings(db_session, sources, who, limit=None)

    face = load_inputs(db_session, who, as_of=date(2024, 11, 1)).rules.filing_lines

    assert face is not None
    assert set(face.lines["accession_no"]) == {"0001193125-10-238044", "0000320193-24-000123"}
    assert all(filed <= date(2024, 11, 1) for filed in face.facts["filed_at"])
