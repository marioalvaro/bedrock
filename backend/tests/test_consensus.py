"""Analyst consensus as guidance (docs/erd/analysis.md "Consensus guidance"): placing
Yahoo's relative periods (0q, +1q, 0y, +1y) on fiscal periods, by the year-ago revenue each row
carries. Pure, on the recorded AAPL frames."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from bedrock.analysis.consensus import (
    ConsensusRow,
    EpsHistoryRow,
    PlacedEstimate,
    PlacedHistory,
    history_from_frame,
    place,
    place_history,
    rows_from_frames,
)

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures" / "consensus"


def _recorded() -> list[ConsensusRow]:
    revenue = pd.read_csv(FIXTURES / "AAPL_revenue_estimate.csv", index_col="period")
    earnings = pd.read_csv(FIXTURES / "AAPL_earnings_estimate.csv", index_col="period")
    return rows_from_frames(revenue, earnings)


# AAPL's stored revenue: FY25 is the recorded 0y row's year-ago revenue (416,161 M), and FY26 Q1
# the 0q row's (143,756 M), three quarters before the latest stored quarter (FY26 Q4).
ANNUAL = {2024: D("391035000000"), 2025: D("416161000000")}
QUARTERLY = {
    (2025, "Q4"): D("102466000000"),
    (2026, "Q1"): D("143756000000"),
    (2026, "Q2"): D("111184000000"),
    (2026, "Q3"): D("94036000000"),
    (2026, "Q4"): D("102500000000"),
}


def test_the_frames_become_rows_with_their_year_ago_revenue() -> None:
    rows = _recorded()

    by = {(r.period, r.metric): r for r in rows}
    assert set(by) == {(p, m) for p in ("0q", "+1q", "0y", "+1y") for m in ("revenue", "eps")}
    assert by[("0y", "revenue")] == ConsensusRow(
        "0y",
        "revenue",
        D("476002000000"),
        D("477692148210"),
        D("484000000000"),
        37,
        D("416161000000"),
    )
    assert by[("0q", "eps")].low == D("2.83") and by[("0q", "eps")].analysts == 27
    # An EPS row is placed by its period's revenue anchor.
    assert by[("0q", "eps")].year_ago_revenue == D("143756000000")


def test_a_year_is_placed_after_the_fiscal_year_whose_revenue_matches_the_year_ago() -> None:
    placed = place(_recorded(), ANNUAL, QUARTERLY)

    fy = [p for p in placed if p.fiscal_period == "FY"]
    assert {(p.metric, p.fiscal_year) for p in fy} == {
        ("revenue", 2026),
        ("eps_diluted", 2026),
        ("revenue", 2027),
        ("eps_diluted", 2027),
    }
    assert (
        PlacedEstimate(
            "revenue", 2026, "FY", D("476002000000"), D("477692148210"), D("484000000000"), 37
        )
        in placed
    )


def test_a_quarter_is_placed_a_year_after_the_quarter_whose_revenue_matches() -> None:
    placed = place(_recorded(), ANNUAL, QUARTERLY)

    # 0q's year-ago revenue is FY26 Q1's: 0q is FY27 Q1, and +1q follows it.
    q = {(p.metric, p.fiscal_year, p.fiscal_period) for p in placed if p.fiscal_period != "FY"}
    assert ("revenue", 2027, "Q1") in q and ("eps_diluted", 2027, "Q1") in q
    assert ("revenue", 2027, "Q2") in q


def test_a_row_whose_year_ago_matches_nothing_is_left_out() -> None:
    assert place(_recorded(), {2010: D(1)}, {}) == []


@pytest.mark.parametrize("off", [D("0.98"), D("1.02")])
def test_the_year_ago_match_allows_one_percent_and_no_more(off: Decimal) -> None:
    annual = {2025: D("416161000000") * off}
    assert [p for p in place(_recorded(), annual, {}) if p.fiscal_period == "FY"] == []


def test_a_row_without_a_range_is_left_out() -> None:
    row = ConsensusRow("0y", "revenue", None, D(5), None, 3, D("416161000000"))
    assert place([row], ANNUAL, {}) == []


def _fy(placed: list[PlacedEstimate]) -> set[tuple[str, int]]:
    return {(p.metric, p.fiscal_year) for p in placed if p.fiscal_period == "FY"}


def _quarters(placed: list[PlacedEstimate]) -> set[tuple[int, str]]:
    return {(p.fiscal_year, p.fiscal_period) for p in placed if p.fiscal_period != "FY"}


def test_a_year_lagging_one_report_behind_is_still_placed() -> None:
    # Just after the FY26 10-K, Yahoo's 0y can still be FY26 (year-ago FY25).
    annual = {**ANNUAL, 2026: D("470000000000")}

    assert _fy(place(_recorded(), annual, {})) == {
        ("revenue", 2026),
        ("eps_diluted", 2026),
        ("revenue", 2027),
        ("eps_diluted", 2027),
    }


def test_a_year_ago_matching_only_an_old_year_is_left_out() -> None:
    # DE: Yahoo's year-ago revenue is equipment sales (38,917 M), below the stored total
    # (FY25 45,684 M), and happens to match FY19 (39,258 M) within 1 %.
    annual = {2019: D("39258000000"), 2024: D("51716000000"), 2025: D("45684000000")}
    row = ConsensusRow("0y", "revenue", D(40989000000), None, D(41687700000), 20, D(38917000000))

    assert place([row], annual, {}) == []


def test_a_quarter_lagging_one_report_behind_is_still_placed() -> None:
    # Just after FY27 Q1 is reported, Yahoo's 0q can still be FY27 Q1 (year-ago FY26 Q1).
    quarterly = {**QUARTERLY, (2027, "Q1"): D("150000000000")}

    assert _quarters(place(_recorded(), ANNUAL, quarterly)) == {(2027, "Q1"), (2027, "Q2")}


def test_a_quarter_is_placed_when_the_stored_filings_are_one_report_behind() -> None:
    # HII: Yahoo already counts a quarter Bedrock has not fetched yet, so the year-ago quarter is
    # two before the latest stored one.
    quarterly = {k: v for k, v in QUARTERLY.items() if k != (2026, "Q4")}

    assert _quarters(place(_recorded(), ANNUAL, quarterly)) == {(2027, "Q1"), (2027, "Q2")}


def test_a_year_ago_matching_only_an_old_quarter_is_left_out() -> None:
    # FY26 Q1 is five quarters before the latest stored one: too old to be 0q's year-ago.
    quarterly = {**QUARTERLY, (2027, "Q1"): D("1"), (2027, "Q2"): D("1")}

    assert _quarters(place(_recorded(), ANNUAL, quarterly)) == set()


# --- past quarters: Yahoo's earnings history (EPS average before each report) ---------------


def _history() -> list[EpsHistoryRow]:
    frame = pd.read_csv(FIXTURES / "AAPL_earnings_history.csv", index_col="quarter")
    return history_from_frame(frame)


# AAPL's fiscal quarters end on a Saturday; Yahoo dates them by the calendar month end.
QUARTER_ENDS = {
    (2025, "Q4"): date(2025, 9, 27),
    (2026, "Q1"): date(2025, 12, 27),
    (2026, "Q2"): date(2026, 3, 28),
    (2026, "Q3"): date(2026, 6, 27),
    (2026, "Q4"): date(2026, 9, 26),
}


def test_the_history_frame_becomes_rows_by_quarter_end() -> None:
    rows = _history()

    assert rows[0] == EpsHistoryRow(date(2025, 9, 30), D("1.77112"), D("1.85"))
    assert [r.quarter_end for r in rows][-1] == date(2026, 9, 30)


def test_a_past_quarter_within_the_window_is_placed_on_its_fiscal_quarter() -> None:
    placed = place_history(_history(), QUARTER_ENDS, since=date(2025, 11, 7))

    # 2025-09-30 ended more than a year before; the rest match within ten days.
    assert placed == [
        PlacedHistory(2026, "Q1", D("2.6708"), date(2025, 12, 27)),
        PlacedHistory(2026, "Q2", D("1.94275"), date(2026, 3, 28)),
        PlacedHistory(2026, "Q3", D("1.89243"), date(2026, 6, 27)),
        PlacedHistory(2026, "Q4", D("1.9852"), date(2026, 9, 26)),
    ]


def test_a_past_quarter_without_a_stored_quarter_nearby_is_left_out() -> None:
    ends = {(2026, "Q3"): date(2026, 6, 15)}  # 15 days from Yahoo's 2026-06-30
    assert place_history(_history(), ends, since=date(2025, 11, 7)) == []


def test_a_past_quarter_without_an_estimate_is_left_out() -> None:
    rows = [EpsHistoryRow(date(2026, 6, 30), None, D("2.02"))]
    assert place_history(rows, QUARTER_ENDS, since=date(2025, 11, 7)) == []
