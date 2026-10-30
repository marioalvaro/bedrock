"""Synthetic average-item frames for the Q4 / TTM / normalized EPS tests: share counts, EPS and
the net income they divide, for FictCo-like years of any quarter lengths. No network, no DB."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.cells import Cell, solve_cells
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.rules import Rules, RuleWarning
from bedrock.statements.splits import split_adjust
from tests.engine_data import Row, fact, facts, item, mappings

M = 1_000_000

ITEMS = [
    item("revenue"),
    item("net_income_common"),
    item("shares_basic", kind="average", unit="shares"),
    item("shares_diluted", kind="average", unit="shares"),
    item("eps_basic", kind="average", unit="USD/shares"),
    item("eps_diluted", kind="average", unit="USD/shares"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("net_income_common", "NetIncomeLoss", 0),
    ("shares_basic", "WeightedAverageNumberOfSharesOutstandingBasic", 0),
    ("shares_diluted", "WeightedAverageNumberOfDilutedSharesOutstanding", 0),
    ("eps_basic", "EarningsPerShareBasic", 0),
    ("eps_diluted", "EarningsPerShareDiluted", 0),
)


@dataclass(frozen=True)
class Year:
    """One fiscal year: its start, the Q1..Q3 ends and the year end (quarter lengths are free, so
    a 12/12/12/16-week calendar is a Year too)."""

    start: date
    q_ends: tuple[date, date, date]
    end: date

    def days(self) -> list[int]:
        """Q1..Q4 lengths, both ends counted."""
        edges = [self.start - timedelta(days=1), *self.q_ends, self.end]
        return [(b - a).days for a, b in zip(edges, edges[1:], strict=False)]


JUNE = Year(
    date(2022, 7, 1), (date(2022, 9, 30), date(2022, 12, 31), date(2023, 3, 31)), date(2023, 6, 30)
)
# Costco-like: three 12-week quarters and one of 16 weeks
WEEKS = Year(
    date(2022, 9, 5), (date(2022, 11, 27), date(2023, 2, 19), date(2023, 5, 14)), date(2023, 9, 3)
)


def flow(
    concept: str, year: Year, fy: int | str, quarters: Sequence[int | str | None]
) -> list[Row]:
    """A flow as 10-Ks and 10-Qs report it: the 12-month value, the discrete Q1..Q3 and the
    year-to-date values of Q2 and Q3 (which the calendar reads the quarter ends from)."""
    rows = [fact(concept, year.start, year.end, fy, accession="K")]
    running = 0
    previous = year.start - timedelta(days=1)
    for n, (q_end, value) in enumerate(zip(year.q_ends, quarters, strict=False), start=1):
        if value is None:
            previous = q_end
            continue
        rows.append(
            fact(
                concept, previous + timedelta(days=1), q_end, value, accession=f"Q{n}", form="10-Q"
            )
        )
        running += Decimal(str(value))
        if n > 1:
            rows.append(fact(concept, year.start, q_end, running, accession=f"Q{n}", form="10-Q"))
        previous = q_end
    return rows


def average(
    concept: str, year: Year, fy: int | str, quarters: Sequence[int | str | None], unit: str
) -> list[Row]:
    """An average as reported: the year and the discrete Q1..Q3, nothing for Q4 or year-to-date."""
    rows = [fact(concept, year.start, year.end, fy, accession="K", unit=unit)]
    previous = year.start - timedelta(days=1)
    for n, (q_end, value) in enumerate(zip(year.q_ends, quarters, strict=False), start=1):
        if value is not None:
            rows.append(
                fact(
                    concept,
                    previous + timedelta(days=1),
                    q_end,
                    value,
                    accession=f"Q{n}",
                    form="10-Q",
                    unit=unit,
                )
            )
        previous = q_end
    return rows


def shares(code: str, year: Year, fy: int, quarters: Sequence[int | None]) -> list[Row]:
    concept = {
        "shares_basic": "WeightedAverageNumberOfSharesOutstandingBasic",
        "shares_diluted": "WeightedAverageNumberOfDilutedSharesOutstanding",
    }[code]
    return average(concept, year, fy, quarters, "shares")


def eps(code: str, year: Year, fy: str, quarters: Sequence[str | None]) -> list[Row]:
    concept = {"eps_basic": "EarningsPerShareBasic", "eps_diluted": "EarningsPerShareDiluted"}[code]
    return average(concept, year, fy, quarters, "USD/shares")


def solve(
    rows: list[Row], splits: Sequence[object] = ()
) -> tuple[dict[tuple[str, str], Cell], list[RuleWarning]]:
    canonical: pd.DataFrame = map_facts(select_vintage(facts(rows)), MAPS, ITEMS)  # type: ignore[arg-type]
    if splits:
        canonical = split_adjust(canonical, splits)  # type: ignore[arg-type]
    result = solve_cells(canonical, ITEMS, fiscal_calendar(canonical), Rules())
    return result.cells, list(result.warnings)


def income(
    year: Year, fy: int = 400, quarters: Sequence[int | None] = (100, 100, 100)
) -> list[Row]:
    """Net income common: gives the calendar, and Q4 earnings as FY less Q1..Q3."""
    return flow("NetIncomeLoss", year, fy * M, [q * M if q is not None else None for q in quarters])


def q4(cells: dict[tuple[str, str], Cell], code: str) -> Cell:
    return cells[(code, "FY2023Q4")]
