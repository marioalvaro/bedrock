"""Peer suggestions and the peer comparison engine (FR-ANL-08)."""

from decimal import Decimal

import pytest

from bedrock.analysis.comps import (
    COMPS_ROWS,
    CompanyFigures,
    CompsRow,
    CompsRowDef,
    PeerCandidate,
    compare,
    suggest_peers,
)
from bedrock.ratios.registry import RATIOS

D = Decimal


def cand(
    ticker: str, sic: str | None, cap: int | None = None, in_set: bool = False
) -> PeerCandidate:
    return PeerCandidate(
        ticker=ticker,
        name=f"{ticker} Inc.",
        sic=sic,
        market_cap=None if cap is None else D(cap),
        in_set=in_set,
    )


# --- suggest_peers ---------------------------------------------------------------------------


def test_the_match_level_is_the_number_of_leading_sic_digits_shared() -> None:
    target = cand("T", "3571")
    found = suggest_peers(
        target,
        [cand("A", "3571"), cand("B", "3579"), cand("C", "3599"), cand("D", "3500")],
    )
    assert [(s.ticker, s.match) for s in found] == [
        ("A", "industry"),
        ("B", "industry group"),
        ("C", "major group"),
        ("D", "major group"),
    ]


def test_a_company_with_no_matching_major_group_or_no_sic_is_not_suggested() -> None:
    found = suggest_peers(cand("T", "3571"), [cand("A", "7372"), cand("B", None), cand("C", "")])
    assert found == []


def test_a_target_without_a_sic_gets_no_suggestions() -> None:
    assert suggest_peers(cand("T", None), [cand("A", "3571")]) == []


def test_a_weaker_match_never_outranks_a_stronger_one_whatever_the_market_cap() -> None:
    target = cand("T", "3571", cap=100)
    found = suggest_peers(
        target, [cand("FAR", "3571", cap=1_000_000), cand("NEAR", "3599", cap=100)]
    )
    assert [s.ticker for s in found] == ["FAR", "NEAR"]


def test_equal_matches_are_ordered_by_market_cap_closeness_on_a_log_scale() -> None:
    target = cand("T", "3571", cap=100)
    # |ln(c/t)|: 200 -> 0.693, 40 -> 0.916, 90 -> 0.105; a ratio, not a difference
    found = suggest_peers(
        target,
        [cand("B", "3571", cap=200), cand("C", "3571", cap=40), cand("A", "3571", cap=90)],
    )
    assert [s.ticker for s in found] == ["A", "B", "C"]


def test_a_missing_market_cap_comes_last_then_ticker_breaks_ties() -> None:
    target = cand("T", "3571", cap=100)
    found = suggest_peers(
        target,
        [
            cand("Z", "3571", cap=100),
            cand("B", "3571", cap=None),
            cand("A", "3571", cap=None),
            cand("Y", "3571", cap=100),
        ],
    )
    assert [s.ticker for s in found] == ["Y", "Z", "A", "B"]


def test_without_a_target_market_cap_candidates_fall_back_to_ticker_order() -> None:
    found = suggest_peers(cand("T", "3571"), [cand("B", "3571", cap=5), cand("A", "3571", cap=900)])
    assert [s.ticker for s in found] == ["A", "B"]


def test_a_non_positive_market_cap_counts_as_missing() -> None:
    target = cand("T", "3571", cap=100)
    found = suggest_peers(target, [cand("A", "3571", cap=0), cand("B", "3571", cap=1)])
    assert [s.ticker for s in found] == ["B", "A"]


def test_a_suggestion_carries_its_fields_and_in_set() -> None:
    found = suggest_peers(cand("T", "3571"), [cand("A", "3523", cap=7, in_set=True)])
    assert len(found) == 1
    s = found[0]
    assert (s.ticker, s.name, s.sic, s.match, s.market_cap, s.in_set) == (
        "A",
        "A Inc.",
        "3523",
        "major group",
        D(7),
        True,
    )


# --- compare ---------------------------------------------------------------------------------

PE = CompsRowDef("pe", "P/E", "Valuation", "x")
MARGIN = CompsRowDef("net_margin", "Net margin", "Profitability", "pct")
CCC = CompsRowDef("ccc", "Cash conversion cycle", "Efficiency", "days")


def fig(
    ticker: str, caveats: dict[str, str] | None = None, **values: int | str | None
) -> CompanyFigures:
    return CompanyFigures(
        ticker=ticker,
        values={k: None if v is None else D(v) for k, v in values.items()},
        caveats=caveats or {},
    )


def one(
    rows: tuple[CompsRowDef, ...], target: CompanyFigures, *peers: CompanyFigures
) -> list[CompsRow]:
    return compare(target, list(peers), rows).rows


def test_the_median_of_an_odd_number_of_peers_is_the_middle_value() -> None:
    (row,) = one((PE,), fig("T", pe=20), fig("A", pe=30), fig("B", pe=10), fig("C", pe=15))
    assert (row.peer_median, row.peer_min, row.peer_max, row.n) == (D(15), D(10), D(30), 3)


def test_the_median_of_an_even_number_of_peers_is_the_mean_of_the_middle_two() -> None:
    (row,) = one(
        (PE,), fig("T", pe=20), fig("A", pe=10), fig("B", pe=15), fig("C", pe=11), fig("D", pe=40)
    )
    assert row.peer_median == D("13")
    assert row.n == 4


def test_peer_values_are_listed_in_the_order_given_with_nulls_kept() -> None:
    (row,) = one((PE,), fig("T", pe=20), fig("A", pe=30), fig("B", pe=None), fig("C"))
    assert row.peers == [D(30), None, None]
    assert row.n == 1


def test_x_values_at_or_below_zero_are_left_out_of_the_statistics_but_still_listed() -> None:
    (row,) = one((PE,), fig("T", pe=20), fig("A", pe=-5), fig("B", pe=0), fig("C", pe=8))
    assert row.peers == [D(-5), D(0), D(8)]
    assert (row.peer_median, row.peer_min, row.peer_max, row.n) == (D(8), D(8), D(8), 1)


def test_pct_negatives_are_kept() -> None:
    (row,) = one(
        (MARGIN,),
        fig("T", net_margin="0.10"),
        fig("A", net_margin="-0.20"),
        fig("B", net_margin="0.30"),
    )
    assert (row.peer_min, row.peer_max, row.peer_median, row.n) == (
        D("-0.20"),
        D("0.30"),
        D("0.05"),
        2,
    )


def test_days_negatives_are_kept() -> None:
    (row,) = one((CCC,), fig("T", ccc=-10), fig("A", ccc=-20), fig("B", ccc=-40))
    assert (row.peer_median, row.n) == (D(-30), 2)


def test_no_usable_peer_value_gives_null_statistics() -> None:
    (row,) = one((PE,), fig("T", pe=20), fig("A", pe=None), fig("B", pe=-3))
    assert (row.peer_median, row.peer_min, row.peer_max, row.n) == (None, None, None, 0)
    assert row.target_vs_median is None


def test_a_single_peer_is_its_own_median() -> None:
    (row,) = one((PE,), fig("T", pe=20), fig("A", pe=10))
    assert (row.peer_median, row.peer_min, row.peer_max, row.n) == (D(10), D(10), D(10), 1)


def test_no_peers_at_all_gives_null_statistics_and_keeps_the_target() -> None:
    (row,) = compare(fig("T", pe=20), [], (PE,)).rows
    assert (row.target, row.peers, row.peer_median, row.n) == (D(20), [], None, 0)


def test_vs_median_is_a_ratio_for_x_rows() -> None:
    (row,) = one((PE,), fig("T", pe=30), fig("A", pe=20))
    assert row.target_vs_median == D("0.5")


def test_vs_median_is_a_ratio_for_days_rows() -> None:
    (row,) = one((CCC,), fig("T", ccc=30), fig("A", ccc=60))
    assert row.target_vs_median == D("-0.5")


def test_vs_median_is_a_difference_for_pct_rows_and_may_cross_zero() -> None:
    (row,) = one((MARGIN,), fig("T", net_margin="-0.02"), fig("A", net_margin="0.03"))
    assert row.target_vs_median == D("-0.05")


def test_vs_median_is_null_when_the_median_is_not_positive_on_a_days_row() -> None:
    (row,) = one((CCC,), fig("T", ccc=30), fig("A", ccc=-5))
    assert row.target_vs_median is None


def test_vs_median_is_null_for_a_null_target() -> None:
    (row,) = one((PE,), fig("T", pe=None), fig("A", pe=20))
    assert (row.target, row.target_vs_median, row.target_rank) == (None, None, None)


def test_rank_is_one_plus_the_peers_strictly_above_the_target() -> None:
    (row,) = one((PE,), fig("T", pe=20), fig("A", pe=30), fig("B", pe=10), fig("C", pe=25))
    assert row.target_rank == 3


def test_rank_one_is_the_highest_and_ties_share_a_rank() -> None:
    (top,) = one((PE,), fig("T", pe=40), fig("A", pe=30), fig("B", pe=10))
    (tied,) = one((PE,), fig("T", pe=30), fig("A", pe=30), fig("B", pe=10))
    assert (top.target_rank, tied.target_rank) == (1, 1)


def test_results_are_quantized_to_six_places() -> None:
    (row,) = one(
        (MARGIN,),
        fig("T", net_margin="0.12345678"),
        fig("A", net_margin="0.11111111"),
        fig("B", net_margin="0.2"),
    )
    assert row.target == D("0.123457")
    assert row.peers == [D("0.111111"), D("0.200000")]
    assert row.peer_median == D("0.155556")
    assert row.target_vs_median == D("-0.032099")


def test_a_cell_caveat_is_carried_with_its_ticker_target_first() -> None:
    (row,) = one(
        (PE,),
        fig("T", pe=20, caveats={"pe": "t note"}),
        fig("A", pe=10),
        fig("B", pe=10, caveats={"pe": "b note", "ev_sales": "other row"}),
    )
    assert [(c.ticker, c.text) for c in row.caveats] == [("T", "t note"), ("B", "b note")]


def test_rows_keep_the_given_order_and_label_category_and_unit() -> None:
    rows = one((MARGIN, PE), fig("T"))
    assert [(r.code, r.label, r.category, r.unit) for r in rows] == [
        ("net_margin", "Net margin", "Profitability", "pct"),
        ("pe", "P/E", "Valuation", "x"),
    ]


def test_the_shipped_rows_follow_the_erd_order_and_registry_labels() -> None:
    assert [(r.code, r.category) for r in COMPS_ROWS] == [
        *[
            (c, "Valuation")
            for c in "pe ev_ebitda ev_sales ev_ebit p_fcf pb ps earnings_yield fcf_yield "
            "dividend_yield".split()
        ],
        *[
            (c, "Profitability")
            for c in "gross_margin operating_margin ebitda_margin net_margin fcf_margin roe "
            "roic".split()
        ],
        *[(c, "Solvency") for c in "net_debt_to_ebitda debt_to_equity interest_coverage".split()],
        *[(c, "Efficiency") for c in "asset_turnover ccc".split()],
        ("revenue_growth", "Growth"),
    ]
    registry = {r.code: r for r in RATIOS}
    for row in COMPS_ROWS:
        if row.code != "revenue_growth":
            assert (row.label, row.unit) == (registry[row.code].label, registry[row.code].unit)
    growth = COMPS_ROWS[-1]
    assert (growth.label, growth.unit) == ("Revenue growth (TTM YoY)", "pct")


def test_compare_uses_the_shipped_rows_by_default() -> None:
    table = compare(fig("T", pe=10), [fig("A", pe=20)])
    assert [r.code for r in table.rows] == [r.code for r in COMPS_ROWS]
    assert table.rows[0].peer_median == D(20)


@pytest.mark.parametrize("code", [r.code for r in COMPS_ROWS])
def test_a_code_missing_from_every_company_gives_a_null_row(code: str) -> None:
    row = next(r for r in compare(fig("T"), [fig("A")]).rows if r.code == code)
    assert (row.target, row.peers, row.n, row.target_rank) == (None, [None], 0, None)


# --- review additions: untested decisions and boundaries -------------------------------------


def test_one_shared_sic_digit_is_no_match() -> None:
    assert suggest_peers(cand("T", "3571"), [cand("A", "3999")]) == []


def test_rank_is_one_when_no_peer_value_is_used() -> None:
    (row,) = one((PE,), fig("T", pe=20), fig("A", pe=None), fig("B", pe=-3))
    assert (row.n, row.target_rank) == (0, 1)


def test_rank_ignores_x_values_left_out_of_the_statistics() -> None:
    (row,) = one((PE,), fig("T", pe=-5), fig("A", pe=-1), fig("B", pe=10))
    assert row.target_rank == 2


def test_vs_median_is_null_when_the_days_median_is_zero() -> None:
    (row,) = one((CCC,), fig("T", ccc=30), fig("A", ccc=0))
    assert row.target_vs_median is None


def test_vs_median_on_a_pct_row_is_a_difference_even_with_a_negative_median() -> None:
    (row,) = one((MARGIN,), fig("T", net_margin="0.01"), fig("A", net_margin="-0.04"))
    assert row.target_vs_median == D("0.05")
