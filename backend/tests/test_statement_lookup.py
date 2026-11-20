"""`Period.point`, `StatementTable.row` and `StatementTable.value_at`: the one way to find a line
and its value at a fiscal point."""

from datetime import date, timedelta
from decimal import Decimal

from bedrock.statements.build import Row, StatementTable
from bedrock.statements.periods import Period


def fy(year: int) -> Period:
    end = date(year, 9, 30)
    return Period(f"FY{year}", f"FY{year % 100}", year, "FY", end - timedelta(days=364), end)


def row(code: str, values: list[Decimal | None]) -> Row:
    n = len(values)
    return Row(code, code.title(), "USD", "flow", 0, values, [None] * n, [None] * n, [None] * n)


TABLE = StatementTable(
    "IS",
    "annual",
    [fy(2024), fy(2025)],
    [row("revenue", [Decimal(10), Decimal(12)]), row("cogs", [None, Decimal(5)])],
    None,
    [],
)


def test_a_periods_point_is_its_fiscal_year_and_period() -> None:
    assert fy(2025).point == (2025, "FY")


def test_row_finds_the_line_by_code() -> None:
    found = TABLE.row("cogs")
    assert found is not None
    assert found.code == "cogs"


def test_row_of_a_missing_code_is_none() -> None:
    assert TABLE.row("capex") is None


def test_value_at_reads_the_cell_at_the_point() -> None:
    assert TABLE.value_at("revenue", (2024, "FY")) == Decimal(10)
    assert TABLE.value_at("revenue", (2025, "FY")) == Decimal(12)


def test_value_at_an_empty_cell_is_none() -> None:
    assert TABLE.value_at("cogs", (2024, "FY")) is None


def test_value_at_a_missing_point_or_code_is_none() -> None:
    assert TABLE.value_at("revenue", (2023, "FY")) is None
    assert TABLE.value_at("revenue", (2025, "Q1")) is None
    assert TABLE.value_at("capex", (2025, "FY")) is None
