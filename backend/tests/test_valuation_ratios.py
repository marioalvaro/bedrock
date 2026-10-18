"""Valuation ratios (FR-ANL-07): the price input, market cap / EV metrics, the 13 ratios, nulls."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from bedrock.ratios.calculator import RatioInputs, RatioTable, compute_ratios
from bedrock.ratios.registry import METRICS, RATIOS
from tests.test_ratios_calculator import fy, table, ttm, values

VALUATION = [
    "pe",
    "earnings_yield",
    "peg",
    "pb",
    "ps",
    "p_fcf",
    "fcf_yield",
    "ev_sales",
    "ev_ebitda",
    "ev_ebit",
    "ev_fcf",
    "dividend_yield",
    "payout_ratio",
]
# FY2023 ends 2023-01-01, FY2024 ends 2024-01-01 (tests.test_ratios_calculator.fy)
PRICES = [
    (date(2022, 12, 30), Decimal(40)),
    (date(2023, 12, 29), Decimal(60)),
    (date(2024, 1, 2), Decimal(99)),  # after FY2024's end: never used
]
YEARS = [fy(2023), fy(2024)]


def inputs(**overrides: list[int | str | None]) -> RatioInputs:
    balance = {
        "shares_outstanding": [10, 10],
        "total_debt": [30, 40],
        "cash": [5, 10],
        "short_term_investments": [5, None],
        "total_equity": [50, 70],
        "equity_parent": [40, 60],
        "temporary_equity": [None, 2],
    }
    balance.update({k: v for k, v in overrides.items() if k in balance})
    return RatioInputs(
        income=table(
            "IS",
            "annual",
            YEARS,
            {
                "revenue": [100, 200],
                "operating_income": [20, 40],
                "net_income_common": [10, 20],
                "dividends_per_share": ["1", "1.2"],
            },
        ),
        cash_flow=table(
            "CF",
            "annual",
            YEARS,
            {
                "d_and_a": [5, 10],
                "free_cash_flow": [20, 24],
                "dividends_paid": [-5, -6],
            },
        ),
        balance=table("BS", "annual", YEARS, balance),
        prices=PRICES,
    )


def annual(**overrides: list[int | str | None]) -> RatioTable:
    return compute_ratios(inputs(**overrides), "annual")


D = Decimal


def test_the_valuation_ratios_are_registered_in_order_under_one_category() -> None:
    codes = [r.code for r in RATIOS if r.category == "Valuation"]
    assert codes == VALUATION
    assert {"price", "market_cap", "minority_interest", "enterprise_value"} <= {
        m.code for m in METRICS
    }


def test_multiples_use_the_close_on_or_before_each_period_end() -> None:
    t = annual()
    # FY2023: price 40 (2022-12-30), market cap 400; FY2024: price 60, market cap 600
    assert values(t, "pe") == [D(40), D(30)]
    assert values(t, "pb") == [D(10), D(10)]
    assert values(t, "ps") == [D(4), D(3)]
    assert values(t, "p_fcf") == [D(20), D(25)]


def test_enterprise_value_multiples() -> None:
    t = annual()
    # FY2023 EV = 400 + 30 + 0 (no temporary equity) + 10 (minority) - 5 - 5 = 430
    # FY2024 EV = 600 + 40 + 2 + 10 - 10 - 0 (no short-term investments) = 642
    assert values(t, "ev_sales") == [D("4.3"), D("3.21")]
    assert values(t, "ev_ebitda") == [D("430") / 25, D("12.84")]
    assert values(t, "ev_ebit") == [D("21.5"), D("16.05")]
    assert values(t, "ev_fcf") == [D("21.5"), D("26.75")]


def test_yields_payout_and_peg() -> None:
    t = annual()
    assert values(t, "earnings_yield") == [D("0.025"), D("0.033333")]
    assert values(t, "fcf_yield") == [D("0.05"), D("0.04")]
    assert values(t, "dividend_yield") == [D("0.025"), D("0.02")]
    assert values(t, "payout_ratio") == [D("0.5"), D("0.3")]
    # earnings growth FY2024 = +100 points; FY2023 has no prior year
    assert values(t, "peg") == [None, D("0.3")]


def test_a_period_before_the_first_close_has_no_valuation() -> None:
    t = compute_ratios(
        RatioInputs(
            **{**inputs().__dict__, "prices": [(date(2023, 6, 1), D(50))]},
        ),
        "annual",
    )
    assert values(t, "pe") == [None, D(25)]
    assert values(t, "dividend_yield")[0] is None


def test_no_prices_gives_null_valuation_but_keeps_other_ratios() -> None:
    t = compute_ratios(RatioInputs(**{**inputs().__dict__, "prices": []}), "annual")
    for code in [c for c in VALUATION if c != "payout_ratio"]:
        assert values(t, code) == [None, None], code
    assert values(t, "payout_ratio") == [D("0.5"), D("0.3")]  # needs no price
    assert values(t, "bvps") == [D(4), D(6)]


def test_missing_cash_or_debt_makes_enterprise_value_null_but_missing_investments_does_not() -> (
    None
):
    assert values(annual(cash=[None, 10]), "ev_sales")[0] is None
    assert values(annual(total_debt=[30, None]), "ev_sales")[1] is None
    assert values(annual(), "ev_sales")[1] == D("3.21")  # short_term_investments missing -> 0


def test_minority_interest_is_clamped_at_zero() -> None:
    # equity_parent above total_equity -> minority 0: EV FY2024 = 600 + 40 + 2 - 10 = 632
    t = annual(total_equity=[50, 55])
    assert values(t, "ev_sales")[1] == D("3.16")


def test_a_loss_makes_pe_null_but_the_yield_is_defined() -> None:
    t = compute_ratios(
        RatioInputs(
            income=table(
                "IS",
                "annual",
                YEARS,
                {
                    "revenue": [100, 200],
                    "net_income_common": [10, -20],
                    "operating_income": [20, 40],
                },
            ),
            cash_flow=inputs().cash_flow,
            balance=inputs().balance,
            prices=PRICES,
        ),
        "annual",
    )
    assert values(t, "pe") == [D(40), None]
    assert values(t, "earnings_yield")[1] == D("-0.033333")
    assert values(t, "peg") == [None, None]


def test_invariants_between_multiples_and_yields() -> None:
    t = annual()
    for pe, ey in zip(values(t, "pe"), values(t, "earnings_yield"), strict=True):
        assert pe is not None and ey is not None
        assert abs(pe * ey - 1) < D("0.0001")
    for p, y in zip(values(t, "p_fcf"), values(t, "fcf_yield"), strict=True):
        assert p is not None and y is not None
        assert abs(p * y - 1) < D("0.0001")


def test_ttm_uses_the_close_at_the_quarter_the_window_ends() -> None:
    periods = [
        replace(ttm(2024, 1), end=date(2024, 1, 1)),
        replace(ttm(2024, 2), end=date(2024, 1, 2)),
    ]
    quarters = [fy(2023)]  # placeholder: quarterly income only feeds average-kind lines
    base = inputs()
    t = compute_ratios(
        RatioInputs(
            income=table(
                "IS", "ttm", periods, {"revenue": [200, 200], "net_income_common": [20, 20]}
            ),
            cash_flow=table("CF", "ttm", periods, {"free_cash_flow": [24, 24]}),
            balance=table("BS", "quarterly", periods, {"shares_outstanding": [10, 10]}),
            quarterly_income=table("IS", "quarterly", quarters, {"revenue": [1]}),
            prices=base.prices,
        ),
        "ttm",
    )
    assert values(t, "pe") == [D(30), D("49.5")]  # closes of 2023-12-29 (60) and 2024-01-02 (99)


def test_as_of_moves_only_the_latest_periods_price_to_that_date() -> None:
    t = compute_ratios(RatioInputs(**{**inputs().__dict__, "as_of": date(2024, 1, 2)}), "annual")
    assert values(t, "pe") == [D(40), D("49.5")]  # FY2024 now reads the 2024-01-02 close (99)
