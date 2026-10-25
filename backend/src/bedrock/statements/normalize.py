"""The normalized view: reported cells plus the user's adjustments. Pure.

An adjustment `(code, fiscal_year, fiscal_period, amount)` adds `amount` (in the displayed sign
convention) to its line and propagates the same delta to every line it rolls into (`rolls_into`,
else the parent on the balance sheet and cash flow), so subtotals follow. Lines that are computed
from others are recomputed from the adjusted cells, and normalized EPS follows net income. The
reported cells are never touched: a new dict comes back.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from bedrock.mapping.config import (
    CanonicalItemDef,
    IdentityDef,
    formula_order,
    is_adjustable,
    parse_formula,
    propagation_targets,
)
from bedrock.statements.cell_types import EMPTY, Cell, CellKey
from bedrock.statements.cells import _formula_cell
from bedrock.statements.periods import Calendar, Period, annual_periods, quarterly_periods
from bedrock.statements.rules import identity_derivation, identity_result
from bedrock.statements.splits import per_share

EPS_SHARES = {"eps_basic": "shares_basic", "eps_diluted": "shares_diluted"}
NET_INCOME_COMMON = "net_income_common"


class AdjustmentLike(Protocol):
    """Anything with these attributes: the ORM `Adjustment` row, or a plain value in tests."""

    @property
    def id(self) -> int: ...

    @property
    def canonical_code(self) -> str: ...

    @property
    def fiscal_year(self) -> int: ...

    @property
    def fiscal_period(self) -> str: ...

    @property
    def amount(self) -> Decimal: ...


@dataclass(frozen=True)
class AppliedAdjustment:
    """An adjustment that changed a cell. `code` is the adjusted line and `amount` its amount;
    `via` is that line again when the cell got the change through propagation, else None."""

    adjustment_id: int
    code: str
    amount: Decimal
    via: str | None


def apply_adjustments(
    cells: dict[CellKey, Cell],
    items: Sequence[CanonicalItemDef],
    adjustments: Sequence[AdjustmentLike],
    calendar: Calendar,
    identities: Sequence[IdentityDef] = (),
) -> tuple[dict[CellKey, Cell], dict[CellKey, list[AppliedAdjustment]]]:
    """The normalized cells (FY and Q1..Q4) and, per changed cell, the adjustments behind it.
    An adjustment for an unknown or non-adjustable code, or a period outside the calendar, is
    ignored. A line with no value takes the adjustment as its value; a line it rolls into that
    has no value stays empty. A line that has a value in the period it was adjusted but none in its
    paired period gets no value there: its amount is inside the residual of its breakdown, which
    absorbs the delta there while the totals roll up as usual (Q1..Q4 = FY, footing). A cell an
    `exact` or `bounded` identity solved is solved again from the adjusted operands; an inferred
    zero stays 0."""
    by_code = {i.code: i for i in items}
    period_by_key = {p.key: p for p in annual_periods(calendar) + quarterly_periods(calendar)}
    existing = set(period_by_key)

    deltas: dict[CellKey, Decimal] = defaultdict(Decimal)
    entries: dict[CellKey, list[AppliedAdjustment]] = defaultdict(list)
    direct: set[CellKey] = set()
    for a in adjustments:
        item = by_code.get(a.canonical_code)
        if item is None or not is_adjustable(item):
            continue
        targets = propagation_targets(items, item.code)
        absorber = _residual_absorbing(items, item, targets)
        absorber_targets = propagation_targets(items, absorber.code) if absorber else {}
        keys = _period_keys(item, a, existing)
        # a line with no reported value in the user's own period is being entered by the adjustment
        # (its totals still need the year and its quarters to foot): all its periods take the amount
        entered = not any(
            cells.get((item.code, k), EMPTY).value is not None for k, own in keys if own
        )
        for period_key, own in keys:
            line_cell = (item.code, period_key)
            if own or entered:
                direct.add(line_cell)
            if own or entered or cells.get(line_cell, EMPTY).value is not None:
                deltas[line_cell] += a.amount
                entries[line_cell].append(AppliedAdjustment(a.id, item.code, a.amount, None))
            elif (
                absorber is not None
                and cells.get((absorber.code, period_key), EMPTY).value is not None
            ):
                # the line is empty in this paired period: no value is invented on it, but its
                # amount is inside the breakdown's residual, which takes the delta with the sign
                # that keeps components + residual = subtotal (an absorber that is empty as
                # reported has nothing to foot against: a value typed on it stays as entered)
                common = next(t for t in targets if t in absorber_targets)
                absorbed = a.amount * targets[common] * absorber_targets[common]
                deltas[(absorber.code, period_key)] += absorbed
                entries[(absorber.code, period_key)].append(
                    AppliedAdjustment(a.id, item.code, a.amount, item.code)
                )
            for target, sign in targets.items():
                deltas[(target, period_key)] += sign * a.amount
                entries[(target, period_key)].append(
                    AppliedAdjustment(a.id, item.code, a.amount, item.code)
                )

    out = dict(cells)
    applied: dict[CellKey, list[AppliedAdjustment]] = {}
    changed: dict[CellKey, Decimal] = {}
    for cell_key, delta in deltas.items():
        current = out.get(cell_key, EMPTY)
        if _computed_only(by_code[cell_key[0]]) or (
            current.value is None and cell_key not in direct
        ):
            continue  # recomputed below / nothing to adjust
        out[cell_key] = Cell(
            (current.value or Decimal(0)) + delta, "normalized", current.source, current.derivation
        )
        applied[cell_key] = entries[cell_key]
        changed[cell_key] = delta

    _recompute_computed_only(out, applied, items, period_by_key)
    _resolve_identities(out, applied, cells, identities, by_code, period_by_key)
    _follow_eps(out, applied, by_code, changed)
    for entries_of_cell in applied.values():  # one rule for every path: by adjustment id (stable)
        entries_of_cell.sort(key=lambda e: e.adjustment_id)
    return out, applied


def _residual_absorbing(
    items: Sequence[CanonicalItemDef], item: CanonicalItemDef, targets: dict[str, int]
) -> CanonicalItemDef | None:
    """The residual that holds `item` where `item` itself is unreported: the residual of its
    breakdown (same non-null parent, the siblings its formula treats as 0 when missing) that rolls
    up to a total it shares with it. None for a line with no parent, such as a subtotal (no
    residual absorbs it), or no such residual: the totals then move on their own."""
    if item.parent is None:
        return None
    return next(
        (
            i
            for i in items
            if i.residual
            and i.code != item.code
            and i.parent == item.parent
            and targets.keys() & propagation_targets(items, i.code).keys()
        ),
        None,
    )


def _period_keys(
    item: CanonicalItemDef, a: AdjustmentLike, existing: set[str]
) -> list[tuple[str, bool]]:
    """The periods an adjustment lands in (keeps Q1+Q2+Q3+Q4 = FY for flows), each flagged `own`
    when the user picked it (an instant's FY and Q4 are the same balance, so both are own); the
    other, paired period only follows a value that is already there."""
    year, period = f"FY{a.fiscal_year}", a.fiscal_period
    instant = item.kind == "instant"
    if period == "FY" or (period == "Q4" and instant):
        keys = [(year, True), (f"{year}Q4", instant)]
    elif period == "Q4":
        keys = [(f"{year}Q4", True), (year, False)]
    elif period in ("Q1", "Q2", "Q3"):
        keys = [(f"{year}{period}", True)] + ([(year, False)] if item.kind == "flow" else [])
    else:
        return []
    return [(k, own) for k, own in keys if k in existing]


def _computed_only(item: CanonicalItemDef) -> bool:
    return item.derive is not None and not item.concepts and not item.residual


def _recompute_computed_only(
    cells: dict[CellKey, Cell],
    applied: dict[CellKey, list[AppliedAdjustment]],
    items: Sequence[CanonicalItemDef],
    period_by_key: dict[str, Period],
) -> None:
    """Totals defined only by a formula (total_debt, free_cash_flow, ...) follow their operands.
    Derive fallbacks and residuals are not recomputed: their change came through propagation."""
    periods = {key for _, key in applied}
    for item in formula_order(items):
        if not _computed_only(item):
            continue
        assert item.derive is not None
        operands = [code for _, code in parse_formula(item.derive)]
        for key in sorted(periods):
            touched = [applied[(c, key)] for c in operands if (c, key) in applied]
            if not touched:
                continue
            cell = _formula_cell(item, period_by_key[key], cells)
            cells[(item.code, key)] = (
                Cell(cell.value, "normalized", cell.source, cell.derivation)
                if cell.value is not None
                else EMPTY
            )
            if cell.value is not None:
                seen: dict[int, AppliedAdjustment] = {}
                for entry in (e for group in touched for e in group):
                    seen.setdefault(
                        entry.adjustment_id,
                        AppliedAdjustment(
                            entry.adjustment_id, entry.code, entry.amount, entry.code
                        ),
                    )
                applied[(item.code, key)] = list(seen.values())


def _resolve_identities(
    out: dict[CellKey, Cell],
    applied: dict[CellKey, list[AppliedAdjustment]],
    reported: dict[CellKey, Cell],
    identities: Sequence[IdentityDef],
    by_code: dict[str, CanonicalItemDef],
    period_by_key: dict[str, Period],
) -> None:
    """Solve again every `exact` or `bounded` cell of `identities` whose operands an adjustment
    changed, from the adjusted operands (an adjustment to a total that the identity ties to other
    lines would otherwise leave the solved line behind). Q4 of a solved flow follows its year, so
    it is solved again too. `zero_only` cells are never touched: an inferred zero stays 0."""
    for identity in identities:
        for code, rule in identity.solve.items():
            if rule.mode == "zero_only" or code not in by_code:
                continue
            operands = [c for _, c in identity.terms if c != code]
            for key, period in period_by_key.items():
                if not _solved_by(identity, code, key, period, reported, by_code):
                    continue
                changed = [c for c in operands if (c, key) in applied]
                values = {c: out.get((c, key), EMPTY).value for c in operands}
                if not changed or any(v is None for v in values.values()):
                    continue
                known = {c: v for c, v in values.items() if v is not None}
                result = identity_result(identity, code, known)
                current = out.get((code, key), EMPTY)
                if current.value == result:
                    continue
                out[(code, key)] = Cell(
                    result,
                    "normalized",
                    None,
                    identity_derivation(identity, code, known, period.fiscal_period),
                )
                seen: dict[int, AppliedAdjustment] = {}
                for entry in (e for c in changed for e in applied[(c, key)]):
                    seen.setdefault(
                        entry.adjustment_id,
                        AppliedAdjustment(
                            entry.adjustment_id, entry.code, entry.amount, entry.code
                        ),
                    )
                applied[(code, key)] = list(seen.values())


def _solved_by(
    identity: IdentityDef,
    code: str,
    key: str,
    period: Period,
    reported: dict[CellKey, Cell],
    by_code: dict[str, CanonicalItemDef],
) -> bool:
    cell = reported.get((code, key), EMPTY)
    if cell.solved_by == identity.id:
        return True
    year = reported.get((code, f"FY{period.fiscal_year}"), EMPTY)
    return (
        period.fiscal_period == "Q4"
        and by_code[code].kind == "flow"
        and cell.value is not None
        and year.solved_by == identity.id
    )


def _follow_eps(
    cells: dict[CellKey, Cell],
    applied: dict[CellKey, list[AppliedAdjustment]],
    by_code: dict[str, CanonicalItemDef],
    changed: dict[CellKey, Decimal],
) -> None:
    """Normalized EPS = reported + change in net income common / shares of the same period; null
    when net income changes and the shares are missing. Q4 and TTM stay null (EPS is an average)."""
    for (code, key), delta in changed.items():
        if code != NET_INCOME_COMMON or delta == 0:
            continue
        for eps_code, shares_code in EPS_SHARES.items():
            current = cells.get((eps_code, key), EMPTY)
            if eps_code not in by_code or current.value is None:
                continue
            shares = cells.get((shares_code, key), EMPTY).value
            # the adjustments behind EPS are the ones behind net income common, emptied or not
            applied[(eps_code, key)] = [
                AppliedAdjustment(e.adjustment_id, e.code, e.amount, e.code)
                for e in applied[(code, key)]
            ]
            if not shares:
                cells[(eps_code, key)] = EMPTY
                continue
            cells[(eps_code, key)] = Cell(
                per_share(current.value + delta / shares),
                "normalized",
                current.source,
                current.derivation,
            )
