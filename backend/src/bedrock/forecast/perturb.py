"""Moving one driver for a sensitivity run (docs/erd/valuation.md "Sensitivity" → Driver shift).
Pure."""

from dataclasses import replace
from decimal import Decimal
from typing import Literal

from bedrock.forecast.drivers import Bounds, driver_def
from bedrock.forecast.resolve import Resolved, ResolvedDrivers

ShiftMode = Literal["add", "scale"]
INWARD = Decimal("1e-6")  # how far inside an open bound a clamped value lands


def shift(
    drivers: ResolvedDrivers, code: str, step: Decimal, mode: ShiftMode, sign: int
) -> ResolvedDrivers:
    """A copy of `drivers` with every numeric value of `code`, years and `quarter_values`, moved
    by sign × step (`add`) or by the factor 1 + sign × step (`scale`), then clamped to the
    driver's bounds. `Flat` and `None` stay; sources stay. A follower of `code` does not move
    (its value is already resolved). Raises UnknownDriver."""
    bounds = driver_def(code).bounds

    def moved(resolved: Resolved) -> Resolved:
        if not isinstance(resolved.value, Decimal):
            return resolved
        value = (
            resolved.value + sign * step if mode == "add" else resolved.value * (1 + sign * step)
        )
        return Resolved(_clamp(value, bounds), resolved.source)

    return replace(
        drivers,
        values={k: moved(v) if k[0] == code else v for k, v in drivers.values.items()},
        quarter_values={
            k: moved(v) if k[0] == code else v for k, v in drivers.quarter_values.items()
        },
    )


def _clamp(value: Decimal, bounds: Bounds) -> Decimal:
    if bounds.contains(value):
        return value
    if value <= bounds.low:
        return bounds.low + INWARD if bounds.low_open else bounds.low
    return bounds.high - INWARD if bounds.high_open else bounds.high
