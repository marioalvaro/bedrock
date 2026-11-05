"""Driver resolution: a scenario's value of each driver for each forecast year and quarter, and
where it came from (docs/erd/forecasting.md "Scenarios (M4)" → Resolution, "Quarterly drivers" →
Resolution). Pure."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from bedrock.forecast.drivers import QUARTERS, DriverKind, Follows, check_bounds, quarter_share
from bedrock.forecast.history import FLAT, Default, Flat

# `year`: a quarter that has no row takes its year's resolved value.
Source = Literal["own", "offset", "base", "default", "year"]
Value = Decimal | None | Flat


@dataclass(frozen=True)
class DriverRow:
    """A stored driver of one scenario (a `driver_value` row, its value already plain): a year's
    (`fiscal_period` FY) or one quarter's (`Q1`..`Q4`; a USD flow is then the quarter's amount)."""

    code: str
    fiscal_year: int
    kind: DriverKind
    value: Decimal
    fiscal_period: str = "FY"


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
    # (code, year, "Q1".."Q4") -> the quarter's value. A USD flow (`FLOW_AMOUNTS`) is the quarter's
    # amount, not the year's. Empty for a resolution built by hand: `get` then derives it.
    quarter_values: Mapping[tuple[str, int, str], Resolved] = field(default_factory=dict)

    def get(self, code: str, year: int, period: str = "FY") -> Resolved:
        """The value of a year (`period` FY) or of one of its quarters. A quarter with no entry
        takes its year's value (source `year`). Raises KeyError for a driver, year or period the
        resolution does not cover."""
        annual = self.values[(code, year)]
        if period == "FY":
            return annual
        if period not in QUARTERS:
            raise KeyError(period)
        return self.quarter_values.get((code, year, period)) or _from_year(code, annual)

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

    def out_of_bounds_quarters(self) -> list[tuple[str, int, str, str]]:
        """(code, year, quarter, message) of every quarter value outside its driver's bounds
        although its year's value is inside (a year outside is in `out_of_bounds`)."""
        found = []
        for (code, year, period), resolved in self.quarter_values.items():
            if not isinstance(resolved.value, Decimal):
                continue
            annual = self.values[(code, year)].value
            if isinstance(annual, Decimal) and check_bounds(code, "value", annual) is not None:
                continue
            message = check_bounds(code, "value", resolved.value)
            if message is not None:
                found.append((code, year, period, message))
        return found


def resolve_drivers(
    base_rows: Sequence[DriverRow],
    own_rows: Sequence[DriverRow],
    defaults: Mapping[str, Default],
    years: Sequence[int],
    is_base: bool,
    quarterly_years: Collection[int] = frozenset(),
) -> ResolvedDrivers:
    """For each driver of `defaults` and forecast year: the scenario's `value` row → else Base's
    resolved value + the scenario's `offset` row → else Base's `value` row → else the default.
    Base itself takes its `value` row, else the default. A default that follows another driver
    takes that driver's resolved value in the same scenario. Rows of other years are ignored.
    Quarters follow the five-step chain of the ERD's "Quarterly drivers" (`_quarters`): the
    scenario's quarter row, its quarter offset on Base's quarter, its annual offset on Base's
    quarter, Base's quarter row, the year's resolved value. In a year of `quarterly_years` (set by
    quarter, docs "Year modes") the quarters ignore every annual row, the case's and Base's: steps
    3 and 5 read the year as if it had none (the default, or what Base inherits), with that
    source; the year's own value stays as stored. Raises ValueError for an offset on Base."""
    if is_base and any(r.kind == "offset" for r in own_rows):
        raise ValueError("Base cannot hold an offset")
    wanted = tuple(years)
    warnings: list[str] = []
    year_rows = [r for r in base_rows if r.fiscal_period == "FY"]
    base = None if is_base else _resolve(year_rows, defaults, wanted, None, warnings)
    own_years = [r for r in own_rows if r.fiscal_period == "FY"]
    values = _resolve(own_years, defaults, wanted, base, warnings)
    by_quarter = frozenset(quarterly_years) & frozenset(wanted)
    if by_quarter:
        # the years as they resolve with no annual row in a year set by quarter
        scratch: list[str] = []
        free_base = (
            None
            if is_base
            else _resolve(
                [r for r in year_rows if r.fiscal_year not in by_quarter],
                defaults,
                wanted,
                None,
                scratch,
            )
        )
        free = _resolve(
            [r for r in own_years if r.fiscal_year not in by_quarter],
            defaults,
            wanted,
            free_base,
            scratch,
        )
        quarter_years = {**values, **{k: v for k, v in free.items() if k[1] in by_quarter}}
        quarter_base = (
            None
            if base is None or free_base is None
            else {**base, **{k: v for k, v in free_base.items() if k[1] in by_quarter}}
        )
    else:
        quarter_years, quarter_base = values, base
    quarters = _quarters(
        {k: r for r in own_rows if (k := _quarter_key(r)) is not None},
        {k: r for r in base_rows if (k := _quarter_key(r)) is not None},
        {(r.code, r.fiscal_year): r for r in own_years if r.fiscal_year not in by_quarter},
        quarter_years,
        quarter_base,
        defaults,
        wanted,
        warnings,
        by_quarter,
    )
    return ResolvedDrivers(
        tuple(defaults),
        wanted,
        values,
        tuple(warnings),
        frozenset(c for c, d in defaults.items() if isinstance(d, Follows)),
        quarters,
    )


def _quarter_key(row: DriverRow) -> tuple[str, int, str] | None:
    return None if row.fiscal_period == "FY" else (row.code, row.fiscal_year, row.fiscal_period)


def _quarters(
    own_quarters: Mapping[tuple[str, int, str], DriverRow],
    base_quarters: Mapping[tuple[str, int, str], DriverRow],
    own_years: Mapping[tuple[str, int], DriverRow],
    values: Mapping[tuple[str, int], Resolved],
    base: Mapping[tuple[str, int], Resolved] | None,
    defaults: Mapping[str, Default],
    years: tuple[int, ...],
    warnings: list[str],
    by_quarter: frozenset[int],
) -> dict[tuple[str, int, str], Resolved]:
    """Every quarter of every forecast year, first rule that applies: (1) the scenario's value at
    the quarter → `own`; (2) its offset at the quarter → Base's quarter + the offset (`offset`);
    (3) its annual offset → Base's quarter + the offset (`offset`); (4) Base's value at the quarter
    → `base`; (5) the year's resolved value → `year`. "Base's quarter" is Base's row at the quarter
    else Base's year. A USD flow works in quarter amounts: a year's amount counts for a quarter
    × `quarter_share`, a quarter row as it is. In a year of `by_quarter` step 5 keeps the source
    of the year's value (`default`, `base`): the year has no annual value of its own there."""
    resolved: dict[tuple[str, int, str], Resolved] = {}
    scratch: list[str] = []  # an annual offset on a flat line already warned at the year
    for code in defaults:
        share = quarter_share(code)
        for year in years:
            annual = values[(code, year)]
            base_year = None if base is None else base[(code, year)]
            for period in QUARTERS:
                key = (code, year, period)
                own, inherited = own_quarters.get(key), base_quarters.get(key)
                if base_year is None:  # Base itself
                    baseline = None
                elif inherited is not None:
                    baseline = Resolved(inherited.value, "base")
                else:
                    baseline = _from_year(code, base_year)
                annual_row = own_years.get((code, year))
                if own is not None and own.kind == "value":
                    resolved[key] = Resolved(own.value, "own")
                elif own is not None and baseline is not None:
                    resolved[key] = _offset(
                        f"{code} {period} FY{year}", baseline.value, own.value, warnings
                    )
                elif (
                    annual_row is not None and annual_row.kind == "offset" and baseline is not None
                ):
                    resolved[key] = _offset(
                        f"{code} FY{year}", baseline.value, annual_row.value * share, scratch
                    )
                elif annual_row is not None and annual_row.kind == "value":
                    resolved[key] = Resolved(annual_row.value * share, "year")
                elif baseline is not None and inherited is not None:
                    resolved[key] = baseline
                elif year in by_quarter:
                    resolved[key] = _share(code, annual)
                else:
                    resolved[key] = _from_year(code, annual)
    return resolved


def _share(code: str, annual: Resolved) -> Resolved:
    """A year's value as a quarter's, its source kept (a USD flow: a quarter of the amount)."""
    if not isinstance(annual.value, Decimal):
        return annual
    return Resolved(annual.value * quarter_share(code), annual.source)


def _from_year(code: str, annual: Resolved) -> Resolved:
    """A quarter that takes its year's value: a quarter of a USD flow, the year's number
    otherwise; a missing or flat year stays so."""
    if not isinstance(annual.value, Decimal):
        return annual
    return Resolved(annual.value * quarter_share(code), "year")


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
                values[(code, year)] = _offset(
                    f"{code} FY{year}", inherited.value, own.value, warnings
                )
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


def _offset(label: str, inherited: Value, offset: Decimal, warnings: list[str]) -> Resolved:
    """`label` names the period in the warning, e.g. `gross_margin FY2027`."""
    if inherited is FLAT:
        warnings.append(f"{label}: the offset is ignored, Base holds the line flat")
        return Resolved(FLAT, "default")
    if inherited is None:
        return Resolved(None, None)
    return Resolved(inherited + offset, "offset")


def _default(value: Value | Follows) -> Resolved:
    if value is None or isinstance(value, Follows):
        return Resolved(None, None)
    return Resolved(value, "default")
