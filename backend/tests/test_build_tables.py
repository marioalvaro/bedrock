"""Building several statement tables from one solve of the company's cells (NFR-02): the same
tables as building each on its own, for the four recorded companies, reported and normalized."""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from bedrock.statements import build
from bedrock.statements.build import build_statement, build_tables

from .statements_pipeline import run_pipeline

# TTM first: it writes extra cells, which must not leak into the tables built after it.
WANTED = [
    ("IS", "ttm"),
    ("CF", "ttm"),
    ("IS", "annual"),
    ("BS", "annual"),
    ("CF", "annual"),
    ("IS", "quarterly"),
    ("BS", "quarterly"),
    ("CF", "quarterly"),
]


@dataclass(frozen=True)
class Adj:
    id: int
    canonical_code: str
    fiscal_year: int
    fiscal_period: str
    amount: Decimal


# A one-off charge added back to operating income in FY2023 and in its Q2.
ADJUSTMENTS = [
    Adj(1, "other_operating_expenses", 2023, "FY", Decimal("-1500000000")),
    Adj(2, "other_operating_expenses", 2023, "Q2", Decimal("-1500000000")),
]


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "COST", "DE"])
@pytest.mark.parametrize("adjustments", [[], ADJUSTMENTS], ids=["reported", "normalized"])
def test_every_table_equals_the_table_built_on_its_own(ticker: str, adjustments: list[Adj]) -> None:
    p = run_pipeline(ticker)

    tables = build_tables(
        p.canonical,
        p.items,
        WANTED,
        "parent",
        adjustments,
        p.rules,  # type: ignore[arg-type]
    )

    assert list(tables) == WANTED
    for statement, freq in WANTED:
        alone = build_statement(
            p.canonical,
            p.items,
            statement,
            freq,
            "parent",
            adjustments,
            p.rules,  # type: ignore[arg-type]
        )
        assert tables[(statement, freq)] == alone, (statement, freq)


def test_the_cells_are_solved_once_for_every_table(monkeypatch: pytest.MonkeyPatch) -> None:
    p = run_pipeline("AAPL")
    calls: list[int] = []
    real = build.solve_cells

    def counting(*args, **kwargs):  # type: ignore[no-untyped-def]  # a spy on the real solver
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(build, "solve_cells", counting)

    build_tables(p.canonical, p.items, WANTED, rules=p.rules)  # type: ignore[arg-type]

    assert len(calls) == 1


def test_a_ttm_balance_sheet_is_refused() -> None:
    p = run_pipeline("AAPL")

    with pytest.raises(ValueError, match="TTM"):
        build_tables(p.canonical, p.items, [("IS", "annual"), ("BS", "ttm")], rules=p.rules)
