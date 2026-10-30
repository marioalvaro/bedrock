"""What an import breaks in the periods it touched: the balance check and the cash roll-forward of
`integrity_warnings` (FR-DATA-15), on hand-built cells."""

from decimal import Decimal

from bedrock.statements.cell_types import Cell, CellKey
from bedrock.statements.imports import integrity_warnings

M = Decimal(1_000_000)


def _cells(key: str, values: dict[str, int]) -> dict[CellKey, Cell]:
    return {(code, key): Cell(Decimal(v) * M, "imported") for code, v in values.items()}


CASH = {"cfo": 100, "cfi": -30, "cff": -20, "fx_effect": 0}


def test_a_cash_flow_that_does_not_roll_forward_is_a_warning_with_its_difference() -> None:
    cells = _cells("FY2006", {**CASH, "net_change_in_cash": 60})

    assert integrity_warnings(cells, [], ["FY2006"]) == [
        "FY2006: the cash flow does not roll forward (difference 10,000,000)"
    ]


def test_a_cash_flow_within_the_tolerance_rolls_forward() -> None:
    cells = _cells("FY2006", {**CASH, "net_change_in_cash": 50})
    cells[("net_change_in_cash", "FY2006")] = Cell(Decimal(50_999_999), "imported")  # 1M floor

    assert integrity_warnings(cells, [], ["FY2006"]) == []


def test_a_cash_flow_missing_a_term_is_not_checked() -> None:
    cells = _cells("FY2006", {"cfo": 100, "cfi": -30, "cff": -20, "net_change_in_cash": 60})

    assert integrity_warnings(cells, [], ["FY2006"]) == []


def test_temporary_equity_counts_in_the_balance_check() -> None:
    sheet = {"total_assets": 100, "total_liabilities": 40, "total_equity": 50}
    with_temporary = _cells("FY2006", {**sheet, "temporary_equity": 10})

    assert integrity_warnings(with_temporary, ["FY2006"], []) == []
    assert integrity_warnings(_cells("FY2006", sheet), ["FY2006"], []) == [
        "FY2006: the balance sheet does not balance (difference 10,000,000)"
    ]


def test_only_the_touched_periods_are_checked() -> None:
    cells = _cells("FY2006", {**CASH, "net_change_in_cash": 60})

    assert integrity_warnings(cells, [], ["FY2007"]) == []
