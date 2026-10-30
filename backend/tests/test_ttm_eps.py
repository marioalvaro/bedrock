"""TTM EPS (docs/erd/data.md "R2"): the sum of the four quarterly EPS, on the EPS lines only."""

from decimal import Decimal

from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import Row, StatementTable, build_statement
from tests.average_data import ITEMS, JUNE, MAPS, M, eps, income, shares
from tests.engine_data import facts


def ttm(rows: list) -> StatementTable:  # type: ignore[type-arg]
    canonical = map_facts(select_vintage(facts(rows)), MAPS, ITEMS)  # type: ignore[arg-type]
    return build_statement(canonical, ITEMS, "IS", "ttm")


def line(table: StatementTable, code: str) -> Row:
    (found,) = [r for r in table.rows if r.code == code]
    return found


def year_rows(fiscal: str = "3.99", quarters: tuple[str | None, ...] = ("1.01", "0.99", "1.00")):
    return (
        income(JUNE)
        + shares("shares_diluted", JUNE, 100 * M, (100 * M, 100 * M, 100 * M))
        + shares("shares_basic", JUNE, 100 * M, (100 * M, 100 * M, 100 * M))
        + eps("eps_diluted", JUNE, fiscal, quarters)
        + eps("eps_basic", JUNE, fiscal, quarters)
    )


def test_ttm_eps_is_the_sum_of_the_four_quarterly_eps_not_the_year() -> None:
    table = ttm(year_rows())

    # Q1..Q3 as reported and Q4 = 100 M / 100 M = 1.00: the sum is 4.00 while the year says 3.99
    assert line(table, "eps_diluted").values == [Decimal("4.00")]
    assert line(table, "eps_basic").values == [Decimal("4.00")]


def test_ttm_eps_is_approximated_because_a_quarter_is() -> None:
    table = ttm(year_rows())

    assert line(table, "eps_diluted").provenance == ["approximated"]


def test_ttm_eps_is_empty_while_a_quarter_is_missing() -> None:
    table = ttm(year_rows(quarters=("1.01", None, "1.00")))

    assert line(table, "eps_diluted").values == [None]
    assert line(table, "eps_diluted").provenance == [None]


def test_ttm_eps_is_empty_when_q4_eps_was_refused() -> None:
    table = ttm(year_rows(fiscal="3.50", quarters=("1.00", "1.00", "1.00")))

    assert line(table, "eps_diluted").values == [None]
    assert [w.rule for w in table.rule_warnings] == ["q4_eps", "q4_eps"]


def test_other_average_items_have_no_ttm() -> None:
    table = ttm(year_rows())

    assert line(table, "shares_diluted").values == [None]
    assert line(table, "shares_basic").values == [None]
    assert line(table, "net_income_common").values == [Decimal(400 * M)]
