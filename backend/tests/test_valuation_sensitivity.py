"""Sensitivity: the inputs list, the tornado and the 2-D grid (docs/erd/valuation.md
"Sensitivity", FR-VAL-04). Pure: evaluation comes in through callbacks."""

from decimal import Decimal

import pytest

from bedrock.forecast.history import FLAT, Flat
from bedrock.forecast.perturb import ShiftMode
from bedrock.forecast.resolve import Resolved, ResolvedDrivers
from bedrock.valuation.inputs import ResolvedInputs, resolve_inputs
from bedrock.valuation.sensitivity import (
    SensitivityInput,
    grid,
    point,
    sensitivity_inputs,
    tornado,
    valuation_inputs_at,
)

D = Decimal
YEARS = (2026, 2027)


def _drivers() -> ResolvedDrivers:
    by_code: dict[str, tuple[Decimal | Flat | None, Decimal | Flat | None]] = {
        "revenue_growth": (D("0.05"), D("0.04")),
        "gross_margin": (None, None),  # nothing sets it
        "receivable_days": (D(40), D(41)),
        "payable_days": (FLAT, FLAT),
        "inventory_days": (FLAT, D(30)),  # a number in one year is enough
        "buybacks": (D(100), D(100)),
    }
    values = {}
    for code, pair in by_code.items():
        for year, value in zip(YEARS, pair, strict=True):
            values[(code, year)] = Resolved(value, None if value is None else "default")
    return ResolvedDrivers(tuple(by_code), YEARS, values, (), frozenset())


LABELS = {"revenue_growth": "Revenue growth", "receivable_days": "Receivable days"}


def _inputs(**texts: str) -> ResolvedInputs:
    return resolve_inputs({}, texts, is_base=True, derived={})


def test_inputs_list_drivers_with_a_number_by_unit_then_the_valuation_inputs() -> None:
    found = sensitivity_inputs(_drivers(), LABELS, _inputs())
    assert found == [
        SensitivityInput("revenue_growth", "Revenue growth", "driver", "pct", D("0.01"), "add"),
        SensitivityInput("receivable_days", "Receivable days", "driver", "days", D(5), "add"),
        SensitivityInput("inventory_days", "Inventory days", "driver", "days", D(5), "add"),
        SensitivityInput("buybacks", "Buybacks", "driver", "USD", D("0.1"), "scale"),
        SensitivityInput("discount_rate", "Discount rate", "valuation", "pct", D("0.005"), "add"),
        SensitivityInput(
            "terminal_growth", "Terminal growth", "valuation", "pct", D("0.005"), "add"
        ),
    ]


def test_an_exit_multiple_run_moves_the_multiple_instead_of_growth() -> None:
    found = sensitivity_inputs(_drivers(), LABELS, _inputs(terminal_method="exit_multiple"))
    assert [i.code for i in found][-2:] == ["discount_rate", "exit_multiple"]
    assert found[-1] == SensitivityInput(
        "exit_multiple", "Exit multiple", "valuation", "x", D(1), "add"
    )


def test_a_driver_with_a_number_only_in_a_quarter_counts() -> None:
    values = {("buybacks", y): Resolved(FLAT, "default") for y in YEARS}
    quarters = {("buybacks", 2026, "Q2"): Resolved(D(5), "own")}
    drivers = ResolvedDrivers(("buybacks",), YEARS, values, (), frozenset(), quarters)
    assert [i.code for i in sensitivity_inputs(drivers, {}, _inputs())][0] == "buybacks"


def _input(code: str, step: str = "0.01", mode: ShiftMode = "add") -> SensitivityInput:
    return SensitivityInput(code, code.title(), "driver", "pct", D(step), mode)


def test_the_tornado_sorts_by_range_with_ties_in_input_order() -> None:
    inputs = [_input("a"), _input("b"), _input("c"), _input("d")]
    values = {
        ("a", -1): D(95), ("a", 1): D(105),  # range 10
        ("b", -1): D(80), ("b", 1): D(130),  # range 50
        ("c", -1): D(110), ("c", 1): D(100),  # range 10, falls with the input
        ("d", -1): D(90), ("d", 1): D(110),  # range 20
    }  # fmt: skip
    bars = tornado(D(100), inputs, lambda i, sign: values[(i.code, sign)])
    assert [b.code for b in bars] == ["b", "d", "a", "c"]
    c = bars[-1]
    assert (c.low_value, c.high_value, c.low_change, c.high_change, c.range) == (
        D(110), D(100), D(10), D(0), D(10),
    )  # fmt: skip
    assert (c.label, c.kind, c.unit, c.step, c.mode, c.error) == (
        "C", "driver", "pct", D("0.01"), "add", None,
    )  # fmt: skip


def test_an_error_side_is_null_and_the_bar_goes_last() -> None:
    inputs = [_input("bad"), _input("ok"), _input("both")]
    r_le_g = "The discount rate (8.0%) must exceed terminal growth (9.0%)"
    values: dict[tuple[str, int], Decimal | str] = {
        ("bad", -1): D(90), ("bad", 1): r_le_g,
        ("ok", -1): D(99), ("ok", 1): D(101),
        ("both", -1): "first", ("both", 1): "second",
    }  # fmt: skip
    bars = tornado(D(100), inputs, lambda i, sign: values[(i.code, sign)])
    assert [b.code for b in bars] == ["ok", "bad", "both"]
    bad = bars[1]
    assert (bad.low_value, bad.low_change, bad.high_value, bad.high_change, bad.range) == (
        D(90), D(-10), None, None, None,
    )  # fmt: skip
    assert bad.error == r_le_g
    assert bars[2].error == "first"
    assert (bars[2].low_value, bars[2].high_value) == (None, None)


def test_the_tornado_of_no_inputs_is_empty() -> None:
    assert tornado(D(100), [], lambda i, sign: D(0)) == []


def test_the_grid_is_five_by_five_with_rows_on_y_and_the_base_at_the_center() -> None:
    x = SensitivityInput("discount_rate", "Discount rate", "valuation", "pct", D("0.005"), "add")
    y = _input("buybacks", "0.1", "scale")
    calls: list[tuple[int, int]] = []

    def evaluate(kx: int, ky: int) -> Decimal | str:
        calls.append((kx, ky))
        return D(100) + 10 * kx + ky

    out = grid(x, y, D(100), D(50), evaluate)
    assert (out.x, out.y) == (x, y)
    assert out.x_shifts == (D("-0.010"), D("-0.005"), D(0), D("0.005"), D("0.010"))
    assert out.y_shifts == (D("-0.2"), D("-0.1"), D(0), D("0.1"), D("0.2"))
    assert len(out.values) == 5 and all(len(row) == 5 for row in out.values)
    assert out.values[2][2] == D(100)
    assert (0, 0) not in calls  # the center is not re-run
    assert len(calls) == 24
    assert out.values[0][4] == D(100) + 20 - 2  # y k = −2, x k = +2
    assert out.upside[0][4] == D(118) / 50 - 1
    assert out.errors == tuple((None,) * 5 for _ in range(5))


def test_a_failed_grid_point_is_null_with_its_text() -> None:
    x, y = _input("a"), _input("b")
    out = grid(x, y, D(10), None, lambda kx, ky: "r ≤ g" if kx == 2 else D(10))
    assert out.values[1][4] is None and out.errors[1][4] == "r ≤ g"
    assert out.upside[1][4] is None
    assert out.upside[1][1] is None  # no price
    assert out.values[1][3] == D(10) and out.errors[1][3] is None


@pytest.mark.parametrize(
    ("mode", "k", "expected"),
    [
        ("add", -2, D("0.03")),
        ("add", 1, D("0.06")),
        ("scale", 2, D("0.07")),
        ("scale", -1, D("0.04")),
    ],
)
def test_a_point_is_the_base_moved_k_steps(mode: ShiftMode, k: int, expected: Decimal) -> None:
    step = D("0.01") if mode == "add" else D("0.2")
    assert point(_input("a", str(step), mode), D("0.05"), k) == expected


def test_valuation_inputs_at_moves_the_rate_itself_even_under_wacc() -> None:
    inputs = _inputs(cost_of_debt="0.05", tax_rate="0.2", debt_weight="0.1")
    rate = SensitivityInput("discount_rate", "Discount rate", "valuation", "pct", D("0.005"), "add")
    moved = valuation_inputs_at(inputs, D("0.083"), rate, -2)
    assert moved.get("discount_method") == "direct"
    assert moved.get("discount_rate") == D("0.073")
    assert inputs.get("discount_method") == "wacc"


def test_valuation_inputs_at_moves_growth_or_the_exit_multiple() -> None:
    inputs = _inputs(terminal_growth="0.02", exit_multiple="10")
    growth = SensitivityInput(
        "terminal_growth", "Terminal growth", "valuation", "pct", D("0.005"), "add"
    )
    multiple = SensitivityInput("exit_multiple", "Exit multiple", "valuation", "x", D(1), "add")
    assert valuation_inputs_at(inputs, D("0.09"), growth, 1).get("terminal_growth") == D("0.025")
    moved = valuation_inputs_at(inputs, D("0.09"), multiple, 2)
    assert moved.get("exit_multiple") == D(12)
    assert moved.get("discount_method") == "wacc"  # the rate is held
