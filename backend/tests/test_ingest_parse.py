import gzip
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bedrock.ingest.parse import FactRecord, ParsedFacts, parse_companyfacts

FIXTURES = Path(__file__).parent / "fixtures"
AAPL_10K_FY24 = "0000320193-24-000123"


@pytest.fixture(scope="module")
def aapl() -> ParsedFacts:
    with gzip.open(FIXTURES / "edgar" / "AAPL.json.gz", "rt") as handle:
        return parse_companyfacts(json.load(handle))


def _fact(accn: str | None = "0001-24-000001", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "start": "2023-01-01",
        "end": "2023-12-31",
        "val": 100,
        "fy": 2023,
        "fp": "FY",
        "form": "10-K",
        "filed": "2024-02-01",
    }
    if accn is not None:
        row["accn"] = accn
    row.update(overrides)
    return row


def _doc(**taxonomies: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    return {
        "cik": 1,
        "facts": {
            taxonomy: {concept: {"units": units} for concept, units in concepts.items()}
            for taxonomy, concepts in taxonomies.items()
        },
    }


def test_a_known_10k_has_its_form_filed_date_and_period_end(aapl: ParsedFacts) -> None:
    filing = next(f for f in aapl.filings if f.accession_no == AAPL_10K_FY24)

    assert filing.form == "10-K"
    assert filing.filed_at == date(2024, 11, 1)
    assert filing.period_end == date(2024, 9, 28)
    assert (filing.fiscal_year, filing.fiscal_period) == (2024, "FY")


def test_instant_facts_have_no_period_start(aapl: ParsedFacts) -> None:
    assets = [
        f
        for f in aapl.facts
        if f.accession_no == AAPL_10K_FY24 and f.concept == "Assets" and f.taxonomy == "us-gaap"
    ]

    assert {f.period_end: f.value for f in assets} == {
        date(2023, 9, 30): Decimal("352583000000"),
        date(2024, 9, 28): Decimal("364980000000"),
    }
    assert all(f.period_start is None for f in assets)


def test_duration_facts_keep_their_start_and_decimal_value(aapl: ParsedFacts) -> None:
    eps = [
        f
        for f in aapl.facts
        if f.accession_no == AAPL_10K_FY24 and f.concept == "EarningsPerShareDiluted"
    ]
    latest = max(eps, key=lambda f: f.period_end)

    assert latest.unit == "USD/shares"
    assert latest.period_start == date(2023, 10, 1)
    assert latest.value == Decimal("6.08")


def test_dei_facts_are_parsed_but_do_not_set_the_filing_period_end(aapl: ParsedFacts) -> None:
    cover = [
        f
        for f in aapl.facts
        if f.accession_no == AAPL_10K_FY24 and f.concept == "EntityCommonStockSharesOutstanding"
    ]

    assert [(f.taxonomy, f.unit, f.period_end) for f in cover] == [
        ("dei", "shares", date(2024, 10, 18))
    ]


def test_every_fact_belongs_to_a_parsed_filing_and_none_repeat(aapl: ParsedFacts) -> None:
    accessions = {f.accession_no for f in aapl.filings}
    keys = [
        (f.accession_no, f.taxonomy, f.concept, f.unit, f.period_start, f.period_end)
        for f in aapl.facts
    ]

    assert len(accessions) == len(aapl.filings)
    assert {f.accession_no for f in aapl.facts} == accessions
    assert len(keys) == len(set(keys))
    assert len(aapl.filings) > 40


def test_a_duplicated_fact_is_kept_once_and_the_first_wins() -> None:
    first = _fact(val=100)
    second = _fact(val=999)  # same natural key, e.g. repeated under a second frame
    doc = _doc(**{"us-gaap": {"Revenues": {"USD": [first, second]}}})

    parsed = parse_companyfacts(doc)

    assert [f.value for f in parsed.facts] == [Decimal("100")]


def test_duplicate_instant_facts_are_kept_once() -> None:
    row = _fact(start=None, val=5)
    row.pop("start")
    doc = _doc(**{"us-gaap": {"Assets": {"USD": [dict(row), dict(row, val=6)]}}})

    parsed = parse_companyfacts(doc)

    assert [(f.period_start, f.value) for f in parsed.facts] == [(None, Decimal("5"))]


def test_the_same_fact_in_two_filings_is_two_vintages() -> None:
    doc = _doc(
        **{
            "us-gaap": {
                "Revenues": {
                    "USD": [
                        _fact("0001-24-000001", val=100, filed="2024-02-01"),
                        _fact("0001-25-000001", val=90, filed="2025-02-01", fy=2024),
                    ]
                }
            }
        }
    )

    parsed = parse_companyfacts(doc)

    assert sorted((f.accession_no, f.value) for f in parsed.facts) == [
        ("0001-24-000001", Decimal("100")),
        ("0001-25-000001", Decimal("90")),
    ]
    assert [f.accession_no for f in parsed.filings] == ["0001-24-000001", "0001-25-000001"]


def test_facts_without_an_accession_are_skipped() -> None:
    doc = _doc(**{"us-gaap": {"Revenues": {"USD": [_fact(None), _fact()]}}})

    parsed = parse_companyfacts(doc)

    assert len(parsed.facts) == 1


def test_every_taxonomy_and_unit_is_covered() -> None:
    doc = _doc(
        **{
            "us-gaap": {
                "Revenues": {"USD": [_fact()]},
                "EarningsPerShareBasic": {"USD/shares": [_fact()]},
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"shares": [_fact(start=None)]}},
            "srt": {"Foo": {"pure": [_fact()]}},
        }
    )

    parsed = parse_companyfacts(doc)

    assert {(f.taxonomy, f.unit) for f in parsed.facts} == {
        ("us-gaap", "USD"),
        ("us-gaap", "USD/shares"),
        ("dei", "shares"),
        ("srt", "pure"),
    }


def test_the_frame_is_kept_when_present() -> None:
    doc = _doc(**{"us-gaap": {"Revenues": {"USD": [_fact(frame="CY2023")]}}})

    (fact,) = parse_companyfacts(doc).facts

    assert fact == FactRecord(
        accession_no="0001-24-000001",
        taxonomy="us-gaap",
        concept="Revenues",
        unit="USD",
        period_start=date(2023, 1, 1),
        period_end=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period="FY",
        frame="CY2023",
        value=Decimal("100"),
    )


def test_a_filing_with_only_dei_facts_falls_back_to_their_latest_end() -> None:
    doc = _doc(
        dei={
            "EntityCommonStockSharesOutstanding": {"shares": [_fact(start=None, end="2024-01-15")]}
        }
    )

    (filing,) = parse_companyfacts(doc).filings

    assert filing.period_end == date(2024, 1, 15)
