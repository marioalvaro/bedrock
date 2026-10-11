"""Repositories over a real SQLite database, fed from the recorded AAPL fixture."""

import gzip
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.ingest.parse import ParsedFacts, parse_companyfacts
from bedrock.ingest.protocol import PriceRow
from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    DEFAULT_OVERRIDES_DIR,
    load_canonical_items,
    load_overrides,
)
from bedrock.models.canonical_item import CanonicalItem
from bedrock.models.company import Company
from bedrock.models.concept_mapping import ConceptMapping
from bedrock.models.filing import Filing
from bedrock.models.price_daily import PriceDaily
from bedrock.models.raw_fact import RawFact
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import mappings as mappings_repo
from bedrock.repositories import prices as prices_repo

from .statements_pipeline import fact_frame, mapping_frame

FIXTURE = Path(__file__).parent / "fixtures" / "edgar" / "AAPL.json.gz"
FACT_COLUMNS = [
    "taxonomy",
    "concept",
    "unit",
    "period_start",
    "period_end",
    "value",
    "accession_no",
    "form",
    "filed_at",
]


@cache
def _doc() -> dict[str, Any]:
    with gzip.open(FIXTURE, "rt") as handle:
        doc: dict[str, Any] = json.load(handle)
    return doc


@cache
def _parsed() -> ParsedFacts:
    return parse_companyfacts(_doc())


def _company(session: Session, ticker: str = "AAPL", cik: str = "0000320193") -> Company:
    company = Company(
        ticker=ticker,
        cik=cik,
        name=f"{ticker} Inc.",
        fiscal_year_end_month=9,
        currency="USD",
        sic=None,
        last_refreshed_at=None,
    )
    session.add(company)
    session.commit()
    return company


def _count(session: Session, model: type[Filing] | type[RawFact]) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _rows(frame: pd.DataFrame) -> list[tuple[object, ...]]:
    return sorted(
        (tuple(r) for r in frame[FACT_COLUMNS].itertuples(index=False)),
        key=lambda r: tuple(str(x) for x in r),
    )


# --- companies -------------------------------------------------------------------------------


def test_companies_are_found_by_ticker_and_listed_in_ticker_order(db_session: Session) -> None:
    _company(db_session, "MSFT", "0000789019")
    _company(db_session, "AAPL")

    assert companies_repo.get_by_ticker(db_session, "AAPL") is not None
    assert companies_repo.get_by_ticker(db_session, "ZZZZ") is None
    assert companies_repo.get_by_cik(db_session, "0000789019") is not None
    assert companies_repo.get_by_cik(db_session, "0000000001") is None
    assert [c.ticker for c in companies_repo.list_all(db_session)] == ["AAPL", "MSFT"]


# --- facts -----------------------------------------------------------------------------------


def test_insert_parsed_stores_every_filing_and_fact(db_session: Session) -> None:
    company = _company(db_session)

    new_filings, new_facts = facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()

    assert new_filings == len(_parsed().filings)
    assert new_facts == len(_parsed().facts)
    assert _count(db_session, Filing) == new_filings
    assert _count(db_session, RawFact) == new_facts


def test_a_second_insert_of_the_same_payload_inserts_nothing(db_session: Session) -> None:
    company = _company(db_session)
    facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()
    instants = db_session.execute(
        select(func.count()).select_from(RawFact).where(RawFact.period_start.is_(None))
    ).scalar_one()
    assert instants > 0  # SQLite's UNIQUE does not stop these; the repository must

    assert facts_repo.insert_parsed(db_session, company, _parsed()) == (0, 0)
    db_session.commit()

    assert _count(db_session, RawFact) == len(_parsed().facts)


def test_a_new_fact_of_a_known_filing_is_added_and_a_repeated_instant_is_not(
    db_session: Session,
) -> None:
    company = _company(db_session)
    facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()
    parsed = _parsed()
    instant = next(f for f in parsed.facts if f.period_start is None)
    extra = replace(instant, concept="BrandNewConcept", value=Decimal("7"))

    result = facts_repo.insert_parsed(
        db_session, company, ParsedFacts(filings=parsed.filings, facts=[instant, extra])
    )

    assert result == (0, 1)


def test_load_facts_returns_every_vintage_of_the_requested_concepts(db_session: Session) -> None:
    company = _company(db_session)
    facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    mappings = mapping_frame(items, load_overrides(DEFAULT_OVERRIDES_DIR, "AAPL", items))
    wanted = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))

    loaded = facts_repo.load_facts(db_session, company.id, wanted)

    assert list(loaded.columns) == FACT_COLUMNS
    assert _rows(loaded) == _rows(fact_frame("AAPL", mappings))


def test_load_facts_loads_nothing_else(db_session: Session) -> None:
    company = _company(db_session)
    facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()

    loaded = facts_repo.load_facts(db_session, company.id, {("us-gaap", "Assets")})

    assert set(zip(loaded["taxonomy"], loaded["concept"], strict=True)) == {("us-gaap", "Assets")}
    assert len(loaded) > 10


def test_load_facts_of_another_company_is_empty(db_session: Session) -> None:
    aapl = _company(db_session)
    other = _company(db_session, "MSFT", "0000789019")
    facts_repo.insert_parsed(db_session, aapl, _parsed())
    db_session.commit()

    assert facts_repo.load_facts(db_session, other.id, {("us-gaap", "Assets")}).empty


def test_loaded_values_are_plain_decimals(db_session: Session) -> None:
    # Numeric(28, 10) comes back padded with zeros ("391035000000.0000000000"), which would
    # leak into the API's JSON strings.
    company = _company(db_session)
    facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()

    loaded = facts_repo.load_facts(db_session, company.id, {("us-gaap", "Assets")})

    assert all("." not in str(v) and "E" not in str(v) for v in loaded["value"])
    eps = facts_repo.load_facts(db_session, company.id, {("us-gaap", "EarningsPerShareDiluted")})
    assert Decimal("6.11") in set(eps["value"])


def test_latest_annual_facts_are_all_of_the_newest_10k(db_session: Session) -> None:
    company = _company(db_session)
    facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()
    newest = max(
        (f for f in _parsed().filings if f.form.startswith("10-K")),
        key=lambda f: (f.filed_at, f.accession_no),
    )

    loaded = facts_repo.load_latest_annual_facts(db_session, company.id)

    assert set(loaded["accession_no"]) == {newest.accession_no}
    assert set(loaded["form"]) == {newest.form}
    assert len(loaded) == sum(1 for f in _parsed().facts if f.accession_no == newest.accession_no)


def test_latest_annual_facts_of_a_company_without_data_is_empty(db_session: Session) -> None:
    company = _company(db_session)

    loaded = facts_repo.load_latest_annual_facts(db_session, company.id)

    assert loaded.empty
    assert list(loaded.columns) == FACT_COLUMNS


def test_latest_shares_outstanding_is_the_newest_filed_value_at_the_latest_end(
    db_session: Session,
) -> None:
    company = _company(db_session)
    facts_repo.insert_parsed(db_session, company, _parsed())
    db_session.commit()
    doc = _doc()
    rows = doc["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    expected = Decimal(str(max(rows, key=lambda r: (r["end"], r["filed"]))["val"]))

    assert facts_repo.latest_shares_outstanding(db_session, company.id) == expected


def test_latest_shares_outstanding_is_none_without_data(db_session: Session) -> None:
    assert facts_repo.latest_shares_outstanding(db_session, _company(db_session).id) is None


# --- mappings --------------------------------------------------------------------------------


def test_replace_mappings_stores_items_defaults_and_followed_overrides(db_session: Session) -> None:
    aapl = _company(db_session)
    msft = _company(db_session, "MSFT", "0000789019")
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    mappings_repo.replace_mappings(
        db_session, items, {aapl.id: {"common_stock_apic": ["us-gaap:CommonStockValue"]}}
    )
    db_session.commit()

    assert _count_rows(db_session, CanonicalItem) == len(items) == 78
    frame = mappings_repo.mappings_for(db_session, aapl.id)
    assert list(frame.columns) == [
        "canonical_code",
        "taxonomy",
        "concept",
        "priority",
        "is_override",
    ]
    override = frame[frame["is_override"]]
    assert list(override["concept"]) == ["CommonStockValue"]
    assert list(override["canonical_code"]) == ["common_stock_apic"]
    defaults = frame[~frame["is_override"]]
    assert {"Revenues", "Assets"} <= set(defaults["concept"])
    # Another company sees the defaults only.
    assert not mappings_repo.mappings_for(db_session, msft.id)["is_override"].any()


def test_a_summed_concept_is_stored_as_one_row_per_member_sharing_a_priority(
    db_session: Session,
) -> None:
    aapl = _company(db_session)
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    summed = {
        "short_term_debt": [
            "us-gaap:CommercialPaper + us-gaap:LongTermDebtCurrent",
            "us-gaap:LongTermDebtCurrent",
        ]
    }

    mappings_repo.replace_mappings(db_session, items, {aapl.id: summed})
    db_session.commit()

    frame = mappings_repo.mappings_for(db_session, aapl.id)
    override = frame[frame["is_override"] & (frame["canonical_code"] == "short_term_debt")]
    assert list(zip(override["concept"], override["priority"], strict=True)) == [
        ("CommercialPaper", 0),  # the anchor comes first: rows are read back in insertion order
        ("LongTermDebtCurrent", 0),
        ("LongTermDebtCurrent", 1),
    ]


def test_replace_mappings_twice_leaves_no_duplicates(db_session: Session) -> None:
    aapl = _company(db_session)
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    overrides = {aapl.id: {"common_stock_apic": ["us-gaap:CommonStockValue"]}}

    mappings_repo.replace_mappings(db_session, items, overrides)
    db_session.commit()
    first = _count_rows(db_session, ConceptMapping)
    mappings_repo.replace_mappings(db_session, items, overrides)
    db_session.commit()

    assert _count_rows(db_session, ConceptMapping) == first


def test_the_mapping_frame_matches_the_one_the_engine_tests_build(db_session: Session) -> None:
    aapl = _company(db_session)
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    overrides = load_overrides(DEFAULT_OVERRIDES_DIR, "AAPL", items)
    mappings_repo.replace_mappings(db_session, items, {aapl.id: overrides})
    db_session.commit()

    stored = mappings_repo.mappings_for(db_session, aapl.id)
    expected = mapping_frame(items, overrides)

    def key(frame: pd.DataFrame) -> list[tuple[object, ...]]:
        return sorted(tuple(r) for r in frame.itertuples(index=False))

    assert key(stored) == key(expected)


def _count_rows(session: Session, model: type[CanonicalItem] | type[ConceptMapping]) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


# --- prices ----------------------------------------------------------------------------------


def _price(day: date, close: str) -> PriceRow:
    return PriceRow(date=day, close=Decimal(close), adj_close=Decimal(close), volume=10)


def test_prices_have_no_last_date_or_close_until_inserted(db_session: Session) -> None:
    company = _company(db_session)

    assert prices_repo.last_date(db_session, company.id) is None
    assert prices_repo.latest_close(db_session, company.id) is None


def test_inserted_prices_give_the_last_date_and_the_latest_close(db_session: Session) -> None:
    company = _company(db_session)
    rows = [_price(date(2026, 10, 6), "250.5"), _price(date(2026, 10, 7), "251.25")]

    assert prices_repo.insert_new(db_session, company.id, rows) == 2
    db_session.commit()

    assert prices_repo.last_date(db_session, company.id) == date(2026, 10, 7)
    assert prices_repo.latest_close(db_session, company.id) == (
        date(2026, 10, 7),
        Decimal("251.25"),
    )


def test_the_latest_close_is_a_plain_decimal(db_session: Session) -> None:
    # Numeric(28, 10) comes back padded ("336.8450000000"), which would reach the API's JSON.
    company = _company(db_session)
    prices_repo.insert_new(db_session, company.id, [_price(date(2026, 10, 7), "336.845")])
    db_session.commit()

    latest = prices_repo.latest_close(db_session, company.id)

    assert latest is not None and str(latest[1]) == "336.845"


def test_inserting_a_known_date_again_is_skipped(db_session: Session) -> None:
    company = _company(db_session)
    prices_repo.insert_new(db_session, company.id, [_price(date(2026, 10, 6), "250.5")])
    db_session.commit()

    added = prices_repo.insert_new(
        db_session,
        company.id,
        [_price(date(2026, 10, 6), "999"), _price(date(2026, 10, 7), "251")],
    )
    db_session.commit()

    assert added == 1
    assert prices_repo.latest_close(db_session, company.id) == (date(2026, 10, 7), Decimal("251"))
    kept = db_session.get(PriceDaily, (company.id, date(2026, 10, 6)))
    assert kept is not None and kept.close == Decimal("250.5")


@pytest.mark.parametrize("count", [0])
def test_inserting_no_prices_adds_none(db_session: Session, count: int) -> None:
    assert prices_repo.insert_new(db_session, _company(db_session).id, []) == count
