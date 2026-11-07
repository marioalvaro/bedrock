"""Moving one driver for a sensitivity run (docs/erd/valuation.md "Sensitivity" → Driver shift).
Pure."""

from dataclasses import replace
from decimal import Decimal
from typing import Literal

from bedrock.forecast.drivers import clamp, driver_def
from bedrock.forecast.resolve import Resolved, ResolvedDrivers

ShiftMode = Literal["add", "scale"]


def shift(
    drivers: ResolvedDrivers, code: str, step: Decimal, mode: ShiftMode, sign: int
) -> ResolvedDrivers:
    """A copy of `drivers` with every numeric value of `code`, years and `quarter_values`, moved
    by sign × step (`add`) or by the factor 1 + sign × step (`scale`), then clamped to the
    driver's bounds. `Flat` and `None` stay; sources stay. A follower of `code` does not move
    (its value is already resolved). Raises UnknownDriver."""
    driver_def(code)  # an unknown code raises before anything moves

    def moved(resolved: Resolved) -> Resolved:
        if not isinstance(resolved.value, Decimal):
            return resolved
        value = (
            resolved.value + sign * step if mode == "add" else resolved.value * (1 + sign * step)
        )
        return Resolved(clamp(code, value), resolved.source)

    return replace(
        drivers,
        values={k: moved(v) if k[0] == code else v for k, v in drivers.values.items()},
        quarter_values={
            k: moved(v) if k[0] == code else v for k, v in drivers.quarter_values.items()
        },
    )
