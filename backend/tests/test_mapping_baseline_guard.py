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

NEW_CELL_PROVENANCE = frozenset({"derived", "zero_inferred", "approximated"})


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
                for period, before in periods.items():
                    if (ticker, freq, code, period) in RESIDUALS_ALLOWED_TO_CHANGE:
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
                    if period not in recorded and provenance not in NEW_CELL_PROVENANCE
                ]

    assert wrong == [], "\n".join(wrong[:20])


def test_every_allowed_residual_change_names_a_residual_and_gives_a_reason() -> None:
    from bedrock.mapping.config import load_canonical_items

    residuals = {i.code for i in load_canonical_items() if i.residual}
    for (_, _, code, _), reason in RESIDUALS_ALLOWED_TO_CHANGE.items():
        assert code in residuals
        assert reason.strip()
