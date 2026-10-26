"""Ratio cell details over the four recorded fixtures: every explained value is the table's value,
and AAPL's ROIC shows the 10-K figures of the golden file."""

from decimal import Decimal

import pytest

from bedrock.ratios.calculator import RatioFreq, RatioInputs, compute_ratios
from bedrock.ratios.explain import Term, explain_ratio
from tests.statements_pipeline import run_pipeline

TICKERS = ["AAPL", "MSFT", "COST", "DE"]


def annual_inputs(ticker: str) -> RatioInputs:
    p = run_pipeline(ticker)
    return RatioInputs(p.annual["IS"], p.annual["CF"], p.annual["BS"])


def ttm_inputs(ticker: str) -> RatioInputs:
    from bedrock.statements.build import build_statement

    p = run_pipeline(ticker)
    income = build_statement(p.canonical, p.items, "IS", "ttm", rules=p.rules)
    cash = build_statement(p.canonical, p.items, "CF", "ttm", rules=p.rules)
    return RatioInputs(income, cash, p.quarterly["BS"], p.quarterly["IS"])


def flatten(terms: tuple[Term, ...]) -> dict[str, Term]:
    found: dict[str, Term] = {}
    for term in terms:
        found.setdefault(term.code, term)
        found.update(flatten(term.children))
    return found


@pytest.mark.parametrize("ticker", TICKERS)
@pytest.mark.parametrize("freq", ["annual", "ttm"])
def test_every_explained_value_is_the_tables_value(ticker: str, freq: RatioFreq) -> None:
    inputs = annual_inputs(ticker) if freq == "annual" else ttm_inputs(ticker)
    table = compute_ratios(inputs, freq)
    checked = 0
    for row in table.rows:
        for period, value in zip(table.periods, row.values, strict=True):
            e = explain_ratio(inputs, freq, row.code, (period.fiscal_year, period.fiscal_period))
            assert e.value == value, (ticker, freq, row.code, period.key)
            assert (e.reason is None) == (value is not None), (ticker, row.code, period.key)
            checked += 1

    assert checked > 500


def test_aapl_roic_shows_the_figures_of_the_10k() -> None:
    inputs = annual_inputs("AAPL")

    e = explain_ratio(inputs, "annual", "roic", (2025, "FY"))

    # nopat 112,280.892 / avg(invested capital 118,923, 99,304) = 109,113.5 [10-K FY2025]
    assert e.value is not None and abs(e.value - Decimal("1.029028")) < Decimal("0.0005")
    assert e.numerator.text == "nopat"
    assert abs((e.numerator.value or 0) - Decimal("112280892000")) < 1_000_000
    assert e.denominator is not None and e.denominator.average
    assert abs((e.denominator.value or 0) - Decimal("109113500000")) < 1_000_000
    current = flatten(e.denominator.terms)["invested_capital"]
    prior = flatten(e.denominator.prior_terms)["invested_capital"]
    assert abs((current.value or 0) - Decimal("118923000000")) < 1_000_000
    assert abs((prior.value or 0) - Decimal("99304000000")) < 1_000_000
    leaves = flatten(e.denominator.terms)
    assert leaves["total_equity"].value == Decimal("73733000000")
    assert leaves["cash"].value == Decimal("35934000000")
    assert flatten(e.numerator.terms)["operating_income"].value == Decimal("133050000000")
