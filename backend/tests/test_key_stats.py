"""Company-list key stats (FR-WS-01) from hand-built statement tables."""

from datetime import date
from decimal import Decimal

import pytest

from bedrock.analysis.multiples import KeyStats, key_stats
from bedrock.statements.build import Row, StatementTable
from bedrock.statements.periods import Period

D = Decimal
NET_INCOME, OPERATING_INCOME, D_AND_A, REVENUE_YOY = D("50"), D("80"), D("20"), D("0.1")
CLOSE = (date(2026, 10, 7), D("100"))
SHARES = D("10")  # market cap 1,000

TTM_PERIODS = [
    Period("TTM-FY2025Q1", "TTM Q1 FY25", 2025, "Q1", date(2024, 4, 1), date(2025, 3, 31)),
    Period("TTM-FY2025Q2", "TTM Q2 FY25", 2025, "Q2", date(2024, 7, 1), date(2025, 6, 30)),
]
BS_PERIODS = [
    Period("FY2025Q1", "Q1 FY25", 2025, "Q1", date(2025, 1, 1), date(2025, 3, 31)),
    Period("FY2025Q2", "Q2 FY25", 2025, "Q2", date(2025, 4, 1), date(2025, 6, 30)),
]


def _row(code: str, values: list[Decimal | None], yoy: list[Decimal | None] | None = None) -> Row:
    n = len(values)
    return Row(
        code=code,
        label=code,
        unit="USD",
        kind="flow",
        depth=0,
        values=values,
        provenance=["derived" if v is not None else None for v in values],
        yoy=yoy if yoy is not None else [None] * n,
        common_size=[None] * n,
    )


def _table(statement: str, periods: list[Period], rows: list[Row], freq: str) -> StatementTable:
    return StatementTable(statement, freq, periods, rows, None, [])


def _tables(
    *,
    net_income: Decimal | None = NET_INCOME,
    operating_income: Decimal | None = OPERATING_INCOME,
    d_and_a: Decimal | None = D_AND_A,
    revenue_yoy: Decimal | None = REVENUE_YOY,
    debt: dict[str, Decimal | None] | None = None,
) -> tuple[dict[str, StatementTable], StatementTable]:
    # The older period carries values nobody should read: the latest period is the last column.
    balances = {
        "short_term_debt": D("30"),
        "long_term_debt": D("170"),
        "cash": D("60"),
        "short_term_investments": D("40"),
    } | (debt or {})
    ttm = {
        "IS": _table(
            "IS",
            TTM_PERIODS,
            [
                _row("revenue", [D("1"), D("500")], [None, revenue_yoy]),
                _row("net_income_common", [D("9"), net_income]),
                _row("operating_income", [D("9"), operating_income]),
            ],
            "ttm",
        ),
        "CF": _table("CF", TTM_PERIODS, [_row("d_and_a", [D("9"), d_and_a])], "ttm"),
    }
    quarterly_bs = _table(
        "BS",
        BS_PERIODS,
        [_row(code, [D("7"), value]) for code, value in balances.items()],
        "quarterly",
    )
    return ttm, quarterly_bs


def _stats(**kwargs: object) -> KeyStats:
    close = kwargs.pop("close", CLOSE)
    shares = kwargs.pop("shares", SHARES)
    ttm, bs = _tables(**kwargs)  # type: ignore[arg-type]
    return key_stats(close=close, shares=shares, ttm=ttm, quarterly_bs=bs)  # type: ignore[arg-type]


def test_price_and_its_date_are_the_latest_close() -> None:
    stats = _stats()

    assert (stats.price, stats.price_date) == (D("100"), date(2026, 10, 7))


def test_market_cap_is_price_times_shares() -> None:
    assert _stats().market_cap == D("1000")


def test_pe_is_market_cap_over_ttm_net_income_to_common() -> None:
    assert _stats().pe == D("20.00")  # 1000 / 50


def test_ev_ebitda_adds_debt_and_subtracts_cash_and_investments_over_ttm_ebitda() -> None:
    # EV = 1000 + 30 + 170 - 60 - 40 = 1100; EBITDA = 80 + 20 = 100.
    assert _stats().ev_ebitda == D("11.00")


def test_revenue_growth_is_the_ttm_revenue_yoy_of_the_latest_period() -> None:
    assert _stats().revenue_growth == D("0.1")


def test_the_balance_sheet_is_read_at_the_quarter_the_latest_ttm_ends() -> None:
    ttm, bs = _tables()
    # Same fiscal year and quarter, different key: the TTM period must match on those two.
    assert ttm["IS"].periods[-1].fiscal_period == bs.periods[-1].fiscal_period == "Q2"

    assert key_stats(close=CLOSE, shares=SHARES, ttm=ttm, quarterly_bs=bs).ev_ebitda == D("11.00")


@pytest.mark.parametrize("close", [None])
def test_without_a_price_there_is_no_price_or_market_cap_or_multiple(close: None) -> None:
    stats = _stats(close=close)

    assert (stats.price, stats.price_date, stats.market_cap) == (None, None, None)
    assert (stats.pe, stats.ev_ebitda) == (None, None)
    assert stats.revenue_growth == D("0.1")  # needs no price


def test_without_shares_there_is_no_market_cap_or_multiple() -> None:
    stats = _stats(shares=None)

    assert stats.price == D("100")
    assert (stats.market_cap, stats.pe, stats.ev_ebitda) == (None, None, None)


@pytest.mark.parametrize("net_income", [None, D("0"), D("-5")])
def test_pe_is_null_for_a_missing_zero_or_negative_net_income(net_income: Decimal | None) -> None:
    stats = _stats(net_income=net_income)

    assert stats.pe is None
    assert stats.ev_ebitda == D("11.00")  # the other stats are unaffected


@pytest.mark.parametrize(
    "overrides",
    [
        {"operating_income": None},
        {"d_and_a": None},
        {"operating_income": D("-30"), "d_and_a": D("30")},  # EBITDA 0
        {"operating_income": D("-30"), "d_and_a": D("10")},  # EBITDA < 0
    ],
)
def test_ev_ebitda_is_null_for_a_missing_input_or_non_positive_ebitda(
    overrides: dict[str, Decimal | None],
) -> None:
    assert _stats(**overrides).ev_ebitda is None


@pytest.mark.parametrize(
    "code", ["short_term_debt", "long_term_debt", "cash", "short_term_investments"]
)
def test_ev_ebitda_is_null_when_a_balance_sheet_input_is_missing(code: str) -> None:
    # A partial enterprise value would be a wrong number under a right label.
    assert _stats(debt={code: None}).ev_ebitda is None


def test_revenue_growth_is_null_when_the_yoy_is() -> None:
    assert _stats(revenue_yoy=None).revenue_growth is None


def test_every_stat_is_null_without_any_data() -> None:
    empty = key_stats(close=None, shares=None, ttm={}, quarterly_bs=None)

    assert empty == KeyStats(None, None, None, None, None, None)
