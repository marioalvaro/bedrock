"""The formula language of custom quality-of-earnings rules and formula levels (FR-ANL-10;
docs/erd/analysis.md "Custom rules and formula levels (M2)").

Pure: a recursive-descent parser (never `eval`) and an evaluator over the ratio calculator's
operands. The known names are injected, so this module imports no service code.

    expr    := term (("+" | "-") term)*
    term    := unary (("*" | "×" | "/" | "÷") unary)*
    unary   := "-" unary | primary
    primary := NUMBER ["%"] | NAME | FUNC "(" expr ")" | "(" expr ")"
    FUNC    := avg | yoy | prev
"""

import re
from collections.abc import Callable, Set
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from typing import Literal, cast, get_args

from bedrock.ratios.calculator import Operands, Point, year_earlier
from bedrock.statements.build import growth

MAX_LENGTH = 500
MAX_DEPTH = 32

Func = Literal["avg", "yoy", "prev"]
BinaryOp = Literal["+", "-", "*", "/"]

_FUNCS: frozenset[str] = frozenset(get_args(Func))
_TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<number>[0-9]+(?:\.[0-9]+)?|\.[0-9]+)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op>[-+*/×÷%()])|(?P<bad>.)",
    re.DOTALL,
)
_OPERATORS: dict[str, BinaryOp] = {"+": "+", "-": "-", "*": "*", "×": "*", "/": "/", "÷": "/"}


class FormulaError(ValueError):
    """A formula that does not parse. `position` is the 0-based character index of the error in
    the text; `str(error)` is "<message> at <position>", e.g. "Unknown name 'revenu' at 0"."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(message, position)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        return f"{self.message} at {self.position}"


@dataclass(frozen=True)
class Number:
    """A literal. `value` is the number as written, never negative (a minus is a `Neg`); with
    `percent` the text had a "%" and the number means `value / 100`."""

    value: Decimal
    percent: bool = False


@dataclass(frozen=True)
class Name:
    """A canonical line, metric or ratio code."""

    code: str


@dataclass(frozen=True)
class Call:
    func: Func
    arg: "Node"


@dataclass(frozen=True)
class Neg:
    operand: "Node"


@dataclass(frozen=True)
class BinOp:
    """`×` parses to "*" and `÷` to "/"."""

    op: BinaryOp
    left: "Node"
    right: "Node"


Node = Number | Name | Call | Neg | BinOp


@dataclass(frozen=True)
class Formula:
    """An immutable parsed formula. Two formulas are equal when their trees are equal: `text`, the
    stripped text it was parsed from ("" when built by hand), takes no part in equality."""

    root: Node
    text: str = field(default="", compare=False)


@dataclass(frozen=True)
class _Token:
    kind: str  # number | name | op | bad | end
    text: str
    position: int


def _tokenize(text: str) -> list[_Token]:
    tokens = [
        _Token(m.lastgroup or "", m.group(), m.start())
        for m in _TOKEN.finditer(text)
        if m.lastgroup != "space"
    ]
    tokens.append(_Token("end", "", len(text)))
    return tokens


class _Parser:
    def __init__(self, text: str, known_names: Set[str]) -> None:
        self._text = text
        self._known = known_names
        self._tokens = _tokenize(text)
        self._index = 0
        self._brackets = 0

    @property
    def _current(self) -> _Token:
        return self._tokens[self._index]

    def parse(self) -> Node:
        root = self._expr(0)
        token = self._current
        if token.kind != "end":
            raise self._unexpected(token)
        return root

    def _unexpected(self, token: _Token) -> FormulaError:
        if token.text == ")":
            return FormulaError("Unmatched ')'", token.position)
        if token.text == "%":
            return FormulaError("'%' must follow a number", token.position)
        if token.kind == "bad":
            return FormulaError(f"Unexpected character '{token.text}'", token.position)
        return FormulaError(f"Unexpected '{token.text}'", token.position)

    def _expr(self, depth: int) -> Node:
        node = self._term(depth)
        while self._current.text in ("+", "-"):
            op = _OPERATORS[self._current.text]
            self._index += 1
            node = BinOp(op, node, self._term(depth))
        return node

    def _term(self, depth: int) -> Node:
        node = self._unary(depth)
        while self._current.text in ("*", "×", "/", "÷"):
            op = _OPERATORS[self._current.text]
            self._index += 1
            node = BinOp(op, node, self._unary(depth))
        return node

    def _open_level(self, depth: int, token: _Token) -> int:
        if depth >= MAX_DEPTH:
            raise FormulaError(f"Nesting deeper than {MAX_DEPTH}", token.position)
        return depth + 1

    def _unary(self, depth: int) -> Node:
        token = self._current
        if token.text == "-" and token.kind == "op":
            inner = self._open_level(depth, token)
            self._index += 1
            return Neg(self._unary(inner))
        return self._primary(depth)

    def _primary(self, depth: int) -> Node:
        token = self._current
        if token.kind == "number":
            self._index += 1
            percent = self._current.text == "%"
            if percent:
                self._index += 1
            return Number(Decimal(token.text), percent)
        if token.kind == "name":
            return self._name(token, depth)
        if token.text == "(":
            inner = self._open_level(depth, token)
            self._index += 1
            return self._group(inner)
        if token.text == ")" and self._brackets == 0:
            raise self._unexpected(token)
        if token.kind == "bad" or token.text == "%":
            raise self._unexpected(token)
        raise FormulaError("Missing operand", token.position)

    def _name(self, token: _Token, depth: int) -> Node:
        self._index += 1
        called = self._current.text == "("
        if token.text in _FUNCS:
            if not called:
                raise FormulaError(f"Function '{token.text}' needs '('", token.position)
            inner = self._open_level(depth, token)
            self._index += 1
            func = cast(Func, token.text)  # membership in _FUNCS was just checked
            return Call(func, self._group(inner))
        if called:
            raise FormulaError(f"Unknown function '{token.text}'", token.position)
        if token.text not in self._known:
            raise FormulaError(f"Unknown name '{token.text}'", token.position)
        return Name(token.text)

    def _group(self, depth: int) -> Node:
        """The expression and closing bracket after an already consumed "("."""
        self._brackets += 1
        node = self._expr(depth)
        self._brackets -= 1
        if self._current.text != ")":
            if self._current.kind == "end":
                raise FormulaError("Missing ')'", len(self._text))
            raise self._unexpected(self._current)
        self._index += 1
        return node


def _precedence(node: Node) -> int:
    if isinstance(node, BinOp):
        return 1 if node.op in ("+", "-") else 2
    return 3 if isinstance(node, Neg) else 4


def _print(node: Node, minimum: int) -> str:
    text = _print_bare(node)
    return f"({text})" if _precedence(node) < minimum else text


def _print_bare(node: Node) -> str:
    match node:
        case Number(value, percent):
            return f"{value:f}" + ("%" if percent else "")
        case Name(code):
            return code
        case Call(func, arg):
            return f"{func}({_print_bare(arg)})"
        case Neg(operand):
            return "-" + _print(operand, 3)
        case BinOp(op, left, right):
            level = _precedence(node)
            return f"{_print(left, level)} {op} {_print(right, level + 1)}"


def _walk_names(node: Node) -> frozenset[str]:
    match node:
        case Number():
            return frozenset()
        case Name(code):
            return frozenset({code})
        case Call(_, arg):
            return _walk_names(arg)
        case Neg(operand):
            return _walk_names(operand)
        case BinOp(_, left, right):
            return _walk_names(left) | _walk_names(right)


def _eval(
    node: Node, value: Callable[[str, Point], Decimal | None], point: Point
) -> Decimal | None:
    match node:
        case Number(number, percent):
            return number / 100 if percent else number
        case Name(code):
            return value(code, point)
        case Neg(operand):
            result = _eval(operand, value, point)
            return None if result is None else -result
        case Call("prev", arg):
            return _eval(arg, value, year_earlier(point))
        case Call("avg", arg):
            current = _eval(arg, value, point)
            prior = _eval(arg, value, year_earlier(point))
            return None if current is None or prior is None else (current + prior) / 2
        case Call("yoy", arg):
            return growth(_eval(arg, value, point), _eval(arg, value, year_earlier(point)))
        case BinOp(op, left, right):
            lhs = _eval(left, value, point)
            rhs = _eval(right, value, point)
            if lhs is None or rhs is None:
                return None
            if op == "+":
                return lhs + rhs
            if op == "-":
                return lhs - rhs
            if op == "*":
                return lhs * rhs
            return None if rhs <= 0 else lhs / rhs
    raise AssertionError(f"unreachable node {node!r}")  # pragma: no cover


def _safe_eval(
    formula: Formula, value: Callable[[str, Point], Decimal | None], point: Point
) -> Decimal | None:
    try:
        return _eval(formula.root, value, point)
    except DecimalException:  # InvalidOperation from growth's quantize, Overflow from * + /
        return None


def parse(text: str, known_names: Set[str]) -> Formula:
    """Parses `text` by the grammar above; the result's `text` is `text.strip()`. Whitespace may
    surround any token. NAME is `[A-Za-z_][A-Za-z0-9_]*`; a NAME directly followed (after
    optional whitespace) by "(" is a function call. NUMBER is a plain decimal (`12`, `0.05`,
    `.5`; no sign, no exponent).

    Raises FormulaError, with the 0-based position of the offending character or token, for:
    an empty or blank formula ("Empty formula" at 0); more than MAX_LENGTH characters (at
    MAX_LENGTH); a character outside the grammar; a NAME not in `known_names`
    ("Unknown name '<name>'" at the name's start); a call of a function other than avg, yoy,
    prev ("Unknown function '<name>'"); a function name used without "("; an unbalanced bracket
    (a ")" with no "(" at its position, a missing ")" at the end of the text); a missing operand
    or a trailing token; and nesting deeper than MAX_DEPTH, where every "(", function call and
    unary minus opens one level (at the token that opens level MAX_DEPTH + 1)."""
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"Formula longer than {MAX_LENGTH} characters", MAX_LENGTH)
    if not text.strip():
        raise FormulaError("Empty formula", 0)
    return Formula(_Parser(text, known_names).parse(), text.strip())


def format(formula: Formula) -> str:
    """The canonical text of `formula`: operators "+ - * /" with one space around them, "-" glued
    to its operand, calls as `avg(x)`, numbers in plain notation with their "%" kept, and brackets
    only where the tree needs them (a right operand of the same precedence is always bracketed).
    Postcondition: `parse(format(f), names) == f` for every name set that holds f's names."""
    return _print_bare(formula.root)


def names(formula: Formula) -> frozenset[str]:
    """Every NAME code in the formula."""
    return _walk_names(formula.root)


def is_constant(formula: Formula) -> bool:
    """True when the formula has no names (it is a number expression)."""
    return not _walk_names(formula.root)


def constant_value(formula: Formula) -> Decimal | None:
    """The value of a constant formula, by the `evaluate` rules (a division by a value <= 0 is
    None). Raises ValueError when the formula is not constant."""
    if not is_constant(formula):
        raise ValueError("Formula is not constant")

    def no_names(code: str, point: Point) -> Decimal | None:
        raise AssertionError(code)  # pragma: no cover

    return _safe_eval(formula, no_names, (0, "FY"))


def evaluate(formula: Formula, ops: Operands, point: Point) -> Decimal | None:
    """The formula's value at `point`, unquantized, by the operand rules of the ratio calculator:

    - a name is `ops.value(code, point)`;
    - `prev(e)` is e at `ratios/calculator.py::year_earlier(point)`;
    - `avg(e)` is (e at point + e a year earlier) / 2, None unless both exist;
    - `yoy(e)` is `statements/build.py::growth(e at point, e a year earlier)`;
    - a number with "%" is value / 100;
    - any None operand makes the result None; a division by a value <= 0 is None;
    - a result that cannot be represented (a yoy above the quantization range, or arithmetic
      overflowing the decimal context) is None, never an exception.

    Functions nest (`prev(prev(x))` is two years earlier)."""
    return _safe_eval(formula, ops.value, point)
