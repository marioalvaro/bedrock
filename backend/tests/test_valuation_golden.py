"""Valuation ratios at a fixed price against the 10-K figures (FR-ANL-07, M2 S9).

`tests/golden/ratios/<TICKER>.yaml` has a `valuation:` block next to `annual:`. Each period gives an
assumed `price` (an input, not a 10-K figure: the close at the fiscal year end) and the ratios
computed by hand from the 10-K figures cited in the comments. A `null` asserts a structural empty.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import yaml

from bedrock.ratios.calculator import RatioInputs, RatioTable, compute_ratios
from bedrock.ratios.caveats import load_caveats
from bedrock.ratios.registry import RATIOS
from tests.statements_pipeline import run_pipeline
from tests.test_ratios_golden import GOLDEN_DIR, TICKERS, mismatches_against

VALUATION = {r.code for r in RATIOS if r.category == "Valuation"}


def valuation_golden(ticker: str) -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load((GOLDEN_DIR / f"{ticker}.yaml").read_text())
    block = loaded["valuation"]
    assert isinstance(block, dict)
    return block


def priced_table(ticker: str) -> RatioTable:
    tables = run_pipeline(ticker).annual
    ends = {p.key: p.end for p in tables["IS"].periods}
    prices: list[tuple[date, Decimal]] = [
        (ends[key], Decimal(str(figures["price"])))
        for key, figures in valuation_golden(ticker).items()
    ]
    inputs = RatioInputs(
        income=tables["IS"], cash_flow=tables["CF"], balance=tables["BS"], prices=prices
    )
    return compute_ratios(inputs, "annual", load_caveats().get(ticker, ()))


@pytest.mark.parametrize("ticker", TICKERS)
def test_valuation_ratios_match_the_10k_at_the_assumed_price(ticker: str) -> None:
    expected = {
        key: {c: v for c, v in figures.items() if c != "price"}
        for key, figures in valuation_golden(ticker).items()
    }
    assert mismatches_against(priced_table(ticker), expected) == []


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_valuation_golden_code_is_a_valuation_ratio(ticker: str) -> None:
    codes = {c for figures in valuation_golden(ticker).values() for c in figures} - {"price"}
    assert codes <= VALUATION and codes


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_multiples_and_yields_are_each_others_inverse(ticker: str) -> None:
    rows = {r.code: r.values for r in priced_table(ticker).rows}
    pairs = [("pe", "earnings_yield"), ("p_fcf", "fcf_yield")]
    checked = 0
    for multiple, yield_ in pairs:
        for m, y in zip(rows[multiple], rows[yield_], strict=True):
            if m is not None and y is not None:
                assert abs(m * y - 1) < Decimal("0.0001"), (ticker, multiple)
                checked += 1
    assert checked > 0
