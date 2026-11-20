"""Thesis checkpoints, the pure engine (FR-NOTE-03; docs/erd/workspace.md "Thesis checkpoints"):
the statement language over the QoE formulas, and the evaluation into holding, at risk, broken
or unknown."""

import random
from datetime import date
from decimal import Decimal

import pytest

from bedrock.analysis.checkpoints import (
    MAX_LENGTH,
    Evaluation,
    Statement,
    evaluate_checkpoint,
    format_statement,
    parse_statement,
    statement_unit,
)
from bedrock.analysis.formula import Formula, FormulaError, Name, Number, parse
from bedrock.analysis.formula import format as format_formula
from bedrock.mapping.config import load_canonical_items
from bedrock.ratios.calculator import Operands, RatioInputs
from bedrock.statements.build import RATIO_PLACES, Row, StatementTable
from bedrock.statements.periods import Period

from .test_formula import samples

KINDS = {i.code: i.kind for i in load_canonical_items()}
NAMES = frozenset({"a", "b", "revenue", "gross_profit", "gross_margin", "shares_outstanding"})


def stmt(text: str) -> Statement:
    return parse_statement(text, NAMES)


def error_of(text: str) -> FormulaError:
    with pytest.raises(FormulaError) as caught:
        parse_statement(text, NAMES)
    return caught.value


# --- the statement language ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "op"),
    [
        ("a > 1", ">"),
        ("a >= 1", ">="),
        ("a ≥ 1", ">="),
        ("a < 1", "<"),
        ("a <= 1", "<="),
        ("a ≤ 1", "<="),
        ("a>=1", ">="),
    ],
)
def test_every_operator_and_alias(text: str, op: str) -> None:
    parsed = stmt(text)
    assert parsed.op == op
    assert parsed.left.root == Name("a")
    assert parsed.right.root == Number(Decimal(1))


def test_each_side_is_a_formula_of_the_qoe_language() -> None:
    parsed = stmt("gross_margin > prev(gross_margin) - 2%")
    assert parsed.left == parse("gross_margin", NAMES)
    assert parsed.right == parse("prev(gross_margin) - 2%", NAMES)


def test_a_constant_may_stand_on_the_left() -> None:
    assert stmt("44% < gross_margin").op == "<"


@pytest.mark.parametrize("text", ["a + b", "", "   ", "a = 1"])
def test_no_operator(text: str) -> None:
    error = error_of(text)
    assert error.message == "A checkpoint compares two values: use >, >=, < or <="
    assert error.position == 0


def test_more_than_one_operator_is_reported_at_the_second() -> None:
    error = error_of("a > b > 1")
    assert error.message == "A checkpoint has one comparison"
    assert error.position == 6


def test_a_doubled_operator_is_more_than_one() -> None:
    assert error_of("a >> 1").position == 3


def test_an_empty_left_side_is_reported_at_the_operator() -> None:
    error = error_of("  > 1")
    assert error.message == "Missing value before '>'"
    assert error.position == 2


def test_an_empty_right_side_is_reported_at_the_end() -> None:
    error = error_of("a >=  ")
    assert error.message == "Missing value after '>='"
    assert error.position == 6


def test_a_formula_error_on_the_right_is_shifted_by_the_side_offset() -> None:
    error = error_of("a > revenu")
    assert error.message == "Unknown name 'revenu'"
    assert error.position == 4


def test_a_formula_error_on_the_left_keeps_its_position() -> None:
    error = error_of(" (a > 1")
    assert error.message == "Missing ')'"
    assert error.position == 4  # the end of the left side, " (a "


def test_both_sides_constant() -> None:
    error = error_of("1 > 2%")
    assert error.message == "A checkpoint needs a line, a metric or a ratio"
    assert error.position == 0


def test_over_the_length_limit() -> None:
    text = "a > " + "1" * (MAX_LENGTH - 3)
    error = error_of(text)
    assert error.position == MAX_LENGTH
    assert str(MAX_LENGTH) in error.message


def test_exactly_the_length_limit_parses() -> None:
    assert stmt("a > " + "1" * (MAX_LENGTH - 4)).op == ">"


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("a≥1", "a >= 1"),
        ("a ≤ 5 %", "a <= 5%"),
        ("gross_margin>prev(gross_margin)-2%", "gross_margin > prev(gross_margin) - 2%"),
        ("yoy(shares_outstanding) < 0", "yoy(shares_outstanding) < 0"),
    ],
)
def test_format_statement_is_canonical(text: str, canonical: str) -> None:
    assert format_statement(stmt(text)) == canonical


def test_format_statement_round_trips_over_random_formulas() -> None:
    sides = samples(["a", "b"])
    rng = random.Random(20261118)
    for left, right in zip(sides, reversed(sides), strict=True):
        op = rng.choice([">", ">=", "<", "<=", "≥", "≤"])
        text = f"{format_formula(Formula(left))} {op} {format_formula(Formula(right))}"
        if len(text) > MAX_LENGTH:
            continue
        try:
            parsed = stmt(text)
        except FormulaError as error:  # two constants: the one error a random pair may hit
            assert error.message == "A checkpoint needs a line, a metric or a ratio"
            continue
        assert stmt(format_statement(parsed)) == parsed


# --- evaluation ------------------------------------------------------------------------------


def fy(year: int) -> Period:
    return Period(
        f"FY{year}", f"FY{year % 100}", year, "FY", date(year - 1, 1, 1), date(year, 1, 1)
    )


def annual(rows: dict[str, list[int | str | None]], years: list[int]) -> Operands:
    periods = [fy(y) for y in years]
    built = []
    for code, values in rows.items():
        k = len(values)
        cells = [None if v is None else Decimal(v) for v in values]
        built.append(
            Row(code, code, "USD", KINDS[code], 0, cells, [None] * k, [None] * k, [None] * k)
        )
    income = StatementTable("IS", "annual", periods, built, None, [])
    empty = StatementTable("CF", "annual", periods, [], None, [])
    balance = StatementTable("BS", "annual", periods, [], None, [])
    return Operands(RatioInputs(income, empty, balance), "annual")


YEARS = [2021, 2022, 2023, 2024]
POINTS = [(y, "FY") for y in YEARS]


def check(
    text: str, rows: dict[str, list[int | str | None]], margin: Decimal | None = None
) -> Evaluation:
    names = frozenset(rows) | {"gross_margin"}
    return evaluate_checkpoint(parse_statement(text, names), margin, annual(rows, YEARS), POINTS)


def test_holding_when_true_with_room_that_has_not_halved() -> None:
    result = check("revenue > 100", {"revenue": [150, 160, 170, 180]})
    assert result.state == "holding"
    assert result.point == (2024, "FY")
    assert (result.left, result.right, result.gap) == (Decimal(180), Decimal(100), Decimal(80))
    assert result.at_risk_by is None


def test_broken_when_false_at_the_point() -> None:
    result = check("revenue > 100", {"revenue": [150, 160, 170, 90]})
    assert result.state == "broken"
    assert result.gap == Decimal(-10)
    assert result.at_risk_by is None


@pytest.mark.parametrize(
    ("text", "earlier", "state"),
    [
        ("revenue > 100", 150, "broken"),
        ("revenue >= 100", 150, "at_risk"),  # true, and the room (0) has more than halved
        ("revenue < 100", 50, "broken"),
        ("revenue <= 100", 50, "at_risk"),
    ],
)
def test_strict_and_non_strict_comparisons_at_equality(text: str, earlier: int, state: str) -> None:
    assert check(text, {"revenue": [earlier, earlier, earlier, 100]}).state == state


def test_a_room_that_was_negative_a_year_earlier_is_not_a_pace_risk() -> None:
    assert check("revenue <= 100", {"revenue": [150, 150, 150, 100]}).state == "holding"


def test_the_gap_of_a_less_than_is_right_minus_left() -> None:
    result = check("revenue < 200", {"revenue": [150, 150, 150, 150]})
    assert (result.state, result.gap) == ("holding", Decimal(50))


def test_at_risk_by_pace_when_the_room_more_than_halved_in_a_year() -> None:
    result = check("revenue > 100", {"revenue": [200, 200, 141, 120]})  # room 41 -> 20
    assert (result.state, result.at_risk_by) == ("at_risk", "pace")


def test_exactly_halved_room_is_still_holding() -> None:
    assert check("revenue > 100", {"revenue": [200, 200, 140, 120]}).state == "holding"


def test_pace_needs_both_sides_a_year_earlier() -> None:
    result = check("revenue > 100", {"revenue": [200, 200, None, 120]})
    assert result.state == "holding"


def test_pace_compares_only_the_year_before_not_older_years() -> None:
    assert check("revenue > 100", {"revenue": [900, 130, 130, 120]}).state == "holding"


def test_a_margin_judges_instead_of_the_pace() -> None:
    rows: dict[str, list[int | str | None]] = {"revenue": [200, 200, 141, 120]}
    held = check("revenue > 100", rows, margin=Decimal(19))
    assert (held.state, held.at_risk_by) == ("holding", None)
    at = check("revenue > 100", rows, margin=Decimal(20))  # gap 20 <= margin 20
    assert (at.state, at.at_risk_by) == ("at_risk", "margin")


def test_a_margin_does_not_rescue_a_broken_checkpoint() -> None:
    result = check("revenue > 100", {"revenue": [1, 1, 1, 99]}, margin=Decimal(5))
    assert (result.state, result.at_risk_by) == ("broken", None)


def test_the_point_is_the_last_one_where_both_sides_have_a_value() -> None:
    result = check(
        "revenue > gross_profit", {"revenue": [5, 10, 30, 40], "gross_profit": [1, 2, 3, None]}
    )
    assert result.point == (2023, "FY")
    assert result.gap == Decimal(27)


def test_unknown_with_no_point_where_both_sides_have_a_value() -> None:
    result = check(
        "revenue > gross_profit",
        {"revenue": [1, None, 3, None], "gross_profit": [None, 2, None, 4]},
    )
    assert result == Evaluation("unknown", None, None, None, None, None)


def test_unknown_with_no_points() -> None:
    result = evaluate_checkpoint(stmt("a > 1"), None, annual({}, []), [])
    assert result.state == "unknown"


def test_a_null_operand_inside_a_side_makes_that_point_unusable() -> None:
    result = check(
        "revenue + gross_profit > 0", {"revenue": [1, 2, 3, 4], "gross_profit": [1, 1, 1, None]}
    )
    assert result.point == (2023, "FY")


def test_a_division_by_zero_side_is_null_and_skipped() -> None:
    result = check(
        "revenue / gross_profit > 1", {"revenue": [5, 5, 5, 5], "gross_profit": [1, 1, 1, 0]}
    )
    assert result.point == (2023, "FY")


def test_values_are_quantized_but_the_comparison_is_not() -> None:
    # gross_margin is quantized as a ratio row value; a line division is not
    result = check(
        "gross_profit / revenue > 0.3333333",
        {"revenue": [3, 3, 3, 3], "gross_profit": [1, 1, 1, 1]},
    )
    assert result.state != "broken"  # 1/3 > 0.3333333 unquantized
    assert result.left == (Decimal(1) / Decimal(3)).quantize(RATIO_PLACES)
    assert result.gap is not None and result.gap == result.gap.quantize(RATIO_PLACES)


def test_a_side_too_large_to_quantize_is_null_in_the_payload_only() -> None:
    result = check("revenue * revenue > 0", {"revenue": [1, 1, 1, "1E+30"]})
    assert result.state == "holding"
    assert result.point == (2024, "FY")
    assert result.left is None


def test_a_room_near_the_decimal_limit_does_not_raise() -> None:
    huge = "9.9E+999999"  # at the context maximum: left - right fits, twice it overflows
    result = check("revenue > 0", {"revenue": [huge, huge, huge, huge]})
    assert (result.state, result.left) == ("holding", None)  # too large to quantize


# --- the unit of a statement's sides -------------------------------------------------------

UNITS = {"a": "USD", "b": "USD", "revenue": "USD", "gross_profit": "USD", "gross_margin": "pct"}


def unit_of(text: str) -> str | None:
    return statement_unit(stmt(text), lambda code: UNITS.get(code))


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("gross_margin > 44%", "pct"),  # a name against a percent literal
        ("44% < gross_margin", "pct"),
        ("revenue > 0", "USD"),  # a plain number takes the other side's unit
        ("revenue > gross_profit", "USD"),
        ("revenue - gross_profit > 1000", "USD"),  # + and - keep a shared unit
        ("-revenue < 0", "USD"),
        ("revenue * 1.1 > gross_profit", "USD"),  # scaled by a plain number
        ("revenue / 2 > gross_profit", "USD"),
        ("yoy(revenue) > 5%", "pct"),  # a growth rate
        ("avg(revenue) > prev(revenue)", "USD"),
        ("gross_profit / revenue > 40%", None),  # a quotient of two units has none
        ("revenue > gross_margin", None),  # the sides disagree
        ("revenue + gross_margin > 0", None),
        ("shares_outstanding > 0", None),  # a name with no known unit
    ],
)
def test_the_statement_unit(text: str, unit: str | None) -> None:
    assert unit_of(text) == unit
