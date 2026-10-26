"""The import template, as xlsx or CSV bytes. Pure.

Its layout is the one `manual_import.parse_import` reads (see that module). One row per canonical
item in display order; residual and computed-only rows are grey and left blank, because a value
typed there is ignored. `values` prefills the sheet with the company's displayed values.
"""

import csv
import io
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from bedrock.ingest.manual_import import (
    COLUMN_TITLES,
    FIRST_PERIOD,
    HEADER_ROWS,
    INSTRUCTIONS,
    SCALES,
    VALUE_PLACES,
)
from bedrock.mapping.config import STATEMENTS, CanonicalItemDef
from bedrock.statements.periods import Period

GREY = PatternFill("solid", fgColor="D9D9D9")
BOLD = Font(bold=True)

_INSTRUCTIONS = (
    "Fill the IS, BS and CF sheets; leave a cell blank when you have no value.",
    "Values are in the scale below, for USD amounts and share counts. Per-share values (EPS, "
    "dividends per share) are never scaled. Currency is USD.",
    "Sign convention: type values as the statements display them (capex, buybacks, dividends "
    "paid and debt repaid are negative).",
    "Grey rows are computed from other lines; a value typed there is ignored.",
    "To break a line down, add a row at the bottom of its sheet with a label and the line's code "
    "in the parent column (a canonical line with no lines of its own, or an earlier custom "
    "line); leave the code blank or start it with 'custom:'. The unit is the parent's. Set "
    "children_complete to TRUE on the parent's row when the new lines are its whole breakdown: "
    "an empty parent then becomes their sum.",
    "An import only fills cells the SEC data leaves empty. A period column needs its fiscal_year, "
    "fiscal_period (FY, Q1..Q4), period_start and period_end (YYYY-MM-DD); add columns to the "
    "right for years or quarters that are missing.",
)


def build_template(
    items: Sequence[CanonicalItemDef],
    periods: Sequence[Period],
    fmt: Literal["xlsx", "csv"],
    scale: str,
    values: Mapping[tuple[str, str], Decimal] | None = None,
) -> bytes:
    """The template for `periods` (the company's, oldest first). `values` maps (code, period key)
    to the displayed value in units; it is written divided by the scale (per-share values as
    they are). Raises ValueError for an unknown scale."""
    if scale not in SCALES:
        raise ValueError(f"Unknown scale '{scale}'")
    sheets = {s: _rows(items, periods, s, scale, values or {}) for s in STATEMENTS}
    return _xlsx(sheets, items, scale) if fmt == "xlsx" else _csv(sheets, scale)


def _is_read_only(item: CanonicalItemDef) -> bool:
    return item.residual or (item.derive is not None and not item.concepts)


def _rows(
    items: Sequence[CanonicalItemDef],
    periods: Sequence[Period],
    statement: str,
    scale: str,
    values: Mapping[tuple[str, str], Decimal],
) -> list[list[Any]]:
    pad: list[Any] = [None] * (FIRST_PERIOD - 1)
    columns: dict[str, list[Any]] = {
        "fiscal_year": [p.fiscal_year for p in periods],
        "fiscal_period": [p.fiscal_period for p in periods],
        "period_start": [p.start.isoformat() for p in periods],
        "period_end": [p.end.isoformat() for p in periods],
    }
    rows: list[list[Any]] = [[name, *pad, *columns[name]] for name in HEADER_ROWS]
    rows.append([*COLUMN_TITLES, *(p.label for p in periods)])
    for item in items:
        if item.statement != statement:
            continue
        divisor = Decimal(SCALES[scale]) if item.unit in ("USD", "shares") else Decimal(1)
        cells = [
            None
            if _is_read_only(item) or (item.code, p.key) not in values
            else _number(values[(item.code, p.key)] / divisor)
            for p in periods
        ]
        rows.append([item.code, item.label, item.parent, item.unit, None, *cells])
    return rows


def _number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(round(value, VALUE_PLACES))


def _xlsx(
    sheets: Mapping[str, list[list[Any]]], items: Sequence[CanonicalItemDef], scale: str
) -> bytes:
    book = Workbook()
    guide = book.active
    assert guide is not None
    guide.title = INSTRUCTIONS
    guide.append(["scale", scale])
    guide.append([])
    for line in _INSTRUCTIONS:
        guide.append([line])
    guide.column_dimensions["A"].width = 18
    read_only = {i.code for i in items if _is_read_only(i)}
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
        for number, row in enumerate(rows, start=1):
            if number <= len(HEADER_ROWS) + 1:
                for cell in sheet[number]:
                    cell.font = BOLD
            elif row[0] in read_only:
                for cell in sheet[number][: len(rows[0])]:
                    cell.fill = GREY
        sheet.freeze_panes = sheet.cell(row=len(HEADER_ROWS) + 2, column=FIRST_PERIOD + 1)
        sheet.column_dimensions["A"].width = 28
        sheet.column_dimensions["B"].width = 38
        for index in range(FIRST_PERIOD + 1, len(rows[0]) + 1):
            sheet.column_dimensions[get_column_letter(index)].width = 14
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _csv(sheets: Mapping[str, list[list[Any]]], scale: str) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["scale", scale])
    for name, rows in sheets.items():
        for row in rows:
            writer.writerow([name, *("" if cell is None else cell for cell in row)])
    return out.getvalue().encode()
