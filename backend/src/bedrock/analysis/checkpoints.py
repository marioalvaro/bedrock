"""Thesis checkpoints (FR-NOTE-03; docs/erd/workspace.md "Thesis checkpoints (M7c)").

Pure. A checkpoint is one comparison of two formulas of the QoE language (`analysis/formula.py`),
read on the ratio calculator's operands as holding, at risk, broken or unknown.

    statement := expr OP expr        OP := > | >= | ≥ | < | <= | ≤
"""

import re
from collections.abc import Callable, Sequence, Set
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from bedrock.analysis import formula as formulas
from bedrock.analysis.formula import BinOp, Call, Formula, FormulaError, Name, Neg, Node, Number
from bedrock.ratios.calculator import Operands, year_earlier
from bedrock.statements.build import RATIO_PLACES
from bedrock.statements.periods import Point

MAX_LENGTH = 500

Op = Literal[">", ">=", "<", "<="]
State = Literal["holding", "at_risk", "broken", "unknown"]
AtRiskBy = Literal["margin", "pace"]

# Two-character forms first, so ">=" is one operator and not ">" followed by "=".
_OPERATOR = re.compile(r">=|<=|[<>≥≤]")
_CANONICAL: dict[str, Op] = {">": ">", ">=": ">=", "≥": ">=", "<": "<", "<=": "<=", "≤": "<="}


@dataclass(frozen=True)
class Statement:
    """`left op right`; `op` is canonical (`≥` parses to ">=", `≤` to "<=")."""

    left: Formula
    op: Op
    right: Formula


@dataclass(frozen=True)
class Evaluation:
    """The checkpoint at `point`, the last point at which both sides have a value. `left`,
    `right` and `gap` are quantized to RATIO_PLACES (None when too large to quantize); the state
    was judged on the unquantized values. Everything but `state` is None when `unknown`;
    `at_risk_by` is set only when `at_risk`."""

    state: State
    point: Point | None
    left: Decimal | None
    right: Decimal | None
    gap: Decimal | None
    at_risk_by: AtRiskBy | None


def parse_statement(text: str, known_names: Set[str]) -> Statement:
    """Parses `text` by the grammar above: it is split at its one comparison operator and each
    side goes through `analysis/formula.py::parse` with `known_names`.

    Raises FormulaError, with the 0-based position in `text`, for: more than MAX_LENGTH
    characters (at MAX_LENGTH); no operator (at 0); a second operator (at it); an empty side
    (the left at the operator, the right at the end of the text); a formula error on a side (its
    position shifted by the side's offset); both sides constant (at 0)."""
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"A checkpoint is longer than {MAX_LENGTH} characters", MAX_LENGTH)
    found = list(_OPERATOR.finditer(text))
    if not found:
        raise FormulaError("A checkpoint compares two values: use >, >=, < or <=", 0)
    if len(found) > 1:
        raise FormulaError("A checkpoint has one comparison", found[1].start())
    match = found[0]
    op = _CANONICAL[match.group()]
    left_text, right_text = text[: match.start()], text[match.end() :]
    if not left_text.strip():
        raise FormulaError(f"Missing value before '{op}'", match.start())
    if not right_text.strip():
        raise FormulaError(f"Missing value after '{op}'", len(text))
    left = _side(left_text, 0, known_names)
    right = _side(right_text, match.end(), known_names)
    if formulas.is_constant(left) and formulas.is_constant(right):
        raise FormulaError("A checkpoint needs a line, a metric or a ratio", 0)
    return Statement(left, op, right)


def _side(text: str, offset: int, known_names: Set[str]) -> Formula:
    try:
        return formulas.parse(text, known_names)
    except FormulaError as error:
        raise FormulaError(error.message, error.position + offset) from error


def format_statement(statement: Statement) -> str:
    """The canonical text: each side by `analysis/formula.py::format`, the operator as ">", ">=",
    "<" or "<=" with one space around it. `parse_statement(format_statement(s)) == s`."""
    left, right = formulas.format(statement.left), formulas.format(statement.right)
    return f"{left} {statement.op} {right}"


def evaluate_checkpoint(
    statement: Statement, margin: Decimal | None, ops: Operands, points: Sequence[Point]
) -> Evaluation:
    """The checkpoint over `points` (oldest first) on `ops`.

    The point is the last one at which both sides have a value (`formula.evaluate`). `gap`, the
    room left, is left - right for > and >=, right - left for < and <=. States: `unknown` with
    no such point; `broken` when the comparison is false there; `at_risk` when it is true and
    either `margin` is set and gap <= margin (`at_risk_by` "margin"), or `margin` is None and the
    gap a year earlier (both sides present there) is more than twice today's (`at_risk_by`
    "pace"); `holding` otherwise."""
    for point in reversed(points):
        gap = _gap(statement, ops, point)
        if gap is None:
            continue
        left, right, room = gap
        if not _holds(statement.op, room):
            state: State = "broken"
            by: AtRiskBy | None = None
        else:
            by = _at_risk_by(statement, margin, ops, point, room)
            state = "holding" if by is None else "at_risk"
        return Evaluation(state, point, _quantize(left), _quantize(right), _quantize(room), by)
    return Evaluation("unknown", None, None, None, None, None)


def _gap(
    statement: Statement, ops: Operands, point: Point
) -> tuple[Decimal, Decimal, Decimal] | None:
    left = formulas.evaluate(statement.left, ops, point)
    right = formulas.evaluate(statement.right, ops, point)
    if left is None or right is None:
        return None
    try:
        room = left - right if statement.op in (">", ">=") else right - left
    except ArithmeticError:  # an overflow of the decimal context: no usable value
        return None
    return left, right, room


def _holds(op: Op, room: Decimal) -> bool:
    return room > 0 if op in (">", "<") else room >= 0


def _at_risk_by(
    statement: Statement, margin: Decimal | None, ops: Operands, point: Point, room: Decimal
) -> AtRiskBy | None:
    if margin is not None:
        return "margin" if room <= margin else None
    earlier = _gap(statement, ops, year_earlier(point))
    if earlier is None:
        return None
    try:
        return "pace" if earlier[2] > 2 * room else None
    except ArithmeticError:  # twice the room overflows the decimal context: it cannot halve
        return None


def _quantize(value: Decimal) -> Decimal | None:
    try:
        return value.quantize(RATIO_PLACES)
    except InvalidOperation:
        return None


# A plain number has no unit of its own: it takes the one it is combined with.
_PLAIN = "plain"


def statement_unit(statement: Statement, unit_of: Callable[[str], str | None]) -> str | None:
    """The unit both sides are in, for display; `unit_of` gives a name's unit (None: unknown).

    A name has its unit, a percent literal is "pct" and `yoy` a growth rate ("pct"); `prev`,
    `avg` and a minus sign keep their operand's unit. A plain number takes the unit of what it is
    added to, subtracted from, multiplied with or divides. Any other product or quotient, or two
    different units, has none (None)."""
    unit = _combine(_unit(statement.left.root, unit_of), _unit(statement.right.root, unit_of))
    return None if unit == _PLAIN else unit


def _unit(node: Node, unit_of: Callable[[str], str | None]) -> str | None:
    match node:
        case Number(_, percent):
            return "pct" if percent else _PLAIN
        case Name(code):
            return unit_of(code)
        case Neg(operand) | Call("prev" | "avg", operand):
            return _unit(operand, unit_of)
        case Call("yoy", _):
            return "pct"
        case BinOp(op, left, right):
            lhs, rhs = _unit(left, unit_of), _unit(right, unit_of)
            if op in ("+", "-"):
                return _combine(lhs, rhs)
            if op == "*" and _PLAIN in (lhs, rhs):
                return rhs if lhs == _PLAIN else lhs
            return lhs if op == "/" and rhs == _PLAIN else None
    raise AssertionError(f"unreachable node {node!r}")  # pragma: no cover


def _combine(lhs: str | None, rhs: str | None) -> str | None:
    if lhs is None or rhs is None:
        return None
    if lhs == _PLAIN:
        return rhs
    return lhs if rhs in (lhs, _PLAIN) else None
