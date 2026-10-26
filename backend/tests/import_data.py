"""Hand-built import files for the parser and pipeline tests: the template's layout, written
without the template builder so that a parser test never depends on it."""

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from openpyxl import Workbook

# (fiscal_year, fiscal_period, start, end): a 52-week year ending late September, 13-week quarters
FY2006 = (2006, "FY", date(2005, 9, 25), date(2006, 9, 30))
Q1_2006 = (2006, "Q1", date(2005, 9, 25), date(2005, 12, 31))
Q2_2006 = (2006, "Q2", date(2006, 1, 1), date(2006, 4, 1))
Q3_2006 = (2006, "Q3", date(2006, 4, 2), date(2006, 7, 1))
Q4_2006 = (2006, "Q4", date(2006, 7, 2), date(2006, 9, 30))

Period = tuple[int, str, date | None, date | None]
HEADER_ROWS = ("fiscal_year", "fiscal_period", "period_start", "period_end")
TITLES = ["code", "label", "parent", "unit", "children_complete"]


def statement_rows(
    periods: Sequence[Period], lines: Mapping[str, Sequence[Any]] | Sequence[Sequence[Any]]
) -> list[list[Any]]:
    """The four header rows, the column titles and one row per line. `lines` maps a code to its
    values (one per period), or lists complete rows `[code, label, parent, unit, flag, *values]`."""
    rows: list[list[Any]] = []
    for at, name in enumerate(HEADER_ROWS):
        rows.append([name, None, None, None, None, *(p[at] for p in periods)])
    rows.append([*TITLES, *(f"{p[1]} {p[0]}" for p in periods)])
    if isinstance(lines, Mapping):
        rows.extend([code, None, None, None, None, *values] for code, values in lines.items())
    else:
        rows.extend(list(line) for line in lines)
    return rows


def workbook(statements: Mapping[str, list[list[Any]]], scale: str | None = "millions") -> bytes:
    book = Workbook()
    instructions = book.active
    assert instructions is not None
    instructions.title = "Instructions"
    instructions.append(["How to fill this workbook"])
    if scale is not None:
        instructions.append(["scale", scale])
    for name, rows in statements.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def csv_file(
    statements: Mapping[str, list[list[Any]]], scale: str | None = "millions", delimiter: str = ","
) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    if scale is not None:
        writer.writerow(["scale", scale])
    for name, rows in statements.items():
        for row in rows:
            writer.writerow([name, *("" if v is None else v for v in row)])
    return out.getvalue().encode()


def filled(book: Any, sheet: str, code: str, period: str, value: float) -> None:
    """Type `value` into the cell of `code` under the column of `period` (`FY2008`, `FY2008Q2`)."""
    ws = book[sheet]

    def key(c: int) -> str:
        year, fiscal_period = ws.cell(row=1, column=c).value, ws.cell(row=2, column=c).value
        return f"FY{year}" + ("" if fiscal_period == "FY" else str(fiscal_period))

    column = next(c for c in range(6, ws.max_column + 1) if key(c) == period)
    row = next(r for r in range(6, ws.max_row + 1) if ws.cell(row=r, column=1).value == code)
    ws.cell(row=row, column=column).value = value


def save(book: Any) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
