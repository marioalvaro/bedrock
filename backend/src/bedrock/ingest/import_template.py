"""The import template, as xlsx or CSV bytes. Pure.

Its layout is the one `manual_import.parse_import` reads (see that module). One row per canonical
item in display order; residual and computed-only rows are grey and left blank, because a value
typed there is ignored. `values` prefills the sheet with the company's displayed values. The
columns carry only a fiscal year and period: their dates come from the `fiscal_year_end` row of
the Instructions (`statements/fiscal_grid.py`).
"""

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import date
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
# The header rows of a template; `period_start` and `period_end` rows are optional overrides.
HEADERS = HEADER_ROWS[:2]

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
    "An import only fills cells the SEC data leaves empty.",
    "fiscal_year_end (above) is the date your annual period ends, YYYY-MM-DD; any fiscal year's "
    "works. Every column's dates follow from it: a month-end date gives month-end quarters, "
    "another day repeats that day. Each sheet already lists 20 fiscal years, each as FY, Q1, Q2, "
    "Q3, Q4: type values in the columns you have and leave the others blank.",
    "For exact dates in a column (a 52/53-week year), insert two rows named period_start and "
    "period_end above the 'code' row and type that column's dates (YYYY-MM-DD, both or neither). "
    "To add a period the sheet lacks, add a column with its fiscal_year and fiscal_period.",
)

# A made-up company in millions, laid out like the statement sheets so the user can compare: the
# header rows, the column titles, then (code, label, children_complete, FY2023, FY2024) per
# line. Canonical labels, parents and units come from the items; the custom lines (blank code,
# a label and a parent) go at the bottom of their sheet. It is internally consistent (gross
# profit, the balance sheet and the cash roll-forward foot) and parses without error.
_EXAMPLE_PERIODS = ((2023, "FY"), (2024, "FY"))  # with fiscal_year_end 2024-12-31
_EXAMPLE: dict[str, tuple[tuple[str, Any, Any, Any], ...]] = {
    "IS": (
        ("revenue", None, 1000, 1200),
        ("cost_of_revenue", True, 600, 700),
        ("gross_profit", None, 400, 500),
        ("rnd", None, 100, 120),
        ("sga", None, 80, 90),
        ("operating_income", None, 220, 290),
        ("interest_expense", None, 10, 12),
        ("pretax_income", None, 210, 278),
        ("income_tax", None, 42, 56),
        ("net_income", None, 168, 222),
        ("eps_diluted", None, 1.68, 2.22),
        ("shares_diluted", None, 100, 100),
    ),
    "BS": (
        ("total_assets", None, 800, 900),
        ("total_current_assets", None, 300, 350),
        ("cash", None, 120, 150),
        ("receivables", None, 100, 110),
        ("inventory", None, 60, 70),
        ("ppe_net", None, 400, 430),
        ("goodwill", None, 100, 120),
        ("total_liabilities", None, 450, 480),
        ("total_current_liabilities", None, 200, 210),
        ("accounts_payable", None, 90, 100),
        ("short_term_debt", None, 50, 50),
        ("long_term_debt", None, 200, 220),
        ("total_equity", None, 350, 420),
        ("equity_parent", None, 350, 420),
        ("common_stock_apic", None, 150, 160),
        ("retained_earnings", None, 200, 260),
        ("total_liabilities_and_equity", None, 800, 900),
        ("shares_outstanding", None, 100, 100),
    ),
    "CF": (
        ("cfo", None, 203, 269),
        ("cf_net_income", None, 168, 222),
        ("d_and_a", None, 40, 45),
        ("sbc", None, 10, 12),
        ("change_receivables", None, -15, -10),
        ("cfi", None, -60, -70),
        ("capex", None, -60, -70),
        ("cff", None, -100, -165),
        ("debt_repaid", None, -30, -40),
        ("buybacks", None, -50, -100),
        ("dividends_paid", None, -20, -25),
        ("fx_effect", None, None, -4),
        ("net_change_in_cash", None, 43, 30),
    ),
}
# (label, parent, FY2023, FY2024): the whole breakdown of cost_of_revenue, so it is complete.
_EXAMPLE_CUSTOM = (
    ("Products", "cost_of_revenue", 450, 520),
    ("Services", "cost_of_revenue", 150, 180),
)


def build_template(
    items: Sequence[CanonicalItemDef],
    periods: Sequence[Period],
    fmt: Literal["xlsx", "csv"],
    scale: str,
    values: Mapping[tuple[str, str], Decimal] | None = None,
    fiscal_year_end: date | None = None,
) -> bytes:
    """The template for `periods` (oldest first). `values` maps (code, period key) to the
    displayed value in units; it is written divided by the scale (per-share values as they are).
    `fiscal_year_end` is written to the Instructions (left blank when None). Raises ValueError for
    an unknown scale."""
    if scale not in SCALES:
        raise ValueError(f"Unknown scale '{scale}'")
    sheets = {s: _rows(items, periods, s, scale, values or {}) for s in STATEMENTS}
    end = None if fiscal_year_end is None else fiscal_year_end.isoformat()
    return _xlsx(sheets, items, scale, end) if fmt == "xlsx" else _csv(sheets, scale, end)


_EXAMPLE_INTRO = (
    "The examples below are a made-up company in millions with fiscal_year_end 2024-12-31 (set "
    "both to import them as they are): 1,200 is USD 1.2 billion. They show the layout of each "
    "sheet; the grey rows stay blank, and the income statement ends with a custom breakdown of "
    "cost_of_revenue."
)


def _example_blocks(items: Sequence[CanonicalItemDef]) -> list[list[list[Any]]]:
    """The filled examples as Instructions rows: a heading, then the sheet layout."""
    by_code = {i.code: i for i in items}
    pad: list[Any] = [None] * (FIRST_PERIOD - 1)
    blocks: list[list[list[Any]]] = []
    for statement, lines in _EXAMPLE.items():
        rows: list[list[Any]] = [[f"Example {statement}"]]
        for position, name in enumerate(HEADERS):
            rows.append([name, *pad, *(p[position] for p in _EXAMPLE_PERIODS)])
        rows.append([*COLUMN_TITLES, *(f"FY{p[0]}" for p in _EXAMPLE_PERIODS)])
        for code, complete, before, after in lines:
            item = by_code[code]
            rows.append([code, item.label, item.parent, item.unit, complete, before, after])
        if statement == "IS":
            for label, parent, before, after in _EXAMPLE_CUSTOM:
                rows.append([None, label, parent, None, None, before, after])
        blocks.append(rows)
    return blocks


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
    }
    rows: list[list[Any]] = [[name, *pad, *columns[name]] for name in HEADERS]
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
    sheets: Mapping[str, list[list[Any]]],
    items: Sequence[CanonicalItemDef],
    scale: str,
    fiscal_year_end: str | None,
) -> bytes:
    book = Workbook()
    guide = book.active
    assert guide is not None
    guide.title = INSTRUCTIONS
    guide.append(["scale", scale])
    guide.append(["fiscal_year_end", fiscal_year_end])
    guide.append([])
    for line in _INSTRUCTIONS:
        guide.append([line])
    for number, rows in enumerate(_example_blocks(items)):
        if number == 0:
            guide.append([])
            guide.append([_EXAMPLE_INTRO])
        guide.append([])
        for row in rows:
            guide.append(row)
    guide.column_dimensions["A"].width = 18
    read_only = {i.code for i in items if _is_read_only(i)}
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
        for number, row in enumerate(rows, start=1):
            if number <= len(HEADERS) + 1:
                for cell in sheet[number]:
                    cell.font = BOLD
            elif row[0] in read_only:
                for cell in sheet[number][: len(rows[0])]:
                    cell.fill = GREY
        sheet.freeze_panes = sheet.cell(row=len(HEADERS) + 2, column=FIRST_PERIOD + 1)
        sheet.column_dimensions["A"].width = 28
        sheet.column_dimensions["B"].width = 38
        for index in range(FIRST_PERIOD + 1, len(rows[0]) + 1):
            sheet.column_dimensions[get_column_letter(index)].width = 14
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _csv(sheets: Mapping[str, list[list[Any]]], scale: str, fiscal_year_end: str | None) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["scale", scale])
    writer.writerow(["fiscal_year_end", fiscal_year_end or ""])
    for name, rows in sheets.items():
        for row in rows:
            writer.writerow([name, *("" if cell is None else cell for cell in row)])
    return out.getvalue().encode()
