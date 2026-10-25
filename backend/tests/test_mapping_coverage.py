"""Every concept the open edgartools table recognizes in a company's latest 10-K is either mapped
or an acknowledged decision (`acknowledged_unmapped` in tests/golden/statements/<TICKER>.yaml).

A concept with a candidate code that nothing maps is a possible gap. Leaving it out has to be a
recorded decision with a reason, not silence, and a concept that a new 10-K introduces fails here
until someone decides (map-xbrl). A decision that no longer applies, because the concept is now
mapped or left the 10-K, fails too, so the lists stay honest.
"""

import pytest

from bedrock.mapping.candidates import (
    DEFAULT_CROSSWALK_PATH,
    DEFAULT_VENDOR_PATH,
    load_candidate_index,
)
from bedrock.mapping.gaps import unmapped_concepts
from bedrock.mapping.triage import DEFAULT_TRIAGE_PATH, ConceptVerdict, load_concept_triage
from tests.statements_pipeline import latest_10k_facts, run_pipeline
from tests.test_statements_golden import TICKERS, golden


def candidates_without_a_mapping(ticker: str) -> set[str]:
    pipeline = run_pipeline(ticker)
    index = load_candidate_index(DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, pipeline.items)
    unmapped = unmapped_concepts(latest_10k_facts(ticker), pipeline.mappings, index)
    return {f"{u.taxonomy}:{u.concept}" for u in unmapped if u.suggested_codes}


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_candidate_in_the_latest_10k_is_mapped_or_acknowledged(ticker: str) -> None:
    acknowledged = golden(ticker).get("acknowledged_unmapped", {})

    undecided = sorted(candidates_without_a_mapping(ticker) - set(acknowledged))

    assert undecided == [], (
        f"{ticker}: the latest 10-K has concepts with candidate codes and no decision. Run the "
        "map-xbrl skill on each: map it, or add it to `acknowledged_unmapped` with the reason."
    )


@pytest.mark.parametrize("ticker", TICKERS)
def test_acknowledged_concepts_are_still_unmapped_candidates(ticker: str) -> None:
    acknowledged = golden(ticker).get("acknowledged_unmapped", {})

    stale = sorted(set(acknowledged) - candidates_without_a_mapping(ticker))

    assert stale == [], f"{ticker}: mapped now, or not in the latest 10-K any more: remove them"


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_acknowledgement_gives_a_reason(ticker: str) -> None:
    acknowledged = golden(ticker).get("acknowledged_unmapped", {})

    assert all(isinstance(r, str) and len(r.split()) >= 3 for r in acknowledged.values())


# --- the triage (M3 S6, FR-DATA-13) --------------------------------------------------------


def unclassified_candidates(
    ticker: str, triage: dict[tuple[str, str], ConceptVerdict]
) -> list[str]:
    pipeline = run_pipeline(ticker)
    index = load_candidate_index(DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, pipeline.items)
    unmapped = unmapped_concepts(latest_10k_facts(ticker), pipeline.mappings, index, triage)
    return [
        f"{u.taxonomy}:{u.concept}" for u in unmapped if u.suggested_codes and not u.classification
    ]


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_suggested_unmapped_concept_has_a_triage_verdict(ticker: str) -> None:
    triage = load_concept_triage(DEFAULT_TRIAGE_PATH, run_pipeline(ticker).items)

    assert unclassified_candidates(ticker, {}) != []  # the check can fail
    assert unclassified_candidates(ticker, triage) == [], (
        f"{ticker}: the latest 10-K has suggested concepts nobody classified. Add each to "
        "mapping/concept_triage.yaml with a reason, or map it with the map-xbrl skill."
    )


def test_every_verdict_applies_to_a_concept_one_of_the_four_companies_leaves_unmapped() -> None:
    triage = load_concept_triage(DEFAULT_TRIAGE_PATH, run_pipeline("AAPL").items)
    used: set[tuple[str, str]] = set()
    for ticker in TICKERS:
        pipeline = run_pipeline(ticker)
        index = load_candidate_index(DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, pipeline.items)
        unmapped = unmapped_concepts(latest_10k_facts(ticker), pipeline.mappings, index)
        used |= {(u.taxonomy, u.concept) for u in unmapped}

    assert sorted(set(triage) - used) == []  # a verdict nobody needs any more is stale
