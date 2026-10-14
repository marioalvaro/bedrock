from datetime import date

import pandas as pd

from bedrock.mapping.vintage import balance_snapshot, select_vintage
from tests.engine_data import fact, facts, mappings

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


# Balance-sheet snapshots. A restatement can reach one total and not the others (Costco's later
# 10-K lists only total assets for FY2014; Microsoft's restated equity sits in an equity statement
# with no balance sheet), so "latest per fact" would mix filings and the sheet would not balance.
# With `snapshot`, every instant of a balance date comes from the latest filing that carries a
# full set of totals for it.
ASSETS = frozenset({("us-gaap", "Assets")})
LIABILITIES = frozenset(
    {("us-gaap", "Liabilities"), ("us-gaap", "LiabilitiesAndStockholdersEquity")}
)
EQUITY = frozenset({("us-gaap", "StockholdersEquity")})
SNAPSHOT = (ASSETS, LIABILITIES, EQUITY)
BALANCE_DATE = date(2014, 8, 31)
ORIGINAL = {"accession": "K-14", "filed": date(2014, 10, 15)}
LATER = {"accession": "K-16", "filed": date(2016, 10, 12)}


def original_balance_sheet() -> list[dict[str, object]]:
    return [
        fact("Assets", None, BALANCE_DATE, 100, **ORIGINAL),
        fact("Liabilities", None, BALANCE_DATE, 60, **ORIGINAL),
        fact("StockholdersEquity", None, BALANCE_DATE, 40, **ORIGINAL),
        fact("Cash", None, BALANCE_DATE, 5, **ORIGINAL),
    ]


def values(latest) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {r["concept"]: int(r["value"]) for r in latest.to_dict("records")}


def test_a_later_filing_with_only_one_total_does_not_break_the_snapshot() -> None:
    rows = original_balance_sheet() + [fact("Assets", None, BALANCE_DATE, 95, **LATER)]

    assert values(select_vintage(facts(rows))) == {
        "Assets": 95,
        "Liabilities": 60,
        "StockholdersEquity": 40,
        "Cash": 5,
    }  # the unchanged rule mixes the filings
    snapshot = select_vintage(facts(rows), snapshot=SNAPSHOT)

    assert values(snapshot) == {
        "Assets": 100,
        "Liabilities": 60,
        "StockholdersEquity": 40,
        "Cash": 5,
    }
    assert set(snapshot["accession_no"]) == {"K-14"}


def test_a_later_equity_statement_alone_does_not_replace_the_balance_sheet_equity() -> None:
    rows = original_balance_sheet() + [fact("StockholdersEquity", None, BALANCE_DATE, 52, **LATER)]

    assert values(select_vintage(facts(rows), snapshot=SNAPSHOT))["StockholdersEquity"] == 40


def test_a_later_complete_balance_sheet_replaces_the_whole_snapshot() -> None:
    restated = [
        fact("Assets", None, BALANCE_DATE, 95, **LATER),
        fact("LiabilitiesAndStockholdersEquity", None, BALANCE_DATE, 95, **LATER),
        fact("StockholdersEquity", None, BALANCE_DATE, 38, **LATER),
        fact("Cash", None, BALANCE_DATE, 6, **LATER),
    ]

    snapshot = select_vintage(facts(original_balance_sheet() + restated), snapshot=SNAPSHOT)

    assert values(snapshot) == {
        "Assets": 95,
        "LiabilitiesAndStockholdersEquity": 95,
        "StockholdersEquity": 38,
        "Cash": 6,
    }  # the original Liabilities (60) is not mixed in
    assert set(snapshot["accession_no"]) == {"K-16"}


def test_a_detail_item_the_snapshot_filing_lacks_keeps_its_latest_value() -> None:
    rows = original_balance_sheet() + [
        fact("Goodwill", None, BALANCE_DATE, 7, **LATER),  # a later partial filing
        fact(
            "OperatingLeaseRightOfUseAsset", None, BALANCE_DATE, 9, accession="K-13"
        ),  # an older one
    ]

    latest = values(select_vintage(facts(rows), snapshot=SNAPSHOT))

    assert latest["Goodwill"] == 7
    assert latest["OperatingLeaseRightOfUseAsset"] == 9
    assert latest["Assets"] == 100  # the totals still come from the snapshot filing


def test_a_detail_item_the_snapshot_filing_carries_takes_its_value() -> None:
    rows = original_balance_sheet() + [fact("Cash", None, BALANCE_DATE, 7, **LATER)]

    assert values(select_vintage(facts(rows), snapshot=SNAPSHOT))["Cash"] == 5


def test_a_date_with_no_complete_filing_keeps_the_latest_value_of_each_fact() -> None:
    rows = [
        fact("Assets", None, BALANCE_DATE, 100, **ORIGINAL),
        fact("Liabilities", None, BALANCE_DATE, 60, **ORIGINAL),
        fact("Assets", None, BALANCE_DATE, 95, **LATER),
    ]  # nobody reported equity

    assert values(select_vintage(facts(rows), snapshot=SNAPSHOT)) == {
        "Assets": 95,
        "Liabilities": 60,
    }


def test_each_balance_date_picks_its_own_snapshot() -> None:
    other = date(2015, 8, 30)
    rows = original_balance_sheet() + [
        fact("Assets", None, other, 120, **LATER),
        fact("Liabilities", None, other, 70, **LATER),
        fact("StockholdersEquity", None, other, 50, **LATER),
    ]

    snapshot = select_vintage(facts(rows), snapshot=SNAPSHOT)

    by_date = {
        d: {
            r["concept"]: int(r["value"])
            for r in snapshot.to_dict("records")
            if r["period_end"] == d
        }
        for d in (BALANCE_DATE, other)
    }
    assert by_date[BALANCE_DATE]["Assets"] == 100
    assert by_date[other] == {"Assets": 120, "Liabilities": 70, "StockholdersEquity": 50}


def test_snapshots_leave_flows_alone() -> None:
    rows = original_balance_sheet() + [
        fact("Revenues", date(2013, 9, 1), BALANCE_DATE, 500, **ORIGINAL),
        fact("Revenues", date(2013, 9, 1), BALANCE_DATE, 510, **LATER),  # a restated flow wins
    ]

    latest = select_vintage(facts(rows), snapshot=SNAPSHOT)

    assert int(latest[latest["concept"] == "Revenues"].iloc[0]["value"]) == 510


def test_snapshots_respect_as_of() -> None:
    restated = [
        fact("Assets", None, BALANCE_DATE, 95, **LATER),
        fact("Liabilities", None, BALANCE_DATE, 57, **LATER),
        fact("StockholdersEquity", None, BALANCE_DATE, 38, **LATER),
    ]
    rows = original_balance_sheet() + restated

    assert (
        values(select_vintage(facts(rows), as_of=date(2015, 1, 1), snapshot=SNAPSHOT))["Assets"]
        == 100
    )
    assert (
        values(select_vintage(facts(rows), as_of=date(2017, 1, 1), snapshot=SNAPSHOT))["Assets"]
        == 95
    )


def test_without_a_snapshot_the_rule_is_unchanged() -> None:
    rows = original_balance_sheet() + [fact("Assets", None, BALANCE_DATE, 95, **LATER)]

    assert select_vintage(facts(rows)).equals(select_vintage(facts(rows), snapshot=()))


def test_balance_snapshot_builds_one_anchor_per_total_from_the_mapped_concepts() -> None:
    mapped = mappings(
        ("total_assets", "Assets", 0),
        ("total_liabilities", "Liabilities", 0),
        ("total_liabilities_and_equity", "LiabilitiesAndStockholdersEquity", 0),
        ("equity_parent", "StockholdersEquity", 0),
        (
            "total_equity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            0,
        ),
        ("total_equity", "StockholdersEquity", 1),
        ("cash", "Cash", 0),
    )
    # an override concept counts too
    overrides = mappings(("total_assets", "AssetsOverride", 0, True))

    anchors = balance_snapshot(pd.concat([mapped, overrides], ignore_index=True))

    assert anchors == [
        {("us-gaap", "Assets"), ("us-gaap", "AssetsOverride")},
        {("us-gaap", "Liabilities"), ("us-gaap", "LiabilitiesAndStockholdersEquity")},
        {
            ("us-gaap", "StockholdersEquity"),
            ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        },
    ]


def test_balance_snapshot_is_empty_when_a_total_is_not_mapped() -> None:
    # Without a mapped total the snapshot cannot be told apart from any filing: the rule stays off.
    assert balance_snapshot(mappings(("total_assets", "Assets", 0), ("cash", "Cash", 0))) == []


# Balance dates a few days apart are one balance date: Deere dates its FY2015 balance sheet
# 2015-10-31 in the 10-Ks that carry it in full, while its fiscal year ends 2015-11-01 and the
# FY2017 10-K's partial comparative column says so. The group is read at its latest date, and the
# latest filing that is complete for the group supplies the totals.
SHIFTED_DATE = date(2014, 9, 1)  # one day after BALANCE_DATE


def test_balance_dates_one_day_apart_are_one_date_and_the_complete_older_filing_wins() -> None:
    partial = [fact("Assets", None, SHIFTED_DATE, 95, **LATER)]

    snapshot = select_vintage(facts(original_balance_sheet() + partial), snapshot=SNAPSHOT)

    assert values(snapshot) == {
        "Assets": 100,
        "Liabilities": 60,
        "StockholdersEquity": 40,
        "Cash": 5,
    }
    assert set(snapshot["accession_no"]) == {"K-14"}
    assert set(snapshot["period_end"]) == {SHIFTED_DATE}  # read at the group's latest date


def test_the_latest_complete_filing_of_the_group_wins_whichever_date_it_used() -> None:
    restated = [
        fact("Assets", None, SHIFTED_DATE, 95, **LATER),
        fact("LiabilitiesAndStockholdersEquity", None, SHIFTED_DATE, 95, **LATER),
        fact("StockholdersEquity", None, SHIFTED_DATE, 38, **LATER),
    ]

    snapshot = select_vintage(facts(original_balance_sheet() + restated), snapshot=SNAPSHOT)

    assert values(snapshot)["Assets"] == 95
    assert values(snapshot)["Cash"] == 5  # a detail the later filing lacks keeps its latest value
    assert "Liabilities" not in values(snapshot)
    assert set(snapshot["period_end"]) == {SHIFTED_DATE}


def test_a_later_detail_value_on_the_exact_date_beats_an_older_one_on_the_shifted_date() -> None:
    rows = original_balance_sheet() + [fact("Cash", None, SHIFTED_DATE, 7, **LATER)]

    assert values(select_vintage(facts(rows), snapshot=SNAPSHOT))["Cash"] == 7


def test_balance_dates_a_week_apart_are_grouped_but_eight_days_apart_are_not() -> None:
    week = [fact("Assets", None, date(2014, 9, 7), 95, **LATER)]
    eight = [fact("Assets", None, date(2014, 9, 8), 95, **LATER)]

    grouped = select_vintage(facts(original_balance_sheet() + week), snapshot=SNAPSHOT)
    apart = select_vintage(facts(original_balance_sheet() + eight), snapshot=SNAPSHOT)

    assert set(grouped["period_end"]) == {date(2014, 9, 7)}
    assert values(grouped)["Assets"] == 100
    assert set(apart["period_end"]) == {BALANCE_DATE, date(2014, 9, 8)}
    assert len(apart) == 5  # the second date keeps its lone fact


def test_a_balance_date_with_no_neighbour_keeps_its_date() -> None:
    snapshot = select_vintage(facts(original_balance_sheet()), snapshot=SNAPSHOT)

    assert set(snapshot["period_end"]) == {BALANCE_DATE}


def test_shifting_dates_leaves_flows_and_unrelated_instants_alone() -> None:
    rows = original_balance_sheet() + [
        fact("Assets", None, SHIFTED_DATE, 95, **LATER),
        fact("Revenues", date(2013, 9, 1), BALANCE_DATE, 10, **ORIGINAL),
        fact("Revenues", date(2013, 9, 2), SHIFTED_DATE, 11, **LATER),
        fact("Shares", None, date(2014, 9, 3), 3, **LATER),  # a cover-page style date
    ]

    out = select_vintage(facts(rows), snapshot=SNAPSHOT)

    flows = out[out["concept"] == "Revenues"]
    assert sorted(flows["period_end"]) == [BALANCE_DATE, SHIFTED_DATE]
    assert list(out[out["concept"] == "Shares"]["period_end"]) == [date(2014, 9, 3)]


def test_without_a_snapshot_dates_are_not_shifted() -> None:
    rows = original_balance_sheet() + [fact("Assets", None, SHIFTED_DATE, 95, **LATER)]

    assert set(select_vintage(facts(rows))["period_end"]) == {BALANCE_DATE, SHIFTED_DATE}
