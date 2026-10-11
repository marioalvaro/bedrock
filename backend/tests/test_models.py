from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from bedrock.models.canonical_item import CanonicalItem
from bedrock.models.company import Company
from bedrock.models.concept_mapping import ConceptMapping
from bedrock.models.filing import Filing
from bedrock.models.price_daily import PriceDaily
from bedrock.models.raw_fact import RawFact


def _company(session: Session) -> Company:
    company = Company(
        ticker="AAPL",
        cik="0000320193",
        name="Apple Inc.",
        fiscal_year_end_month=9,
        currency="USD",
    )
    session.add(company)
    session.flush()
    return company


def _filing(session: Session, company: Company) -> Filing:
    filing = Filing(
        company_id=company.id,
        accession_no="0000320193-24-000123",
        form="10-K",
        filed_at=date(2024, 11, 1),
        fiscal_year=2024,
        fiscal_period="FY",
        period_end=date(2024, 9, 28),
    )
    session.add(filing)
    session.flush()
    return filing


def _fact(company: Company, filing: Filing, value: Decimal) -> RawFact:
    return RawFact(
        company_id=company.id,
        filing_id=filing.id,
        taxonomy="us-gaap",
        concept="Revenues",
        unit="USD",
        period_start=date(2023, 10, 1),
        period_end=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period="FY",
        frame="CY2023",
        value=value,
    )


def test_values_round_trip_as_exact_decimals(db_session: Session) -> None:
    company = _company(db_session)
    filing = _filing(db_session, company)
    db_session.add(_fact(company, filing, Decimal("391035000000")))
    db_session.add(
        PriceDaily(
            company_id=company.id,
            date=date(2024, 12, 31),
            close=Decimal("6.11"),
            adj_close=Decimal("6.11"),
            volume=5_000_000_000,
        )
    )
    db_session.commit()
    db_session.expire_all()

    fact = db_session.scalars(select(RawFact)).one()
    price = db_session.scalars(select(PriceDaily)).one()
    assert fact.value == Decimal("391035000000")
    assert fact.period_start == date(2023, 10, 1)
    assert price.close == Decimal("6.11")
    assert price.volume == 5_000_000_000


def test_deleting_a_company_cascades_to_its_data(db_session: Session) -> None:
    company = _company(db_session)
    filing = _filing(db_session, company)
    db_session.add(_fact(company, filing, Decimal("1")))
    db_session.add(
        PriceDaily(
            company_id=company.id,
            date=date(2024, 12, 31),
            close=Decimal("1"),
            adj_close=Decimal("1"),
            volume=1,
        )
    )
    db_session.add(
        CanonicalItem(
            code="revenue",
            statement="IS",
            label="Revenue",
            kind="flow",
            unit="USD",
            sign=1,
            display_order=0,
            parent_code=None,
        )
    )
    db_session.flush()
    db_session.add(
        ConceptMapping(
            canonical_code="revenue",
            taxonomy="us-gaap",
            concept="Revenues",
            priority=0,
            company_id=company.id,
        )
    )
    db_session.commit()

    db_session.delete(db_session.get(Company, company.id))
    db_session.commit()

    for model in (Filing, RawFact, PriceDaily, ConceptMapping):
        assert db_session.scalars(select(model)).all() == [], model.__name__
    assert db_session.scalars(select(CanonicalItem)).one().code == "revenue"


def test_a_filing_cascade_removes_its_facts(db_session: Session) -> None:
    company = _company(db_session)
    filing = _filing(db_session, company)
    db_session.add(_fact(company, filing, Decimal("1")))
    db_session.commit()

    db_session.delete(db_session.get(Filing, filing.id))
    db_session.commit()

    assert db_session.scalars(select(RawFact)).all() == []


def test_raw_fact_natural_key_is_unique(db_session: Session) -> None:
    company = _company(db_session)
    filing = _filing(db_session, company)
    db_session.add(_fact(company, filing, Decimal("1")))
    db_session.add(_fact(company, filing, Decimal("2")))
    with pytest.raises(Exception, match="UNIQUE"):
        db_session.commit()
    db_session.rollback()


def test_raw_fact_has_the_company_concept_index(db_session: Session) -> None:
    indexes = inspect(db_session.get_bind()).get_indexes("raw_fact")
    by_name = {index["name"]: index["column_names"] for index in indexes}
    assert by_name["ix_raw_fact_company_concept"] == ["company_id", "taxonomy", "concept"]
