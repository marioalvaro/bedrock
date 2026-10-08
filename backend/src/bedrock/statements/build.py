"""Statement tables: periods as columns, canonical items as rows. Pure."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.cells import EMPTY, Cell, CellKey, Provenance, compute_cells
from bedrock.statements.periods import (
    Period,
    annual_periods,
    fiscal_calendar,
    quarterly_periods,
    ttm_windows,
)

Freq = Literal["annual", "quarterly", "ttm"]


@dataclass(frozen=True)
class Row:
    code: str
    label: str
    unit: str
    kind: str
    depth: int  # number of ancestors
    values: list[Decimal | None]
    provenance: list[Provenance | None]
    yoy: list[Decimal | None]
    common_size: list[Decimal | None]


@dataclass(frozen=True)
class BalanceCheck:
    period_key: str
    difference: Decimal | None
    ok: bool


@dataclass(frozen=True)
class StatementTable:
    statement: str
    freq: str
    periods: list[Period]
    rows: list[Row]
    balance_check: list[BalanceCheck] | None
    warnings: list[str]


RATIO_PLACES = Decimal("0.000001")
BALANCE_FLOOR = Decimal(1_000_000)
BALANCE_RELATIVE = Decimal("0.00001")


def build_statement(
    frame: pd.DataFrame, items: Sequence[CanonicalItemDef], statement: str, freq: Freq
) -> StatementTable:
    """Evaluation order: discrete periods -> formulas -> TTM -> YoY / common-size."""
    if statement == "BS" and freq == "ttm":
        raise ValueError("TTM is only defined for flow statements, not the balance sheet")
    calendar = fiscal_calendar(frame)
    cells = compute_cells(frame, items, calendar)
    if freq == "annual":
        periods = annual_periods(calendar)
    elif freq == "quarterly":
        periods = quarterly_periods(calendar)
    else:
        windows = ttm_windows(calendar)
        periods = [w.period for w in windows]
        for item in items:
            for w in windows:
                cells[(item.code, w.period.key)] = _ttm_cell(
                    item, [q.key for q in w.quarters], cells
                )

    by_code = {i.code: i for i in items}
    denominator = "total_assets" if statement == "BS" else "revenue"
    base = [cells.get((denominator, p.key), EMPTY).value for p in periods]
    rows = [
        _row(item, periods, cells, by_code, base) for item in items if item.statement == statement
    ]
    balance = _balance_check(periods, cells) if statement == "BS" else None
    return StatementTable(statement, freq, periods, rows, balance, list(calendar.warnings))


def _ttm_cell(item: CanonicalItemDef, quarter_keys: list[str], cells: dict[CellKey, Cell]) -> Cell:
    if item.kind != "flow":
        return EMPTY
    values = [cells.get((item.code, key), EMPTY).value for key in quarter_keys]
    if any(v is None for v in values):
        return EMPTY
    return Cell(sum((v for v in values if v is not None), Decimal(0)), "derived")


def _row(
    item: CanonicalItemDef,
    periods: list[Period],
    cells: dict[CellKey, Cell],
    by_code: dict[str, CanonicalItemDef],
    base: list[Decimal | None],
) -> Row:
    series = [cells.get((item.code, p.key), EMPTY) for p in periods]
    values = [c.value for c in series]
    position = {(p.fiscal_year, p.fiscal_period): i for i, p in enumerate(periods)}
    yoy: list[Decimal | None] = []
    for p, value in zip(periods, values, strict=True):
        prior_at = position.get((p.fiscal_year - 1, p.fiscal_period))
        yoy.append(_growth(value, None if prior_at is None else values[prior_at]))
    return Row(
        code=item.code,
        label=item.label,
        unit=item.unit,
        kind=item.kind,
        depth=_depth(item, by_code),
        values=values,
        provenance=[c.provenance for c in series],
        yoy=yoy,
        common_size=[_ratio(v, b) for v, b in zip(values, base, strict=True)],
    )


def _growth(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    if current is None or prior is None or prior <= 0:
        return None
    return (current / prior - 1).quantize(RATIO_PLACES)


def _ratio(value: Decimal | None, base: Decimal | None) -> Decimal | None:
    if value is None or base is None or base == 0:
        return None
    return (value / base).quantize(RATIO_PLACES)


def _balance_check(periods: list[Period], cells: dict[CellKey, Cell]) -> list[BalanceCheck]:
    checks = []
    for p in periods:
        assets, liabilities, equity = (
            cells.get((code, p.key), EMPTY).value
            for code in ("total_assets", "total_liabilities", "total_equity")
        )
        if assets is None or liabilities is None or equity is None:
            checks.append(BalanceCheck(p.key, None, False))
            continue
        difference = assets - (liabilities + equity)
        tolerance = max(BALANCE_FLOOR, BALANCE_RELATIVE * assets)
        checks.append(BalanceCheck(p.key, difference, abs(difference) <= tolerance))
    return checks


def _depth(item: CanonicalItemDef, by_code: dict[str, CanonicalItemDef]) -> int:
    depth = 0
    while item.parent is not None:
        item = by_code[item.parent]
        depth += 1
    return depth
