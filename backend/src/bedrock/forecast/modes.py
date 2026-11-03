"""Year modes: the quarter rows a switch to "by quarter" writes (docs/erd/forecasting.md "Year
modes"). Pure."""

from collections.abc import Sequence
from decimal import Decimal

from bedrock.forecast.drivers import driver_def, quarter_share
from bedrock.forecast.resolve import DriverRow, ResolvedDrivers


def fill_quarters(
    year: int,
    quarters: Sequence[str],
    resolved: ResolvedDrivers,
    own_rows: Sequence[DriverRow],
    is_base: bool,
) -> list[DriverRow]:
    """The quarter rows of `year` that leave a case's forecast as it is, for the year's forecast
    `quarters` (a year in progress has actual ones too): for each quarter-capable
    driver with a number for the year, a `value` row per quarter holding what that quarter
    resolves to (Base), or, for Bull and Bear, rows only where the case has its own annual row: a
    `value` per quarter, or the annual `offset` (a USD flow's split in four) per quarter. A
    quarter that already has a row keeps it. `resolved` is the case's resolution before the fill,
    `own_rows` its stored rows."""
    annual = {r.code: r for r in own_rows if r.fiscal_year == year and r.fiscal_period == "FY"}
    taken = {(r.code, r.fiscal_period) for r in own_rows if r.fiscal_year == year}
    rows: list[DriverRow] = []
    for code in resolved.codes:
        if not driver_def(code).quarterly:
            continue
        if not isinstance(resolved.get(code, year).value, Decimal):  # flat, or nothing sets it
            continue
        row = annual.get(code)
        if row is None and not is_base:  # the case follows Base's quarters
            continue
        for quarter in quarters:
            if (code, quarter) in taken:
                continue
            if row is not None and row.kind == "offset":
                offset = row.value * quarter_share(code)
                rows.append(DriverRow(code, year, "offset", offset, quarter))
                continue
            value = resolved.get(code, year, quarter).value
            if isinstance(value, Decimal):
                rows.append(DriverRow(code, year, "value", value, quarter))
    return rows
