"""Market-based discount-rate defaults (docs/erd/valuation.md "Market defaults"): the Damodaran
implied ERP parse, the 5-year monthly beta, and the defaults they make. Pure, no network."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bedrock.valuation.inputs import resolve_inputs
from bedrock.valuation.market import (
    MIN_BETA_MONTHS,
    beta,
    market_defaults,
    month_end_closes,
    parse_damodaran_erp,
)

D = Decimal
FIXTURE = Path(__file__).parent / "fixtures" / "market" / "damodaran_home.html"


# -- Damodaran ----------------------------------------------------------------------------------


def test_the_recorded_home_page_gives_the_current_implied_erp() -> None:
    found = parse_damodaran_erp(FIXTURE.read_text())

    assert found == (date(2026, 11, 1), D("4.41"))


def test_the_first_figure_after_the_date_is_the_erp_tags_and_spaces_between() -> None:
    html = (
        "<p><strong>Implied ERP on March 1, 2027 </strong>= 4.6<span>2% (Trailing 12 month)</span>"
        "<strong>Implied ERP in previous month</strong> = 4.20%</p>"
    )
    assert parse_damodaran_erp(html) == (date(2027, 3, 1), D("4.62"))


@pytest.mark.parametrize("html", ["", "<html>no premium here</html>", "Implied ERP on soon = x%"])
def test_a_page_without_the_line_gives_nothing(html: str) -> None:
    assert parse_damodaran_erp(html) is None


# -- month-end closes and beta ------------------------------------------------------------------


def test_month_end_closes_keep_the_last_close_of_each_month() -> None:
    closes = [
        (date(2026, 1, 2), D(10)),
        (date(2026, 1, 30), D(11)),
        (date(2026, 2, 27), D(12)),
        (date(2026, 2, 3), D(99)),  # out of order: the date decides, not the position
    ]
    assert month_end_closes(closes) == {(2026, 1): D(11), (2026, 2): D(12)}


def _months(n: int, end: date = date(2026, 10, 31)) -> list[date]:
    """n month-end-ish dates, oldest first, ending in `end`'s month."""
    out: list[date] = []
    y, m = end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 28))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def _series(returns: list[Decimal]) -> list[Decimal]:
    prices = [D(100)]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return prices


def _pattern(n: int) -> list[Decimal]:
    base = [D("0.02"), D("-0.01"), D("0.03"), D("-0.02"), D("0.01"), D("0.00")]
    return [base[i % len(base)] for i in range(n)]


def test_a_stock_that_moves_twice_the_index_has_a_beta_of_two() -> None:
    index_r = _pattern(60)
    stock_r = [2 * r for r in index_r]
    # 61 month-ends make 60 returns, then the current (partial) month, which is left out.
    days = _months(62)
    index = list(zip(days, [*_series(index_r), D(1)], strict=True))
    stock = list(zip(days, [*_series(stock_r), D(1)], strict=True))

    assert beta(stock, index) == D("2.00")


def test_beta_reads_only_the_latest_sixty_months() -> None:
    # 30 older months where the stock moved 3x, then 60 recent months at 1x.
    index_r = _pattern(90)
    stock_r = [3 * r for r in index_r[:30]] + index_r[30:]
    days = _months(92)
    index = list(zip(days, [*_series(index_r), D(1)], strict=True))
    stock = list(zip(days, [*_series(stock_r), D(1)], strict=True))

    assert beta(stock, index) == D("1.00")


def test_beta_needs_three_years_of_common_months() -> None:
    index_r = _pattern(MIN_BETA_MONTHS - 1)
    days = _months(MIN_BETA_MONTHS + 1)
    index = list(zip(days, [*_series(index_r), D(1)], strict=True))
    stock = list(zip(days, [*_series(index_r), D(1)], strict=True))

    assert beta(stock, index) is None


def test_beta_of_an_index_that_never_moves_is_none() -> None:
    days = _months(62)
    index = [(d, D(100)) for d in days]
    stock = list(zip(days, [*_series(_pattern(60)), D(1)], strict=True))

    assert beta(stock, index) is None


def test_beta_uses_daily_stock_closes_at_each_month_end() -> None:
    # Daily stock closes; only each month's last one counts.
    index_r = _pattern(60)
    month_days = _months(62)
    index = list(zip(month_days, [*_series(index_r), D(1)], strict=True))
    stock_prices = [*_series([2 * r for r in index_r]), D(1)]
    stock: list[tuple[date, Decimal]] = []
    for day, price in zip(month_days, stock_prices, strict=True):
        stock.append((day - timedelta(days=10), D(5)))  # an earlier, ignored close
        stock.append((day, price))

    assert beta(stock, index) == D("2.00")


# -- defaults -----------------------------------------------------------------------------------


def test_market_figures_become_the_discount_defaults() -> None:
    defaults = market_defaults(risk_free_pct=D("4.234"), erp_pct=D("4.41"), beta=D("1.23"))

    assert defaults == {
        "risk_free_rate": D("0.0423"),
        "equity_risk_premium": D("0.0441"),
        "beta": D("1.23"),
    }


def test_a_missing_or_out_of_bounds_figure_keeps_the_catalog_default() -> None:
    assert market_defaults(risk_free_pct=None, erp_pct=None, beta=None) == {}
    # beta is bounded to [0, 5], the risk-free rate to [0, 20 %].
    assert market_defaults(risk_free_pct=D(25), erp_pct=None, beta=D(7)) == {}


def test_a_market_default_resolves_as_a_default_and_an_own_value_still_wins() -> None:
    defaults = {"risk_free_rate": D("0.0423"), "beta": D("1.23")}

    inputs = resolve_inputs({}, {"beta": "0.9"}, is_base=True, derived={}, defaults=defaults)

    assert inputs.get("risk_free_rate") == D("0.0423")
    assert inputs.source("risk_free_rate") == "default"
    assert inputs.get("beta") == D("0.9") and inputs.source("beta") == "own"
    assert inputs.get("equity_risk_premium") == D("0.05")  # no market figure: the catalog's
