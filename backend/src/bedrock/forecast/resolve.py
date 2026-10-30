"""Driver resolution: a scenario's value of each driver for each forecast year, and where it came
from (docs/erd/forecasting.md "Scenarios (M4)" → Resolution). Pure."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.forecast.drivers import DriverKind, Follows, check_bounds
from bedrock.forecast.history import FLAT, Default, Flat

Source = Literal["own", "offset", "base", "default"]
Value = Decimal | None | Flat


@dataclass(frozen=True)
class DriverRow:
    """A stored driver of one scenario (a `driver_value` row, its value already plain)."""

    code: str
    fiscal_year: int
    kind: DriverKind
    value: Decimal


@dataclass(frozen=True)
class Resolved:
    value: Value  # None: a required driver nothing sets
    source: Source | None  # None with a None value


@dataclass(frozen=True)
class ResolvedDrivers:
    codes: tuple[str, ...]  # catalog order
    years: tuple[int, ...]
    values: Mapping[tuple[str, int], Resolved]
    warnings: tuple[str, ...]
    following: frozenset[str]  # drivers whose default follows another driver

    def get(self, code: str, year: int) -> Resolved:
        """Raises KeyError for a driver or year the resolution does not cover."""
        return self.values[(code, year)]

    def missing_required(self) -> list[str]:
        """The drivers with no value in some forecast year, in catalog order. A driver that
        follows another one is left out: setting the followed driver fills it."""
        return [
            code
            for code in self.codes
            if code not in self.following
            and any(self.values[(code, y)].value is None for y in self.years)
        ]

    def out_of_bounds(self) -> list[tuple[str, int, str]]:
        """(code, year, message) of every resolved value outside its driver's bounds."""
        found = []
        for code in self.codes:
            for year in self.years:
                value = self.values[(code, year)].value
                if isinstance(value, Decimal):
                    message = check_bounds(code, "value", value)
                    if message is not None:
                        found.append((code, year, message))
        return found


def resolve_drivers(
    base_rows: Sequence[DriverRow],
    own_rows: Sequence[DriverRow],
    defaults: Mapping[str, Default],
    years: Sequence[int],
    is_base: bool,
) -> ResolvedDrivers:
    """For each driver of `defaults` and forecast year: the scenario's `value` row → else Base's
    resolved value + the scenario's `offset` row → else Base's `value` row → else the default.
    Base itself takes its `value` row, else the default. A default that follows another driver
    takes that driver's resolved value in the same scenario. Rows of other years are ignored.
    Raises ValueError for an offset on Base."""
    if is_base and any(r.kind == "offset" for r in own_rows):
        raise ValueError("Base cannot hold an offset")
    wanted = tuple(years)
    warnings: list[str] = []
    base = None if is_base else _resolve(base_rows, defaults, wanted, None, warnings)
    values = _resolve(own_rows, defaults, wanted, base, warnings)
    return ResolvedDrivers(
        tuple(defaults),
        wanted,
        values,
        tuple(warnings),
        frozenset(c for c, d in defaults.items() if isinstance(d, Follows)),
    )


def _resolve(
    rows: Sequence[DriverRow],
    defaults: Mapping[str, Default],
    years: tuple[int, ...],
    base: Mapping[tuple[str, int], Resolved] | None,
    warnings: list[str],
) -> dict[tuple[str, int], Resolved]:
    stored = {(r.code, r.fiscal_year): r for r in rows if r.fiscal_year in years}
    values: dict[tuple[str, int], Resolved] = {}
    follows: list[tuple[str, int, Follows]] = []
    for code, default in defaults.items():
        for year in years:
            own = stored.get((code, year))
            inherited = None if base is None else base[(code, year)]
            if own is not None and own.kind == "value":
                values[(code, year)] = Resolved(own.value, "own")
            elif own is not None and inherited is not None:
                values[(code, year)] = _offset(code, year, inherited.value, own.value, warnings)
            elif inherited is not None and inherited.source == "own":
                values[(code, year)] = Resolved(inherited.value, "base")
            elif isinstance(default, Follows):
                follows.append((code, year, default))
            else:
                values[(code, year)] = _default(default)
    for code, year, follow in follows:
        target = values.get((follow.code, year), Resolved(None, None)).value
        values[(code, year)] = _default(target)
    return values


def _offset(
    code: str, year: int, inherited: Value, offset: Decimal, warnings: list[str]
) -> Resolved:
    if inherited is FLAT:
        warnings.append(f"{code} FY{year}: the offset is ignored, Base holds the line flat")
        return Resolved(FLAT, "default")
    if inherited is None:
        return Resolved(None, None)
    return Resolved(inherited + offset, "offset")


def _default(value: Value | Follows) -> Resolved:
    if value is None or isinstance(value, Follows):
        return Resolved(None, None)
    return Resolved(value, "default")
