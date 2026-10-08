from datetime import date

from bedrock.mapping.vintage import select_vintage
from tests.engine_data import fact, facts

FY_START, FY_END = date(2022, 7, 1), date(2023, 6, 30)


def rows() -> list[dict[str, object]]:
    return [
        fact("Revenues", FY_START, FY_END, 540, accession="K-23", filed=date(2023, 8, 20)),
        # the next 10-K restates the same fiscal year
        fact("Revenues", FY_START, FY_END, 545, accession="K-24", filed=date(2024, 8, 20)),
        fact(
            "Revenues",
            date(2023, 7, 1),
            date(2024, 6, 30),
            600,
            accession="K-24",
            filed=date(2024, 8, 20),
        ),
    ]


def test_latest_filing_wins_for_a_restated_value() -> None:
    latest = select_vintage(facts(rows()))

    assert len(latest) == 2
    restated = latest[latest["period_end"] == FY_END].iloc[0]
    assert restated["value"] == 545
    assert restated["accession_no"] == "K-24"


def test_as_of_before_the_restatement_returns_the_original() -> None:
    original = select_vintage(facts(rows()), as_of=date(2024, 1, 1))

    assert len(original) == 1
    assert original.iloc[0]["value"] == 540
    assert original.iloc[0]["accession_no"] == "K-23"


def test_as_of_includes_filings_on_that_day() -> None:
    assert len(select_vintage(facts(rows()), as_of=date(2024, 8, 20))) == 2


def test_as_of_before_everything_is_empty() -> None:
    assert select_vintage(facts(rows()), as_of=date(2020, 1, 1)).empty


def test_ties_on_filed_at_break_by_max_accession() -> None:
    same_day = [
        fact("Revenues", FY_START, FY_END, 1, accession="A-1", filed=date(2023, 8, 20)),
        fact("Revenues", FY_START, FY_END, 2, accession="A-2", filed=date(2023, 8, 20)),
    ]

    assert select_vintage(facts(same_day)).iloc[0]["accession_no"] == "A-2"


def test_instant_facts_with_no_start_are_deduplicated() -> None:
    instants = [
        fact("Cash", None, FY_END, 10, accession="K-23", filed=date(2023, 8, 20)),
        fact("Cash", None, FY_END, 11, accession="K-24", filed=date(2024, 8, 20)),
    ]

    latest = select_vintage(facts(instants))

    assert len(latest) == 1
    assert latest.iloc[0]["value"] == 11


def test_different_units_and_concepts_are_kept_apart() -> None:
    mixed = [
        fact("EPS", FY_START, FY_END, 1, unit="USD/shares"),
        fact("EPS", FY_START, FY_END, 2, unit="USD"),
        fact("Other", FY_START, FY_END, 3),
    ]

    assert len(select_vintage(facts(mixed))) == 3


def test_empty_input_stays_empty() -> None:
    assert select_vintage(facts([])).empty
