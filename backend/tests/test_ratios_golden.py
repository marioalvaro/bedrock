"""Annual ratios over the recorded companyfacts fixtures, against the 10-Ks (M2 S4, FR-ANL-01..04).

Goldens live in `tests/golden/ratios/<TICKER>.yaml` and are computed by hand from 10-K figures,
never from companyfacts (see each file's header). `annual: {PERIOD: {ratio_code: value | null}}`;
`null` means the engine must give no value. Tolerances follow the ratio's registry unit.
"""

from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from bedrock.ratios.calculator import RatioInputs, RatioTable, compute_ratios
from bedrock.ratios.caveats import load_caveats
from bedrock.ratios.registry import RATIOS, Unit
from tests.statements_pipeline import run_pipeline

GOLDEN_DIR = Path(__file__).parent / "golden" / "ratios"
TICKERS = ["AAPL", "MSFT", "COST", "DE"]
TOLERANCE: dict[Unit, Decimal] = {
    "pct": Decimal("0.0005"),
    "x": Decimal("0.05"),
    "days": Decimal("0.05"),
    "USD/shares": Decimal("0.01"),
}
UNITS: dict[str, Unit] = {ratio.code: ratio.unit for ratio in RATIOS}


def golden(ticker: str) -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load((GOLDEN_DIR / f"{ticker}.yaml").read_text())
    assert isinstance(loaded, dict)
    annual = loaded["annual"]
    assert isinstance(annual, dict)
    return annual


@cache
def annual_ratios(ticker: str) -> RatioTable:
    tables = run_pipeline(ticker).annual
    inputs = RatioInputs(income=tables["IS"], cash_flow=tables["CF"], balance=tables["BS"])
    return compute_ratios(inputs, "annual", load_caveats().get(ticker, ()))


def mismatches_against(table: RatioTable, expected: dict[str, dict[str, Any]]) -> list[str]:
    """Every golden entry the table disagrees with: a missing period, a value where the golden
    has null, no value where it has one, or a value outside the unit's tolerance."""
    keys = [p.key for p in table.periods]
    rows = {r.code: r for r in table.rows}
    found = []
    for period_key, figures in expected.items():
        if period_key not in keys:
            found.append(f"{period_key}: period missing from the ratio table")
            continue
        index = keys.index(period_key)
        for code, figure in figures.items():
            actual = rows[code].values[index]
            if figure is None:
                if actual is not None:
                    found.append(f"{period_key} {code}: golden null, engine {actual}")
            elif actual is None or abs(actual - Decimal(str(figure))) > TOLERANCE[UNITS[code]]:
                found.append(f"{period_key} {code}: 10-K {figure}, engine {actual}")
    return found


@pytest.mark.parametrize("ticker", TICKERS)
def test_ratios_match_the_10k(ticker: str) -> None:
    assert mismatches_against(annual_ratios(ticker), golden(ticker)) == []


@pytest.mark.parametrize("ticker", TICKERS)
def test_golden_files_cover_fy2020_and_the_latest_fiscal_year(ticker: str) -> None:
    latest = annual_ratios(ticker).periods[-1].key
    assert {"FY2020", latest} <= set(golden(ticker))


@pytest.mark.parametrize("ticker", TICKERS)
def test_every_golden_code_is_a_registry_ratio(ticker: str) -> None:
    codes = {code for figures in golden(ticker).values() for code in figures}
    assert codes - set(UNITS) == set()


def test_the_de_caveats_are_on_de_rows_only() -> None:
    """Each DE caveat entry's text is on the rows it names (the first entry naming a code wins, as
    in `compute_ratios`); every other DE row and every row of the other companies has none."""
    entries = load_caveats()["DE"]
    for row in annual_ratios("DE").rows:
        expected = next((c.text for c in entries if row.code in c.codes), None)
        assert row.caveat == expected, row.code
    for ticker in ("AAPL", "MSFT", "COST"):
        assert [r.code for r in annual_ratios(ticker).rows if r.caveat is not None] == []
