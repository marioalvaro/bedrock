"""Trimming the columns of a statement table that the API should not show."""

from datetime import date
from decimal import Decimal

from bedrock.statements.build import BalanceCheck, Row, StatementTable
from bedrock.statements.periods import Period
from bedrock.statements.view import trim_periods

D = Decimal


def _period(year: int) -> Period:
    return Period(
        f"FY{year}", f"FY{year % 100}", year, "FY", date(year - 1, 7, 1), date(year, 6, 30)
    )


def _row(code: str, values: list[Decimal | None]) -> Row:
    return Row(
        code=code,
        label=code,
        unit="USD",
        kind="flow",
        depth=0,
        values=values,
        provenance=["reported" if v is not None else None for v in values],
        yoy=[D("0.5") if v is not None else None for v in values],
        common_size=[D("1") if v is not None else None for v in values],
    )


def _table() -> StatementTable:
    # FY2010 and FY2013 are empty in every row; FY2011 has one value; FY2012 has both.
    periods = [_period(y) for y in (2010, 2011, 2012, 2013)]
    return StatementTable(
        statement="BS",
        freq="annual",
        periods=periods,
        rows=[
            _row("cash", [None, D("5"), D("6"), None]),
            _row("goodwill", [None, None, D("2"), None]),
        ],
        balance_check=[BalanceCheck(p.key, D("0"), True) for p in periods],
        warnings=["FY2010: no quarters"],
    )


def test_periods_with_no_value_in_any_row_are_dropped() -> None:
    trimmed = trim_periods(_table())

    assert [p.key for p in trimmed.periods] == ["FY2011", "FY2012"]


def test_every_row_array_and_the_balance_check_stay_aligned_with_the_periods() -> None:
    trimmed = trim_periods(_table())

    cash, goodwill = trimmed.rows
    assert cash.values == [D("5"), D("6")]
    assert goodwill.values == [None, D("2")]
    for row in trimmed.rows:
        assert len(row.provenance) == len(row.yoy) == len(row.common_size) == 2
    assert cash.provenance == ["reported", "reported"]
    assert goodwill.provenance == [None, "reported"]
    assert trimmed.balance_check is not None
    assert [c.period_key for c in trimmed.balance_check] == ["FY2011", "FY2012"]


def test_a_balance_sheet_period_missing_a_total_is_dropped_too() -> None:
    # The values of such a column are comparatives from other statements, not a balance sheet.
    table = _table()
    checks = [
        BalanceCheck("FY2010", None, False),
        BalanceCheck("FY2011", None, False),  # has a value, but no difference: incomplete
        BalanceCheck("FY2012", D("0"), True),
        BalanceCheck("FY2013", None, False),
    ]
    table = StatementTable(
        table.statement, table.freq, table.periods, table.rows, checks, table.warnings
    )

    trimmed = trim_periods(table)

    assert [p.key for p in trimmed.periods] == ["FY2012"]
    assert trimmed.rows[0].values == [D("6")]
    assert trimmed.balance_check == [BalanceCheck("FY2012", D("0"), True)]


def test_a_balance_sheet_period_that_fails_the_check_is_kept() -> None:
    # A real imbalance must stay visible; only a sheet that cannot be checked is dropped.
    table = _table()
    checks = [BalanceCheck(p.key, D("900"), False) for p in table.periods]
    table = StatementTable(
        table.statement, table.freq, table.periods, table.rows, checks, table.warnings
    )

    assert [p.key for p in trim_periods(table).periods] == ["FY2011", "FY2012"]


def test_rows_stay_even_when_they_have_no_value_at_all() -> None:
    table = _table()
    empty_row = _row("intangibles", [None] * 4)
    table = StatementTable(
        table.statement,
        table.freq,
        table.periods,
        [*table.rows, empty_row],
        table.balance_check,
        table.warnings,
    )

    trimmed = trim_periods(table)

    assert [r.code for r in trimmed.rows] == ["cash", "goodwill", "intangibles"]
    assert trimmed.rows[2].values == [None, None]


def test_a_table_with_every_period_filled_is_unchanged() -> None:
    table = StatementTable(
        "IS", "annual", [_period(2011)], [_row("revenue", [D("1")])], None, ["kept"]
    )

    assert trim_periods(table) == table


def test_a_table_with_no_values_has_no_periods() -> None:
    table = StatementTable("IS", "annual", [_period(2011)], [_row("revenue", [None])], None, [])

    assert trim_periods(table).periods == []
