"""Sensitivity of the DCF value per share: the inputs moved, the tornado and the 2-D grid
(docs/erd/valuation.md "Sensitivity (orig. §5.2, M5)"). Pure: the caller evaluates a point
through a callback (the service re-runs the model and the DCF), so nothing here imports a model,
a service or the database."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.forecast.drivers import Unit, driver_def
from bedrock.forecast.perturb import ShiftMode
from bedrock.forecast.resolve import ResolvedDrivers
from bedrock.valuation.inputs import InputValue, ResolvedInputs
from bedrock.valuation.interface import upside

SensitivityKind = Literal["driver", "valuation"]
# A point's value per share, or the error text of a run that cannot value.
Outcome = Decimal | str
GRID_STEPS = (-2, -1, 0, 1, 2)
# User decision 2026-11-06: unit steps.
DRIVER_STEPS: dict[Unit, tuple[Decimal, ShiftMode]] = {
    "pct": (Decimal("0.01"), "add"),
    "days": (Decimal(5), "add"),
    "USD": (Decimal("0.1"), "scale"),
}


@dataclass(frozen=True)
class SensitivityInput:
    code: str
    label: str
    kind: SensitivityKind
    unit: str  # pct | days | USD | x
    step: Decimal
    mode: ShiftMode


RATE = SensitivityInput(
    "discount_rate", "Discount rate", "valuation", "pct", Decimal("0.005"), "add"
)
GROWTH = SensitivityInput(
    "terminal_growth", "Terminal growth", "valuation", "pct", Decimal("0.005"), "add"
)
EXIT = SensitivityInput("exit_multiple", "Exit multiple", "valuation", "x", Decimal(1), "add")


def sensitivity_inputs(
    drivers: ResolvedDrivers, labels: Mapping[str, str], inputs: ResolvedInputs
) -> list[SensitivityInput]:
    """Every driver of the resolution (its order) with a number in at least one forecast year or
    quarter, stepped by its unit; then the discount rate, and terminal growth (`gordon`) or the
    exit multiple (`exit_multiple`). A label missing from `labels` is the catalog's."""
    found = []
    for code in drivers.codes:
        values = [drivers.values[(code, y)].value for y in drivers.years]
        values += [v.value for k, v in drivers.quarter_values.items() if k[0] == code]
        if not any(isinstance(v, Decimal) for v in values):
            continue
        d = driver_def(code)
        step, mode = DRIVER_STEPS[d.unit]
        found.append(
            SensitivityInput(code, labels.get(code, d.label), "driver", d.unit, step, mode)
        )
    found.append(RATE)
    found.append(EXIT if inputs.get("terminal_method") == "exit_multiple" else GROWTH)
    return found


def shift_amount(item: SensitivityInput, k: int) -> Decimal:
    """k × step: an amount (`add`) or a relative change (`scale`)."""
    return k * item.step


def point(item: SensitivityInput, base: Decimal, k: int) -> Decimal:
    """The input's value k steps from `base`."""
    if item.mode == "scale":
        return base * (1 + shift_amount(item, k))
    return base + shift_amount(item, k)


def valuation_inputs_at(
    inputs: ResolvedInputs, rate: Decimal, item: SensitivityInput, k: int
) -> ResolvedInputs:
    """The inputs with a valuation input moved k steps, everything else (derived inputs
    included) held: the discount rate moves the rate `rate` itself (a direct rate, whether the
    base is WACC or direct); growth and the exit multiple move from their resolved values."""
    values: dict[str, InputValue]
    if item.code == RATE.code:
        values = {"discount_method": "direct", "discount_rate": point(item, rate, k)}
    else:
        base = inputs.get(item.code)
        if not isinstance(base, Decimal):
            raise ValueError(f"{item.code} has no value")
        values = {item.code: point(item, base, k)}
    return inputs.with_values(values)


@dataclass(frozen=True)
class TornadoBar:
    code: str
    label: str
    kind: SensitivityKind
    unit: str
    step: Decimal
    mode: ShiftMode
    low_value: Decimal | None
    high_value: Decimal | None
    low_change: Decimal | None
    high_change: Decimal | None
    range: Decimal | None
    error: str | None


def tornado(
    base_value: Decimal,
    inputs: Sequence[SensitivityInput],
    evaluate: Callable[[SensitivityInput, int], Outcome],
) -> list[TornadoBar]:
    """Each input at sign −1 (low) and +1 (high). A failed side has null numbers and the bar a
    null range and the first error text. Sorted by range descending, nulls last, ties in input
    order."""
    bars = []
    for item in inputs:
        low, high = evaluate(item, -1), evaluate(item, 1)
        errors = [o for o in (low, high) if isinstance(o, str)]
        low_value = low if isinstance(low, Decimal) else None
        high_value = high if isinstance(high, Decimal) else None
        bars.append(
            TornadoBar(
                code=item.code,
                label=item.label,
                kind=item.kind,
                unit=item.unit,
                step=item.step,
                mode=item.mode,
                low_value=low_value,
                high_value=high_value,
                low_change=None if low_value is None else low_value - base_value,
                high_change=None if high_value is None else high_value - base_value,
                range=(
                    abs(high_value - low_value)
                    if low_value is not None and high_value is not None
                    else None
                ),
                error=errors[0] if errors else None,
            )
        )
    return sorted(bars, key=lambda b: (b.range is None, -(b.range or 0)))


Matrix = tuple[tuple[Decimal | None, ...], ...]


@dataclass(frozen=True)
class SensitivityGrid:
    x: SensitivityInput
    y: SensitivityInput
    x_shifts: tuple[Decimal, ...]
    y_shifts: tuple[Decimal, ...]
    values: Matrix  # [y point][x point]
    upside: Matrix
    errors: tuple[tuple[str | None, ...], ...]


def grid(
    x: SensitivityInput,
    y: SensitivityInput,
    base_value: Decimal,
    price: Decimal | None,
    evaluate: Callable[[int, int], Outcome],
) -> SensitivityGrid:
    """5 × 5 points, k ∈ (−2..2) steps on each axis; `evaluate(kx, ky)` values a point. Rows are
    y. The center is `base_value` (not re-evaluated); a failed point is null with its text."""
    values: list[tuple[Decimal | None, ...]] = []
    errors: list[tuple[str | None, ...]] = []
    for ky in GRID_STEPS:
        row: list[Decimal | None] = []
        row_errors: list[str | None] = []
        for kx in GRID_STEPS:
            outcome = base_value if kx == ky == 0 else evaluate(kx, ky)
            row.append(outcome if isinstance(outcome, Decimal) else None)
            row_errors.append(outcome if isinstance(outcome, str) else None)
        values.append(tuple(row))
        errors.append(tuple(row_errors))
    return SensitivityGrid(
        x=x,
        y=y,
        x_shifts=tuple(shift_amount(x, k) for k in GRID_STEPS),
        y_shifts=tuple(shift_amount(y, k) for k in GRID_STEPS),
        values=tuple(values),
        upside=tuple(tuple(upside(v, price) for v in row) for row in values),
        errors=tuple(errors),
    )
