"""Forecast columns appended to a statement table, and picking the columns to show
(`statements/build.py::extend_table`, `statements/view.py::select_periods`)."""

from datetime import date
from decimal import Decimal

from bedrock.statements.build import BalanceCheck, Row, StatementTable, extend_table
from bedrock.statements.periods import Period
from bedrock.statements.view import select_periods

D = Decimal


def _fy(year: int, forecast: bool = False) -> Period:
    label = f"FY{year % 100:02d}{'E' if forecast else ''}"
    return Period(f"FY{year}", label, year, "FY", date(year, 1, 1), date(year, 12, 31))


def _row(code: str, values: list[Decimal | None], yoy: list[Decimal | None]) -> Row:
    return Row(
        code=code,
        label=code.title(),
        unit="USD",
        kind="flow",
        depth=0,
        values=values,
        provenance=["reported" if v is not None else None for v in values],
        yoy=yoy,
        common_size=[D(1) if v is not None else None for v in values],
        common_size_base="Revenue",
    )


def _income() -> StatementTable:
    periods = [_fy(2024), _fy(2025)]
    return StatementTable(
        "IS",
        "annual",
        periods,
        [
            _row("revenue", [D(100), D(110)], [None, D("0.1")]),
            _row("sga", [D(10), None], [None, None]),
            _row("custom:x", [D(1), D(2)], [None, D(1)]),
        ],
        None,
        ["a calendar warning"],
    )


def test_forecast_columns_are_appended_with_forecast_provenance() -> None:
    forecast = [_fy(2026, True), _fy(2027, True)]
    values = {
        ("revenue", "FY2026"): D(121),
        ("revenue", "FY2027"): D(133),
        ("sga", "FY2026"): D(12),
        ("sga", "FY2027"): None,
    }

    table = extend_table(_income(), forecast, values)

    assert [p.key for p in table.periods] == ["FY2024", "FY2025", "FY2026", "FY2027"]
    revenue, sga, custom = table.rows
    assert revenue.values == [D(100), D(110), D(121), D(133)]
    assert revenue.provenance == ["reported", "reported", "forecast", "forecast"]
    assert sga.values == [D(10), None, D(12), None]
    assert sga.provenance == ["reported", None, "forecast", None]
    # a line the forecast does not carry is null in the forecast columns
    assert custom.values == [D(1), D(2), None, None]
    assert table.warnings == ["a calendar warning"]


def test_yoy_runs_across_the_actual_to_forecast_boundary() -> None:
    values = {("revenue", "FY2026"): D(121), ("revenue", "FY2027"): D(133)}

    revenue = extend_table(_income(), [_fy(2026, True), _fy(2027, True)], values).rows[0]

    # history YoY kept; FY26E against the actual FY25, FY27E against FY26E (6 places)
    assert revenue.yoy == [None, D("0.1"), D("0.100000"), D("0.099174")]


def test_yoy_is_null_when_the_prior_year_is_missing_or_not_positive() -> None:
    values = {("revenue", "FY2026"): D(5), ("sga", "FY2026"): D(5)}

    table = extend_table(_income(), [_fy(2026, True)], values)

    assert table.rows[1].yoy[-1] is None  # sga FY2025 is null


def test_forecast_common_size_divides_by_the_forecast_revenue() -> None:
    values = {("revenue", "FY2026"): D(200), ("sga", "FY2026"): D(30)}

    table = extend_table(_income(), [_fy(2026, True)], values)

    assert table.rows[0].common_size[-1] == D("1.000000")
    assert table.rows[1].common_size[-1] == D("0.150000")
    assert table.rows[1].common_size[:2] == [D(1), None]  # history kept as built


def test_common_size_is_null_without_a_forecast_base() -> None:
    table = extend_table(_income(), [_fy(2026, True)], {("sga", "FY2026"): D(30)})

    assert table.rows[1].common_size[-1] is None


def _balance_sheet() -> StatementTable:
    periods = [_fy(2025)]
    rows = [
        Row(code, code, "USD", "instant", 0, [D(v)], ["reported"], [None], [None])
        for code, v in (
            ("total_assets", 100),
            ("total_liabilities", 60),
            ("total_equity", 40),
        )
    ]
    return StatementTable("BS", "annual", periods, rows, [BalanceCheck("FY2025", D(0), True)], [])


def test_a_balance_sheet_gets_the_check_of_each_forecast_column() -> None:
    values = {
        ("total_assets", "FY2026"): D(150),
        ("total_liabilities", "FY2026"): D(70),
        ("total_equity", "FY2026"): D(70),
        ("temporary_equity", "FY2026"): D(10),
        ("total_assets", "FY2027"): D(200),
        ("total_liabilities", "FY2027"): D(100),
        ("total_equity", "FY2027"): D(90),
    }

    table = extend_table(_balance_sheet(), [_fy(2026, True), _fy(2027, True)], values)

    assert table.balance_check == [
        BalanceCheck("FY2025", D(0), True),
        BalanceCheck("FY2026", D(0), True),
        BalanceCheck("FY2027", D(10), True),  # within the 1,000,000 USD floor
    ]
    assert table.rows[0].common_size[1:] == [D("1.000000"), D("1.000000")]


def test_an_income_statement_gets_no_balance_check() -> None:
    assert extend_table(_income(), [_fy(2026, True)], {}).balance_check is None


def test_select_periods_keeps_the_listed_columns_aligned() -> None:
    table = extend_table(_balance_sheet(), [_fy(2026, True)], {("total_assets", "FY2026"): D(1)})

    picked = select_periods(table, ["FY2026"])

    assert [p.key for p in picked.periods] == ["FY2026"]
    assert picked.rows[0].values == [D(1)]
    assert picked.rows[0].provenance == ["forecast"]
    assert [c.period_key for c in picked.balance_check or []] == ["FY2026"]


def test_select_periods_with_no_keys_gives_no_columns() -> None:
    picked = select_periods(_income(), [])

    assert picked.periods == []
    assert all(r.values == [] for r in picked.rows)
