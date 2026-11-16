"""The coverage ratchet (M7b S1): strict coverage of a development fixture never falls below its
floor in `tests/golden/coverage/floor.json`.

Later steps raise the floors to their new measured values (rounded down to a whole percent).
Nobody lowers a floor without a written reason in the step Log of docs/progress/CURRENT.md.
"""

import json
from decimal import ROUND_FLOOR
from pathlib import Path

import pytest

from bedrock.statements.coverage import table_coverage
from tests.statements_pipeline import STATEMENTS, run_pipeline

FLOOR = Path(__file__).parent / "golden" / "coverage" / "floor.json"
DEVELOPMENT = ("AAPL", "MSFT", "COST", "DE", "BA", "JNJ", "NFLX", "NKE", "ORCL", "WMT")
FREQS = ("annual", "quarterly")


def floors() -> dict[str, dict[str, int]]:
    return json.loads(FLOOR.read_text())  # type: ignore[no-any-return]


def measured(ticker: str) -> dict[str, int]:
    """Strict coverage per `<statement>/<freq>`, as a whole percent rounded down."""
    pipeline = run_pipeline(ticker)
    mapped = set(pipeline.mappings["canonical_code"])
    warnings = pipeline.annual["IS"].rule_warnings
    out: dict[str, int] = {}
    for freq, tables in (("annual", pipeline.annual), ("quarterly", pipeline.quarterly)):
        for statement in STATEMENTS:
            fraction = table_coverage(tables[statement], pipeline.items, mapped, warnings).fraction
            assert fraction is not None
            out[f"{statement}/{freq}"] = int((fraction * 100).to_integral_value(ROUND_FLOOR))
    return out


def test_every_development_fixture_has_a_floor_for_each_table() -> None:
    keys = {f"{s}/{f}" for s in STATEMENTS for f in FREQS}

    assert set(floors()) == set(DEVELOPMENT)
    assert all(set(by_table) == keys for by_table in floors().values())
    assert all(0 <= v <= 100 for by_table in floors().values() for v in by_table.values())


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_coverage_does_not_fall_below_its_floor(ticker: str) -> None:
    now = measured(ticker)
    below = {k: (now[k], floor) for k, floor in floors()[ticker].items() if now[k] < floor}

    assert not below, f"{ticker} fell below its coverage floor (now, floor): {below}"
