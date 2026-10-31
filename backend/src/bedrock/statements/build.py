"""Statement tables: periods as columns, canonical items as rows. Pure."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef, is_adjustable
from bedrock.statements.cell_types import EMPTY, Cell, CellKey, Provenance, RuleWarning
from bedrock.statements.cells import solve_cells
from bedrock.statements.imports import company_calendar
from bedrock.statements.normalize import AdjustmentLike, apply_adjustments
from bedrock.statements.periods import (
    Period,
    annual_periods,
    quarterly_periods,
    ttm_windows,
)
from bedrock.statements.rules import BALANCE_FLOOR, BALANCE_RELATIVE, NO_RULES, Rules

Freq = Literal["annual", "quarterly", "ttm"]
CommonSizeBase = Literal["total", "parent"]


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
    common_size_base: str | None = None  # label of the row `common_size` divides by
    adjustable: bool = False  # a normalization adjustment may target this line
    custom: bool = False  # a custom line, or the `Other` row of a custom breakdown
    parent: str | None = None  # the line a custom row sits under; None for a canonical line


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
    # rules whose result a guard refused (the same list on every table of one company)
    rule_warnings: tuple[RuleWarning, ...] = ()


OTHER_PREFIX = "other:"
RATIO_PLACES = Decimal("0.000001")
TTM_EPS_CODES = frozenset({"eps_basic", "eps_diluted"})


def build_statement(
    frame: pd.DataFrame,
    items: Sequence[CanonicalItemDef],
    statement: str,
    freq: Freq,
    common_size_base: CommonSizeBase = "total",
    adjustments: Sequence[AdjustmentLike] = (),
    rules: Rules = NO_RULES,
) -> StatementTable:
    """Evaluation order: discrete periods -> formulas and rules (`solve_cells`) -> adjustments
    (normalized basis) -> TTM -> YoY / common-size.

    Common-size divides every row by one base row of the same period: `total` is revenue (IS, CF)
    or total assets (BS); `parent` is the row's parent, and a row without one uses the total."""
    if statement == "BS" and freq == "ttm":
        raise ValueError("TTM is only defined for flow statements, not the balance sheet")
    calendar = company_calendar(frame, rules.imported)
    solved = solve_cells(frame, items, calendar, rules)
    cells = solved.cells
    if adjustments:
        cells, _ = apply_adjustments(cells, items, adjustments, calendar, rules.identities)
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
    total = by_code.get("total_assets" if statement == "BS" else "revenue")
    shown = [i for i in items if i.statement == statement]
    others = _other_items(shown)
    for other in others.values():
        for p in periods:
            cells[(other.code, p.key)] = _other_cell(other, shown, p.key, cells)
        by_code[other.code] = other
    rows = _with_others(
        shown,
        others,
        lambda item: _row(
            item, periods, cells, by_code, _base_item(item, by_code, total, common_size_base)
        ),
    )
    balance = _balance_check(periods, cells) if statement == "BS" else None
    return StatementTable(
        statement, freq, periods, rows, balance, list(calendar.warnings), solved.warnings
    )


def _other_items(shown: Sequence[CanonicalItemDef]) -> dict[str, CanonicalItemDef]:
    """The `Other <label>` row of every line that has custom lines under it, by the parent's code
    (`other:<parent code>`): the part of the line its breakdown does not name."""
    parents = {i.parent for i in shown if i.custom}
    return {
        item.code: CanonicalItemDef(
            f"{OTHER_PREFIX}{item.code}",
            item.statement,
            f"Other {item.label}",
            item.kind,
            item.unit,
            item.sign,
            item.code,
            (),
            None,
            False,
            (),
            custom=True,
        )
        for item in shown
        if item.code in parents
    }


def _other_cell(
    other: CanonicalItemDef, shown: Sequence[CanonicalItemDef], key: str, cells: dict[CellKey, Cell]
) -> Cell:
    """The parent less the custom lines under it that have a value; empty when the parent or all
    of them are."""
    parent = cells.get((other.parent or "", key), EMPTY).value
    parts = [
        v
        for i in shown
        if i.custom and i.parent == other.parent
        if (v := cells.get((i.code, key), EMPTY).value) is not None
    ]
    if parent is None or not parts:
        return EMPTY
    return Cell(parent - sum(parts, Decimal(0)), "derived")


def _with_others(
    shown: Sequence[CanonicalItemDef],
    others: dict[str, CanonicalItemDef],
    make: Callable[[CanonicalItemDef], Row],
) -> list[Row]:
    """The rows of `shown` in order, each `Other` row after the last line of its breakdown."""
    by_code = {i.code: i for i in shown}

    def under(item: CanonicalItemDef, ancestor: str) -> bool:
        while item.parent is not None:
            if item.parent == ancestor:
                return True
            parent = by_code.get(item.parent)
            if parent is None:
                return False
            item = parent
        return False

    rows: list[Row] = []
    open_breakdowns: list[str] = []
    for item in shown:
        while open_breakdowns and not under(item, open_breakdowns[-1]):
            rows.append(make(others[open_breakdowns.pop()]))
        rows.append(make(item))
        if item.code in others:
            open_breakdowns.append(item.code)
    while open_breakdowns:
        rows.append(make(others[open_breakdowns.pop()]))
    return rows


def extend_table(
    table: StatementTable,
    periods: Sequence[Period],
    values: Mapping[CellKey, Decimal | None],
) -> StatementTable:
    """`table` with forecast `periods` appended (docs/erd/forecasting.md "API" → forecast). Each
    row takes its value from `values` (null where absent; a non-null value has provenance
    `forecast`); YoY of a new column runs against the same period one year earlier among all the
    columns; common size divides by the period's total in `values` (total assets for BS, else
    revenue); a balance sheet gets the check of each new column. The existing columns are kept
    as built."""
    added = list(periods)
    combined = table.periods + added
    position = {(p.fiscal_year, p.fiscal_period): i for i, p in enumerate(combined)}
    total = "total_assets" if table.statement == "BS" else "revenue"
    rows = []
    for row in table.rows:
        new = [values.get((row.code, p.key)) for p in added]
        all_values = row.values + new
        yoy = []
        for p, value in zip(added, new, strict=True):
            prior_at = position.get((p.fiscal_year - 1, p.fiscal_period))
            yoy.append(growth(value, None if prior_at is None else all_values[prior_at]))
        rows.append(
            replace(
                row,
                values=all_values,
                provenance=row.provenance + ["forecast" if v is not None else None for v in new],
                yoy=row.yoy + yoy,
                common_size=row.common_size
                + [_ratio(v, values.get((total, p.key))) for v, p in zip(new, added, strict=True)],
            )
        )
    balance = None
    if table.balance_check is not None:
        cells = {key: Cell(v, "forecast") for key, v in values.items()}
        balance = table.balance_check + _balance_check(added, cells)
    return replace(table, periods=combined, rows=rows, balance_check=balance)


def _ttm_cell(item: CanonicalItemDef, quarter_keys: list[str], cells: dict[CellKey, Cell]) -> Cell:
    """The sum of the last four discrete quarters: flows, and the two EPS lines (market convention:
    the sum of the quarterly EPS). Other average items have no TTM."""
    if item.kind != "flow" and item.code not in TTM_EPS_CODES:
        return EMPTY
    quarters = [cells.get((item.code, key), EMPTY) for key in quarter_keys]
    if any(q.value is None for q in quarters):
        return EMPTY
    provenance = {q.provenance for q in quarters}
    return Cell(
        sum((q.value for q in quarters if q.value is not None), Decimal(0)),
        "zero_inferred"
        if provenance == {"zero_inferred"}
        else "normalized"
        if "normalized" in provenance
        else "approximated"
        if "approximated" in provenance
        else "derived",
    )


def _row(
    item: CanonicalItemDef,
    periods: list[Period],
    cells: dict[CellKey, Cell],
    by_code: dict[str, CanonicalItemDef],
    base: CanonicalItemDef | None,
) -> Row:
    series = [cells.get((item.code, p.key), EMPTY) for p in periods]
    base_values = [
        EMPTY.value if base is None else cells.get((base.code, p.key), EMPTY).value for p in periods
    ]
    values = [c.value for c in series]
    position = {(p.fiscal_year, p.fiscal_period): i for i, p in enumerate(periods)}
    yoy: list[Decimal | None] = []
    for p, value in zip(periods, values, strict=True):
        prior_at = position.get((p.fiscal_year - 1, p.fiscal_period))
        yoy.append(growth(value, None if prior_at is None else values[prior_at]))
    return Row(
        code=item.code,
        label=item.label,
        unit=item.unit,
        kind=item.kind,
        depth=_depth(item, by_code),
        values=values,
        provenance=[c.provenance for c in series],
        yoy=yoy,
        common_size=[_ratio(v, b) for v, b in zip(values, base_values, strict=True)],
        common_size_base=None if base is None else base.label,
        adjustable=is_adjustable(item),
        custom=item.custom,
        parent=item.parent if item.custom else None,
    )


def _base_item(
    item: CanonicalItemDef,
    by_code: dict[str, CanonicalItemDef],
    total: CanonicalItemDef | None,
    mode: CommonSizeBase,
) -> CanonicalItemDef | None:
    if mode == "parent" and item.parent is not None:
        return by_code[item.parent]
    return total


def growth(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    """The statement YoY rule: current / prior - 1, quantized to RATIO_PLACES; None unless both
    exist and prior > 0."""
    if current is None or prior is None or prior <= 0:
        return None
    return (current / prior - 1).quantize(RATIO_PLACES)


def _ratio(value: Decimal | None, base: Decimal | None) -> Decimal | None:
    if value is None or base is None or base == 0:
        return None
    return (value / base).quantize(RATIO_PLACES)


def _balance_check(periods: list[Period], cells: Mapping[CellKey, Cell]) -> list[BalanceCheck]:
    checks = []
    for p in periods:
        assets, liabilities, equity = (
            cells.get((code, p.key), EMPTY).value
            for code in ("total_assets", "total_liabilities", "total_equity")
        )
        if assets is None or liabilities is None or equity is None:
            checks.append(BalanceCheck(p.key, None, False))
            continue
        temporary = cells.get(("temporary_equity", p.key), EMPTY).value or Decimal(0)
        difference = assets - (liabilities + temporary + equity)
        tolerance = max(BALANCE_FLOOR, BALANCE_RELATIVE * assets)
        checks.append(BalanceCheck(p.key, difference, abs(difference) <= tolerance))
    return checks


def _depth(item: CanonicalItemDef, by_code: dict[str, CanonicalItemDef]) -> int:
    depth = 0
    while item.parent is not None:
        item = by_code[item.parent]
        depth += 1
    return depth
