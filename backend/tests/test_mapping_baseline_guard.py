"""The rule-engine guard (M3 S7-S9): the rules of docs/erd/data.md "Rule engine" only fill empty
cells. No non-empty annual or quarterly statement cell may change value or become empty, except the
residual cells listed here with their reason; a cell that was empty may be filled, and then it must
carry provenance `derived`, `zero_inferred` or `approximated`.

`golden/baseline/cells.json.gz` holds every non-empty annual and quarterly statement cell of the
four fixtures as the code produced them at the start of S7, after S6 (`{ticker: {freq: {statement:
{code: {period: value}}}}}`, values as decimal strings). It was generated once from that code and is
shared by S7, S8 and S9: a change outside the allowed list is a regression, not a new baseline.
"""

import gzip
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.statements_pipeline import STATEMENTS, Pipeline, run_pipeline

BASELINE = Path(__file__).parent / "golden" / "baseline" / "cells.json.gz"
TICKERS = ["AAPL", "MSFT", "COST", "DE"]

# A residual is its subtotal less the components that have a value, so it moves when a rule fills a
# sibling. `{(ticker, freq, code, period): reason}`; empty until a rule is shown to move one.
RESIDUALS_ALLOWED_TO_CHANGE: dict[tuple[str, str, str, str], str] = {}

# M7b S4: lines a combined default fills for the first time (docs/erd/data-coverage.md "Combined
# lines"): their new cells may be reported. `{(ticker, code): reason}`.
COMBINED_FILLS: dict[tuple[str, str], str] = {
    ("DE", "change_payables"): (
        "Deere's cash-flow line 'Accounts payable and accrued expenses' is the combined entry "
        "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities (10-K face, every year)"
    ),
}
# M7b S7: extension lines a company's override file maps (docs/erd/data-coverage.md "Structure
# rules"; evidence in tests/test_mapping_regressions.py::EXTENSION_LINES): their new cells may be
# reported. `{(ticker, code): reason}`.
EXTENSION_FILLS: dict[tuple[str, str], str] = {
    ("MSFT", "d_and_a"): "msft:DepreciationAmortizationAndOther, the 10-K's only D&A line",
    ("MSFT", "acquisitions"): "msft:AcquisitionsNetOfCash...OtherAssets, after the us-gaap tag",
    ("MSFT", "sales_maturities_of_investments"): (
        "msft:ProceedsFromInvestments + the us-gaap maturities line, the two face lines"
    ),
    ("DE", "ppe_net"): "de: property and equipment tag, the same face line from FY2019",
    ("DE", "long_term_debt"): "de:LongTermDebtAndFinanceLeasesNoncurrent, from FY2022",
    ("DE", "short_term_debt"): "de: short-term borrowings + securitization, before FY2020",
}

NEW_CELL_PROVENANCE = frozenset({"derived", "zero_inferred", "approximated"})
# Canonical items added after the baseline was recorded (S8a; M7b S4's scope totals): their
# reported cells are new too
NEW_ITEMS = frozenset(
    {
        "shares_issued",
        "treasury_shares",
        "long_term_debt_total",
        "long_term_debt_current",
        "operating_lease_liabilities_total",
        "operating_lease_liabilities_current",
        # M7b S5: the new canonical rows (docs/erd/data-coverage.md "New canonical rows")
        "interest_income",
        "deferred_tax_assets",
        "deferred_revenue_noncurrent",
        "deferred_tax_liabilities",
        "pension_liabilities",
        "cash_taxes_paid",
        "cash_interest_paid",
    }
)


def _residuals() -> frozenset[str]:
    from bedrock.mapping.config import load_canonical_items

    return frozenset(i.code for i in load_canonical_items() if i.residual)


RESIDUALS = _residuals()


def siblings_taken_out(residual: str) -> list[str]:
    """The lines a residual subtracts (its parent's other children): a residual cell may move by
    exactly the value of those whose cell was empty in the baseline and is filled now (a combined
    fill of S4, a row of S5, a face sum, an inferred zero or an extension line of S7), and by
    nothing else."""
    from bedrock.mapping.config import load_canonical_items

    items = load_canonical_items()
    parent = next(i.parent for i in items if i.code == residual)
    return [i.code for i in items if i.parent == parent and not i.residual and i.code != residual]


def current_cells(
    pipeline: Pipeline,
) -> dict[str, dict[str, dict[str, dict[str, tuple[str, str | None]]]]]:
    """`{freq: {statement: {code: {period: (value, provenance)}}}}` for every non-empty cell."""
    cells: dict[str, dict[str, dict[str, dict[str, tuple[str, str | None]]]]] = {}
    for freq, tables in (("annual", pipeline.annual), ("quarterly", pipeline.quarterly)):
        for statement in STATEMENTS:
            table = tables[statement]
            keys = [p.key for p in table.periods]
            for row in table.rows:
                values = {
                    key: (str(value), provenance)
                    for key, value, provenance in zip(keys, row.values, row.provenance, strict=True)
                    if value is not None
                }
                if values:
                    cells.setdefault(freq, {}).setdefault(statement, {})[row.code] = values
    return cells


def baseline() -> dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]]:
    with gzip.open(BASELINE, "rt") as handle:
        loaded = json.load(handle)
    assert isinstance(loaded, dict)
    return loaded


def same(before: str, after: str) -> bool:
    return Decimal(before) == Decimal(after)


def test_the_baseline_covers_the_four_companies_and_both_frequencies() -> None:
    recorded = baseline()

    assert sorted(recorded) == sorted(TICKERS)
    for ticker in TICKERS:
        assert sorted(recorded[ticker]) == ["annual", "quarterly"]
        assert all(set(recorded[ticker][f]) <= set(STATEMENTS) for f in recorded[ticker])
    assert (
        sum(
            len(v)
            for t in recorded.values()
            for f in t.values()
            for s in f.values()
            for v in s.values()
        )
        > 20_000
    )


@pytest.mark.parametrize("ticker", TICKERS)
def test_no_non_empty_cell_changes_or_empties(ticker: str) -> None:
    now = current_cells(run_pipeline(ticker))
    changed: list[str] = []
    for freq, statements in baseline()[ticker].items():
        for statement, codes in statements.items():
            for code, periods in codes.items():
                after = now.get(freq, {}).get(statement, {}).get(code, {})
                filled = [
                    (now.get(freq, {}).get(statement, {}).get(sibling, {}), codes.get(sibling, {}))
                    for sibling in (siblings_taken_out(code) if code in RESIDUALS else [])
                ]
                for period, before in periods.items():
                    if (ticker, freq, code, period) in RESIDUALS_ALLOWED_TO_CHANGE:
                        continue
                    taken = [
                        Decimal(f[period][0])
                        for f, was in filled
                        if period in f and period not in was
                    ]
                    if taken and period in after:
                        # residual = subtotal - ... - sibling: each fill moves it by the sibling
                        expected = Decimal(before) - sum(taken, Decimal(0))
                        if not same(str(expected), after[period][0]):
                            changed.append(
                                f"{ticker} {freq} {code} {period}: {before} -> "
                                f"{after[period][0]}, expected {expected}"
                            )
                        continue
                    if period not in after:
                        changed.append(f"{ticker} {freq} {code} {period}: {before} -> empty")
                    elif not same(before, after[period][0]):
                        changed.append(
                            f"{ticker} {freq} {code} {period}: {before} -> {after[period][0]}"
                        )

    assert changed == [], "\n".join(changed[:20])


@pytest.mark.parametrize("ticker", TICKERS)
def test_a_cell_that_was_empty_is_filled_by_a_rule_not_a_report(ticker: str) -> None:
    before = baseline()[ticker]
    wrong: list[str] = []
    for freq, statements in current_cells(run_pipeline(ticker)).items():
        for statement, codes in statements.items():
            for code, periods in codes.items():
                recorded = before.get(freq, {}).get(statement, {}).get(code, {})
                wrong += [
                    f"{ticker} {freq} {code} {period}: new cell with provenance {provenance}"
                    for period, (_, provenance) in periods.items()
                    if period not in recorded
                    and code not in NEW_ITEMS
                    and (ticker, code) not in COMBINED_FILLS
                    and (ticker, code) not in EXTENSION_FILLS
                    and provenance not in NEW_CELL_PROVENANCE
                ]

    assert wrong == [], "\n".join(wrong[:20])


def test_every_allowed_residual_change_names_a_residual_and_gives_a_reason() -> None:
    from bedrock.mapping.config import load_canonical_items

    residuals = {i.code for i in load_canonical_items() if i.residual}
    for (_, _, code, _), reason in RESIDUALS_ALLOWED_TO_CHANGE.items():
        assert code in residuals
        assert reason.strip()


def test_every_combined_fill_and_following_residual_gives_a_reason() -> None:
    from bedrock.mapping.config import (
        DEFAULT_OVERRIDES_DIR,
        load_canonical_items,
        load_overrides,
        signed_members,
    )

    by_code = {i.code: i for i in load_canonical_items()}
    for (_, code), reason in COMBINED_FILLS.items():
        assert by_code[code].covers and reason.strip()
    for (ticker, code), reason in EXTENSION_FILLS.items():
        assert reason.strip()
        overrides = load_overrides(DEFAULT_OVERRIDES_DIR, ticker, list(by_code.values()))
        assert any(
            taxonomy != "us-gaap"
            for entry in overrides[code]
            for _, taxonomy, _ in signed_members(entry)
        )  # the override maps an extension tag
