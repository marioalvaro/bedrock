"""The coverage census of a followed company, read from the database, against the fixture pipeline
(M7b S1)."""

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.services.companies import add_manual_company
from bedrock.services.coverage import company_coverage

from .statements_pipeline import fixture_coverage, latest_10k_facts


@pytest.fixture
def aapl(seed_db: Callable[..., None], db_session: Session) -> Company:
    seed_db("AAPL")
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    return company


def test_the_database_census_equals_the_fixture_census(aapl: Company, db_session: Session) -> None:
    stored = company_coverage(db_session, aapl)
    expected = fixture_coverage("AAPL")

    assert set(stored.census.tables) == set(expected.census.tables)
    for key, table in expected.census.tables.items():
        assert stored.census.tables[key].buckets == table.buckets, key
        assert stored.census.tables[key].counts == table.counts, key
    assert stored.census.tables[("BS", "annual")].counts["candidate_exists"] > 0  # not vacuous


def test_the_latest_10k_and_the_candidate_facts_are_loaded(
    aapl: Company, db_session: Session
) -> None:
    stored = company_coverage(db_session, aapl)

    assert len(stored.latest_10k) == len(latest_10k_facts("AAPL"))
    assert len(stored.facts) == len(fixture_coverage("AAPL").facts)
    assert set(stored.tables) == {
        (s, f) for s in ("IS", "BS", "CF") for f in ("annual", "quarterly")
    }


def test_a_company_without_facts_has_an_empty_census(db_session: Session) -> None:
    company = add_manual_company(db_session, "ACME", "Acme Corp", 12, None).company

    stored = company_coverage(db_session, company)

    assert stored.census.tables == {}
    assert stored.latest_10k.empty and stored.facts.empty
