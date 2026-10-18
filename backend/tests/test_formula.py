"""The formula language of custom QoE rules and formula levels (FR-ANL-10): grammar, errors with
positions, the printer, constants and evaluation over annual and TTM operands."""

import random
from datetime import date
from decimal import Decimal
from typing import cast, get_args

import pytest

from bedrock.analysis.formula import (
    MAX_DEPTH,
    MAX_LENGTH,
    BinaryOp,
    BinOp,
    Call,
    Formula,
    FormulaError,
    Func,
    Name,
    Neg,
    Node,
    Number,
    constant_value,
    evaluate,
    format,
    is_constant,
    names,
    parse,
)
from bedrock.mapping.config import load_canonical_items
from bedrock.ratios.calculator import Operands, RatioInputs
from bedrock.statements.build import Row, StatementTable, growth
from bedrock.statements.periods import Period

KINDS = {i.code: i.kind for i in load_canonical_items()}
NAMES = {"a", "b", "c", "x", "revenue", "gross_profit", "gross_margin", "total_assets"}


def p(text: str, known: set[str] | None = None) -> Node:
    return parse(text, NAMES if known is None else known).root


def n(value: str, percent: bool = False) -> Number:
    return Number(Decimal(value), percent)


A, B, C = Name("a"), Name("b"), Name("c")


def err(text: str) -> FormulaError:
    with pytest.raises(FormulaError) as info:
        parse(text, NAMES)
    return info.value


# --- grammar -------------------------------------------------------------------------------------


def test_precedence_multiplication_binds_tighter_than_addition() -> None:
    assert p("a + b * c") == BinOp("+", A, BinOp("*", B, C))
    assert p("a * b - c / a") == BinOp("-", BinOp("*", A, B), BinOp("/", C, A))


def test_binary_operators_are_left_associative() -> None:
    assert p("a - b - c") == BinOp("-", BinOp("-", A, B), C)
    assert p("a / b / c") == BinOp("/", BinOp("/", A, B), C)


def test_brackets_override_precedence() -> None:
    assert p("(a + b) * c") == BinOp("*", BinOp("+", A, B), C)
    assert p("a - (b - c)") == BinOp("-", A, BinOp("-", B, C))
    assert p("((a))") == A


def test_unary_minus_binds_tighter_than_multiplication() -> None:
    assert p("-a * b") == BinOp("*", Neg(A), B)
    assert p("--a") == Neg(Neg(A))
    assert p("a - -b") == BinOp("-", A, Neg(B))
    assert p("-(a + b)") == Neg(BinOp("+", A, B))


def test_percent_number_means_a_hundredth() -> None:
    assert p("5%") == n("5", percent=True)
    assert p("5 %") == n("5", percent=True)
    assert p("a * 12.5%") == BinOp("*", A, n("12.5", percent=True))


def test_number_forms() -> None:
    assert p(".5") == n("0.5")
    assert p("12") == n("12")
    assert p("0.05") == n("0.05")


def test_times_and_divide_signs_are_aliases() -> None:
    assert p("a × b ÷ c") == p("a * b / c")


def test_whitespace_may_surround_any_token() -> None:
    assert p("  a+b  ") == p("a + b")
    assert p(" \t( a\n+ b ) *\tc ") == p("(a+b)*c")
    assert p("avg ( a )") == Call("avg", A)


def test_function_calls_and_nesting() -> None:
    assert p("avg(a)") == Call("avg", A)
    assert p("yoy(a) - prev(b)") == BinOp("-", Call("yoy", A), Call("prev", B))
    assert p("avg(yoy(prev(a)))") == Call("avg", Call("yoy", Call("prev", A)))
    assert p("yoy(a + b) / 2") == BinOp("/", Call("yoy", BinOp("+", A, B)), n("2"))


def test_result_text_is_the_stripped_input_and_does_not_affect_equality() -> None:
    f = parse("  a + b ", NAMES)
    assert f.text == "a + b"
    assert f == Formula(BinOp("+", A, B))


def test_parse_exports_the_declared_literals() -> None:
    assert set(get_args(Func)) == {"avg", "yoy", "prev"}
    assert set(get_args(BinaryOp)) == {"+", "-", "*", "/"}


# --- errors --------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_formula(text: str) -> None:
    e = err(text)
    assert (e.message, e.position) == ("Empty formula", 0)
    assert str(e) == "Empty formula at 0"


def test_overlong_formula_is_rejected_at_the_limit() -> None:
    e = err("a" * (MAX_LENGTH + 1))
    assert e.position == MAX_LENGTH
    assert str(e) == f"Formula longer than {MAX_LENGTH} characters at {MAX_LENGTH}"


def test_formula_of_exactly_the_limit_parses() -> None:
    text = " + ".join(["a"] * 125)
    assert len(text) <= MAX_LENGTH
    assert parse(text.ljust(MAX_LENGTH), NAMES).root is not None


@pytest.mark.parametrize(
    ("text", "position"), [("a $ b", 2), ("a + b^2", 5), ("$", 0), ("a, b", 1)]
)
def test_bad_character(text: str, position: int) -> None:
    e = err(text)
    assert e.position == position
    assert e.message == f"Unexpected character '{text[position]}'"


def test_exponent_notation_is_not_a_number() -> None:
    e = err("1e5")
    assert (str(e)) == "Unexpected 'e5' at 1"


def test_number_with_a_trailing_dot() -> None:
    assert err("5.").position == 1
    assert err("1.2.3").position == 3


def test_unknown_name_reports_its_start() -> None:
    assert str(err("revenu / 2")) == "Unknown name 'revenu' at 0"
    assert str(err("a + (b * zzz)")) == "Unknown name 'zzz' at 9"
    assert str(err("  Revenue")) == "Unknown name 'Revenue' at 2"


def test_unknown_function() -> None:
    assert str(err("foo(x)")) == "Unknown function 'foo' at 0"
    assert str(err("a + median(b)")) == "Unknown function 'median' at 4"
    assert str(err("x + revenue (a)")) == "Unknown function 'revenue' at 4"


def test_function_name_without_bracket() -> None:
    assert str(err("avg + 1")) == "Function 'avg' needs '(' at 0"
    assert str(err("1 + yoy")) == "Function 'yoy' needs '(' at 4"
    assert str(err("prev * 2")).endswith(" at 0")


def test_stray_closing_bracket() -> None:
    assert str(err("a + b)")) == "Unmatched ')' at 5"
    assert str(err(")")) == "Unmatched ')' at 0"
    assert str(err("(a))")) == "Unmatched ')' at 3"
    assert str(err("avg(a))")) == "Unmatched ')' at 6"


def test_missing_closing_bracket_is_reported_at_the_end() -> None:
    assert str(err("(a + b")) == "Missing ')' at 6"
    assert str(err("avg(a ")) == "Missing ')' at 6"
    assert str(err("((a)")) == "Missing ')' at 4"


@pytest.mark.parametrize(
    ("text", "position"),
    [("1 +", 3), ("* 2", 0), ("()", 1), ("a + * b", 4), ("-", 1), ("avg()", 4), ("a +  ", 5)],
)
def test_missing_operand(text: str, position: int) -> None:
    e = err(text)
    assert (e.message, e.position) == ("Missing operand", position)


@pytest.mark.parametrize(("text", "position"), [("1 2", 2), ("a b", 2), ("1 (a)", 2), ("(a) b", 4)])
def test_trailing_token(text: str, position: int) -> None:
    e = err(text)
    assert e.position == position
    assert e.message.startswith("Unexpected ")


def test_percent_must_follow_a_number() -> None:
    assert str(err("a%")) == "'%' must follow a number at 1"
    assert str(err("%")) == "'%' must follow a number at 0"
    assert str(err("5%%")) == "'%' must follow a number at 2"
    assert str(err("(5)%")) == "'%' must follow a number at 3"
    assert str(err("-%")).endswith(" at 1")


def test_nesting_of_the_maximum_depth_parses() -> None:
    assert MAX_DEPTH == 32
    text = "(" * MAX_DEPTH + "a" + ")" * MAX_DEPTH
    assert parse(text, NAMES).root == A


def test_brackets_beyond_the_maximum_depth_are_rejected_at_the_opening_bracket() -> None:
    text = "(" * (MAX_DEPTH + 1) + "a" + ")" * (MAX_DEPTH + 1)
    e = err(text)
    assert (e.message, e.position) == ("Nesting deeper than 32", MAX_DEPTH)


def test_calls_and_minus_signs_open_levels_too() -> None:
    assert parse("-" * MAX_DEPTH + "a", NAMES)
    assert err("-" * (MAX_DEPTH + 1) + "a").position == MAX_DEPTH
    calls = "avg(" * MAX_DEPTH + "a" + ")" * MAX_DEPTH
    assert parse(calls, NAMES)
    deeper = "avg(" * (MAX_DEPTH + 1) + "a" + ")" * (MAX_DEPTH + 1)
    assert err(deeper).position == MAX_DEPTH * 4
    mixed = "-(" * 16 + "a" + ")" * 16
    assert parse(mixed, NAMES)
    assert err("-(" * 16 + "-(a" + ")" * 17).position == 32


def test_error_is_a_value_error_with_message_and_position() -> None:
    e = err("a +")
    assert isinstance(e, ValueError)
    assert e.args == ("Missing operand", 3)


# --- format --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("a+b", "a + b"),
        ("a×b÷c", "a * b / c"),
        ("(a)", "a"),
        ("((a + b))", "a + b"),
        ("(a * b) + c", "a * b + c"),
        ("a + (b * c)", "a + b * c"),
        ("(a + b) * c", "(a + b) * c"),
        ("a - (b - c)", "a - (b - c)"),
        ("(a - b) - c", "a - b - c"),
        ("a / (b / c)", "a / (b / c)"),
        ("a / (b * c)", "a / (b * c)"),
        ("a * (b / c)", "a * (b / c)"),
        ("(a / b) * c", "a / b * c"),
        ("a + (b + c)", "a + (b + c)"),
        ("-a", "-a"),
        ("- a * b", "-a * b"),
        ("-(a * b)", "-(a * b)"),
        ("-(a)", "-a"),
        ("--a", "--a"),
        ("a - -b", "a - -b"),
        ("(-a) * b", "-a * b"),
        ("5 %", "5%"),
        (".50", "0.50"),
        ("avg( a ) / 2", "avg(a) / 2"),
        ("yoy(a)-yoy(b)", "yoy(a) - yoy(b)"),
        ("-avg(a)", "-avg(a)"),
        ("12.50%", "12.50%"),
    ],
)
def test_format_is_canonical(text: str, canonical: str) -> None:
    assert format(parse(text, NAMES)) == canonical


def test_format_uses_plain_notation_for_numbers() -> None:
    assert format(Formula(Number(Decimal("1E+2")))) == "100"
    assert format(Formula(Number(Decimal("1E-7")))) == "0.0000001"


def test_format_of_a_hand_built_tree_brackets_a_right_operand_of_equal_precedence() -> None:
    assert format(Formula(BinOp("-", A, BinOp("+", B, C)))) == "a - (b + c)"
    assert format(Formula(BinOp("*", BinOp("+", A, B), Neg(C)))) == "(a + b) * -c"


# hypothesis is not installed (as in test_capital_allocation.py): the properties run over seeded
# random trees instead, which is deterministic and needs no dependency.
SAMPLES = 400


def decimal(rng: random.Random) -> Decimal:
    return Decimal(rng.randint(0, 10**6)) / 1000


def tree(
    rng: random.Random, depth: int, leaf_names: list[str], funcs: list[Func] | None = None
) -> Node:
    funcs = funcs if funcs is not None else ["avg", "yoy", "prev"]
    if depth == 0 or rng.random() < 0.25:
        if leaf_names and rng.random() < 0.5:
            return Name(rng.choice(leaf_names))
        return Number(decimal(rng), rng.random() < 0.3)
    kind = rng.choice(["neg", "call", "bin", "bin"])
    if kind == "neg":
        return Neg(tree(rng, depth - 1, leaf_names, funcs))
    if kind == "call":
        return Call(rng.choice(funcs), tree(rng, depth - 1, leaf_names, funcs))
    op: BinaryOp = rng.choice(["+", "-", "*", "/"])
    return BinOp(
        op, tree(rng, depth - 1, leaf_names, funcs), tree(rng, depth - 1, leaf_names, funcs)
    )


def samples(leaf_names: list[str], funcs: list[Func] | None = None) -> list[Node]:
    rng = random.Random(20261017)
    return [tree(rng, rng.randint(1, 5), leaf_names, funcs) for _ in range(SAMPLES)]


def test_format_then_parse_round_trips() -> None:
    for root in samples(LEAF_NAMES):
        formula = Formula(root)
        assert parse(format(formula), NAMES) == formula


def test_format_is_a_fixed_point() -> None:
    for root in samples(LEAF_NAMES):
        text = format(Formula(root))
        assert format(parse(text, NAMES)) == text


LEAF_NAMES = ["a", "b", "c"]


# --- names and constants -------------------------------------------------------------------------


def test_names_lists_every_code_once() -> None:
    assert names(parse("a + avg(b) * a - yoy(revenue) / 2", NAMES)) == {"a", "b", "revenue"}
    assert names(parse("5% + 1", NAMES)) == frozenset()


def test_is_constant() -> None:
    assert is_constant(parse("(1 + 2) * 3% - -4", NAMES))
    assert is_constant(parse("avg(2)", NAMES))
    assert not is_constant(parse("1 + a", NAMES))
    assert not is_constant(parse("prev(a)", NAMES))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 + 2 * 3", "7"),
        ("(1 + 2) * 3", "9"),
        ("10 - 4 - 3", "3"),
        ("8 / 4 / 2", "1"),
        ("5%", "0.05"),
        ("200 * 5%", "10.00"),
        ("-3 + 1", "-2"),
        ("--3", "3"),
        ("1 / 4", "0.25"),
        ("prev(7)", "7"),
        ("avg(3)", "3"),
        ("1 / 0", None),
        ("1 / -2", None),
        ("1 / (2 - 5)", None),
        ("5 / (1 - 1)", None),
        ("0 / 4", "0"),
    ],
)
def test_constant_value(text: str, expected: str | None) -> None:
    result = constant_value(parse(text, NAMES))
    assert result == (None if expected is None else Decimal(expected))


def test_a_none_inside_a_constant_propagates() -> None:
    assert constant_value(parse("1 + 5 / 0", NAMES)) is None
    assert constant_value(parse("-(1 / 0)", NAMES)) is None


def test_constant_value_of_yoy_follows_growth() -> None:
    assert constant_value(parse("yoy(4)", NAMES)) == Decimal(0)
    assert constant_value(parse("yoy(0)", NAMES)) is None


def test_a_digit_outside_ascii_is_not_a_number() -> None:
    e = err("\u0661\u0662")
    assert e.position == 0


def test_yoy_too_large_to_represent_is_none() -> None:
    now, before = (2024, "FY"), (2023, "FY")
    ops = cast(Operands, Stub({"revenue": {now: Decimal("1e23"), before: Decimal(1)}}))
    assert evaluate(parse("yoy(revenue)", NAMES), ops, now) is None


def test_arithmetic_overflow_is_none() -> None:
    huge = cast(Operands, Stub({"revenue": {(2024, "FY"): Decimal("9e999999")}}))
    assert evaluate(parse("revenue * revenue", NAMES), huge, (2024, "FY")) is None
    assert evaluate(parse("revenue + revenue", NAMES), huge, (2024, "FY")) is None


def test_constant_value_of_a_non_constant_raises() -> None:
    with pytest.raises(ValueError, match="not constant"):
        constant_value(parse("a + 1", NAMES))


def oracle(node: Node) -> Decimal | None:
    """The same arithmetic written out directly, for constant trees."""
    match node:
        case Number(value, percent):
            return value / 100 if percent else value
        case Neg(operand):
            v = oracle(operand)
            return None if v is None else -v
        case Call("prev", arg):
            return oracle(arg)
        case Call("avg", arg):
            v = oracle(arg)
            return None if v is None else (v + v) / 2
        case BinOp(op, left, right):
            lv, rv = oracle(left), oracle(right)
            if lv is None or rv is None:
                return None
            if op == "+":
                return lv + rv
            if op == "-":
                return lv - rv
            if op == "*":
                return lv * rv
            return None if rv <= 0 else lv / rv
    raise AssertionError(node)


def test_constant_value_equals_direct_decimal_arithmetic() -> None:
    for root in samples([], ["avg", "prev"]):
        formula = Formula(root)
        assert is_constant(formula)
        assert constant_value(formula) == oracle(root)


# --- evaluate ------------------------------------------------------------------------------------

Values = list[Decimal | int | str | None]


def fy(year: int) -> Period:
    return Period(
        f"FY{year}", f"FY{year % 100}", year, "FY", date(year - 1, 1, 1), date(year, 1, 1)
    )


def quarter(year: int, q: int) -> Period:
    return Period(
        f"FY{year}Q{q}", f"Q{q} FY{year % 100}", year, f"Q{q}", date(year, 1, 1), date(year, 3, q)
    )


def ttm(year: int, q: int) -> Period:
    return Period(
        f"TTM-FY{year}Q{q}", f"TTM Q{q}", year, f"Q{q}", date(year - 1, 1, 1), date(year, 3, q)
    )


def table(
    statement: str, freq: str, periods: list[Period], rows: dict[str, Values]
) -> StatementTable:
    built = []
    for code, vals in rows.items():
        assert len(vals) == len(periods), code
        k = len(vals)
        cells = [None if v is None else Decimal(v) for v in vals]
        built.append(
            Row(code, code, "USD", KINDS[code], 0, cells, [None] * k, [None] * k, [None] * k)
        )
    return StatementTable(statement, freq, periods, built, None, [])


YEARS = [fy(2022), fy(2023), fy(2024)]
ANNUAL = Operands(
    RatioInputs(
        income=table(
            "IS",
            "annual",
            YEARS,
            {
                "revenue": [None, 100, 150],
                "gross_profit": [40, 50, 90],
                "net_income": [10, -5, 20],
                "receivables": [0, 0, 8],
            },
        ),
        cash_flow=table("CF", "annual", YEARS, {"cfo": [5, 8, 12]}),
        balance=table("BS", "annual", YEARS, {"total_assets": [200, 300, 500]}),
    ),
    "annual",
)
Y22, Y23, Y24 = (2022, "FY"), (2023, "FY"), (2024, "FY")


def ev(text: str, ops: Operands, point: tuple[int, str]) -> Decimal | None:
    return evaluate(parse(text, NAMES | {"net_income", "cfo", "receivables"}), ops, point)


def test_a_line_name_reads_the_operand() -> None:
    assert ev("revenue", ANNUAL, Y24) == Decimal(150)
    assert ev("revenue", ANNUAL, Y22) is None


def test_a_ratio_code_equals_the_operand_value() -> None:
    expected = ANNUAL.value("gross_margin", Y24)
    assert expected is not None
    assert ev("gross_margin", ANNUAL, Y24) == expected


def test_arithmetic_with_names_and_percent() -> None:
    assert ev("gross_profit / revenue", ANNUAL, Y24) == Decimal(90) / Decimal(150)
    assert ev("revenue * 10% + 1", ANNUAL, Y24) == Decimal("16.0")
    assert ev("-revenue", ANNUAL, Y24) == Decimal(-150)


def test_avg_is_null_unless_both_years_exist() -> None:
    assert ev("avg(total_assets)", ANNUAL, Y24) == Decimal(400)
    assert ev("avg(total_assets)", ANNUAL, Y22) is None
    assert ev("avg(revenue)", ANNUAL, Y23) is None


def test_prev_reads_the_year_earlier() -> None:
    assert ev("prev(revenue)", ANNUAL, Y24) == Decimal(100)
    assert ev("prev(prev(total_assets))", ANNUAL, Y24) == Decimal(200)
    assert ev("prev(prev(prev(total_assets)))", ANNUAL, Y24) is None
    assert ev("prev(revenue)", ANNUAL, Y23) is None


def test_prev_of_an_expression() -> None:
    assert ev("prev(revenue - gross_profit)", ANNUAL, Y24) == Decimal(50)


def test_yoy_is_the_statement_growth_rule() -> None:
    assert ev("yoy(revenue)", ANNUAL, Y24) == growth(Decimal(150), Decimal(100))
    assert ev("yoy(revenue)", ANNUAL, Y23) is None
    assert ev("yoy(total_assets)", ANNUAL, Y24) == Decimal("0.666667")


def test_yoy_is_null_unless_the_prior_value_is_positive() -> None:
    assert ev("yoy(receivables)", ANNUAL, Y24) is None
    assert ev("yoy(net_income)", ANNUAL, Y24) is None  # prior -5
    assert ev("yoy(net_income)", ANNUAL, Y23) == growth(Decimal(-5), Decimal(10))


def test_division_by_zero_or_a_negative_is_null() -> None:
    assert ev("revenue / receivables", ANNUAL, Y23) is None
    assert ev("revenue / net_income", ANNUAL, Y23) is None
    assert ev("revenue / (net_income - net_income)", ANNUAL, Y24) is None
    assert ev("1 + revenue / -2", ANNUAL, Y24) is None


def test_a_null_operand_makes_the_result_null() -> None:
    assert ev("revenue + 1", ANNUAL, Y22) is None
    assert ev("1 + 2 * revenue", ANNUAL, Y22) is None
    assert ev("-revenue", ANNUAL, Y22) is None
    assert ev("0 * revenue", ANNUAL, Y22) is None


def test_composite_rule_expression() -> None:
    result = ev("(net_income - cfo) / avg(total_assets)", ANNUAL, Y24)
    assert result == Decimal(8) / Decimal(400)


TTM_PERIODS = [ttm(2024, 2), ttm(2025, 2)]
QUARTERS = [quarter(2024, 2), quarter(2025, 1), quarter(2025, 2)]
TTM_OPS = Operands(
    RatioInputs(
        income=table("IS", "ttm", TTM_PERIODS, {"revenue": [200, 260], "gross_profit": [80, 130]}),
        cash_flow=table("CF", "ttm", TTM_PERIODS, {"cfo": [30, 40]}),
        balance=table("BS", "quarterly", QUARTERS, {"total_assets": [1000, 1100, 1200]}),
        quarterly_income=table("IS", "quarterly", QUARTERS, {"revenue": [1, 1, 1]}),
    ),
    "ttm",
)
T24, T25 = (2024, "Q2"), (2025, "Q2")


def test_ttm_name_and_ratio_follow_the_operands() -> None:
    assert ev("revenue", TTM_OPS, T25) == Decimal(260)
    expected = TTM_OPS.value("gross_margin", T25)
    assert expected is not None
    assert ev("gross_margin", TTM_OPS, T25) == expected


def test_ttm_prev_avg_and_yoy_use_the_same_quarter_a_year_earlier() -> None:
    assert ev("prev(revenue)", TTM_OPS, T25) == Decimal(200)
    assert ev("avg(total_assets)", TTM_OPS, T25) == Decimal(1100)
    assert ev("avg(total_assets)", TTM_OPS, T24) is None
    assert ev("yoy(revenue)", TTM_OPS, T25) == growth(Decimal(260), Decimal(200))
    assert ev("yoy(revenue)", TTM_OPS, T24) is None
    assert ev("prev(prev(revenue))", TTM_OPS, T25) is None


# --- evaluation properties -----------------------------------------------------------------------


class Stub:
    """Operand values by code and point; None where not listed."""

    def __init__(self, values: dict[str, dict[tuple[int, str], Decimal | None]]) -> None:
        self._values = values

    def value(self, code: str, point: tuple[int, str]) -> Decimal | None:
        return self._values.get(code, {}).get(point)


def test_a_missing_operand_makes_every_formula_using_it_null() -> None:
    point = (2024, "FY")
    years = {(2024, "FY"): Decimal(3), (2023, "FY"): Decimal(2), (2022, "FY"): Decimal(1)}
    for root in samples(LEAF_NAMES):
        for missing in LEAF_NAMES:
            # Stub only duck-types Operands.value, the one method evaluate calls
            ops = cast(Operands, Stub({c: years for c in LEAF_NAMES if c != missing}))
            gone = Name(missing)
            for formula in (
                Formula(gone),
                Formula(BinOp("+", root, gone)),
                Formula(BinOp("*", gone, root)),
                Formula(Neg(Call("avg", gone))),
            ):
                assert evaluate(formula, ops, point) is None
