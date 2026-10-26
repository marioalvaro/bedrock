"""Manual statement import: an xlsx or CSV file into one plan, every error located. Pure.

The layout is the template's (docs/erd/data.md "Manual statement import"). A statement sheet has
four header rows (`fiscal_year`, `fiscal_period`, `period_start`, `period_end`; their name in the
first column, the values from the sixth), a column-title row, then one row per line with the
columns `code | label | parent | unit | children_complete | <one column per period>`. An xlsx file
has the sheets `Instructions` (a `scale` row), `IS`, `BS` and `CF`; a CSV file is the same sheets
one after the other, every row led by its statement, after a `scale` row.

`parse_import` returns an `ImportPlan` of values in units and in the reported sign convention, or
raises `ImportParseError` with every error. Whether the periods fit a company's fiscal calendar is
decided by the caller (`statements/imports.py`), which knows the calendar.
"""

import csv
import io
import math
import zipfile
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from xml.etree.ElementTree import ParseError

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from bedrock.mapping.config import STATEMENTS, CanonicalItemDef
from bedrock.statements.periods import (
    FY_DAYS,
    START_TOLERANCE,
    Calendar,
    annual_periods,
    quarterly_periods,
)

ImportFormat = Literal["xlsx", "csv"]

SCALES: dict[str, int] = {"units": 1, "thousands": 10**3, "millions": 10**6, "billions": 10**9}
FISCAL_PERIODS = ("FY", "Q1", "Q2", "Q3", "Q4")
HEADER_ROWS = ("fiscal_year", "fiscal_period", "period_start", "period_end")
COLUMN_TITLES = ("code", "label", "parent", "unit", "children_complete")
INSTRUCTIONS = "Instructions"
FIRST_PERIOD = len(COLUMN_TITLES)  # index of the first period column within a statement row
QUARTER_DAYS = (60, 125)  # COST's 16-week fourth quarter is 112 days
# The range a SQLite REAL stores exactly (Gotcha G21), checked on the value in units.
VALUE_LIMIT = Decimal(10) ** 15
VALUE_PLACES = 10
MAX_ROWS = 2_000  # a statement has ~90 lines; a file with more is not a template

_SCALED_UNITS = ("USD", "shares")  # a per-share value is never scaled
_TRUE = {"true", "yes", "y", "1", "x"}
_FALSE = {"false", "no", "n", "0", ""}


@dataclass(frozen=True)
class ImportIssue:
    """An error or a warning. `row` and `column` (a letter) locate it in `sheet` (the statement
    of a CSV file); any of them is None when the issue concerns the whole file or sheet."""

    sheet: str | None
    row: int | None
    column: str | None
    message: str


class ImportParseError(ValueError):
    """The file cannot be imported: `errors` is every problem found, in file order."""

    def __init__(self, errors: Sequence[ImportIssue]) -> None:
        super().__init__("; ".join(e.message for e in errors))
        self.errors = list(errors)


@dataclass(frozen=True)
class PlanPeriod:
    """A period the file has values for. `start` is None for a period that only a balance sheet
    carries. `sheet` and `column` locate its header (for errors found later)."""

    fiscal_year: int
    fiscal_period: str
    start: date | None
    end: date
    sheet: str
    column: str

    @property
    def key(self) -> str:
        return period_key(self.fiscal_year, self.fiscal_period)


@dataclass(frozen=True)
class PlanValue:
    """One typed value, in units and in the reported sign convention."""

    statement: str
    code: str
    fiscal_year: int
    fiscal_period: str
    value: Decimal
    sheet: str
    row: int
    column: str

    @property
    def period_key(self) -> str:
        return period_key(self.fiscal_year, self.fiscal_period)


@dataclass(frozen=True)
class ImportPlan:
    format: ImportFormat
    scale: str
    periods: tuple[PlanPeriod, ...]
    values: tuple[PlanValue, ...]
    warnings: tuple[ImportIssue, ...]


def check_periods(
    plan: ImportPlan, sec: Calendar, current: Calendar
) -> tuple[list[ImportIssue], ImportPlan]:
    """The plan's periods against the company's calendar. `sec` is the calendar of the SEC facts,
    `current` the one with the imported years already stored. A period of `current` is read
    against the calendar's own dates (the plan's are snapped to them, within a week); a new period
    must lie before the first SEC year, or anywhere when the company has no SEC years. Returns the
    errors and the plan with the snapped periods."""
    known = {
        (p.fiscal_year, p.fiscal_period): p
        for p in annual_periods(current) + quarterly_periods(current)
    }
    issues: list[ImportIssue] = []
    snapped: list[PlanPeriod] = []
    for period in plan.periods:
        match = known.get((period.fiscal_year, period.fiscal_period))
        if match is not None:
            near = abs(match.end - period.end) <= START_TOLERANCE and (
                period.start is None or abs(match.start - period.start) <= START_TOLERANCE
            )
            if near:
                snapped.append(
                    replace(
                        period, start=None if period.start is None else match.start, end=match.end
                    )
                )
            else:
                issues.append(
                    ImportIssue(
                        period.sheet,
                        4,
                        period.column,
                        f"{_label(period)} is {period.start or '?'} to {period.end} in the file "
                        f"but {match.start} to {match.end} in the company's calendar",
                    )
                )
            continue
        clash = next(
            (
                other
                for (_, fp), other in known.items()
                if (fp == "FY") == (period.fiscal_period == "FY")
                and abs(other.end - period.end) <= START_TOLERANCE
            ),
            None,
        )
        if clash is not None:
            issues.append(
                ImportIssue(
                    period.sheet,
                    4,
                    period.column,
                    f"{_label(period)} ends {period.end}, the date of {clash.label} "
                    f"in the company's calendar ({clash.key})",
                )
            )
        elif sec.years and period.end >= sec.years[0].start:
            issues.append(
                ImportIssue(
                    period.sheet,
                    4,
                    period.column,
                    f"{_label(period)} is not a period of the company's calendar; an import "
                    "fills the periods SEC has, or years before the first SEC year",
                )
            )
        else:
            snapped.append(period)
    return issues, replace(plan, periods=tuple(snapped))


def _label(period: PlanPeriod) -> str:
    year = f"FY{period.fiscal_year}"
    return year if period.fiscal_period == "FY" else f"{period.fiscal_period} {year}"


def period_key(fiscal_year: int, fiscal_period: str) -> str:
    return f"FY{fiscal_year}" if fiscal_period == "FY" else f"FY{fiscal_year}{fiscal_period}"


def parse_import(
    content: bytes,
    filename: str,
    items: Sequence[CanonicalItemDef],
    scale: str | None = None,
) -> ImportPlan:
    """Both formats into one plan. `scale` stands in for a file that has none. Raises
    `ImportParseError` with every error found (none is raised for a warning)."""
    name = filename.lower()
    if name.endswith(".xlsx"):
        fmt: ImportFormat = "xlsx"
        book = _read_xlsx(content)
    elif name.endswith(".csv"):
        fmt = "csv"
        book = _read_csv(content)
    else:
        raise ImportParseError(
            [ImportIssue(None, None, None, "The file must be an .xlsx or a .csv file")]
        )
    return _Parser(fmt, book, {i.code: i for i in items}, scale).run()


@dataclass
class _Book:
    """What a reader found: the file's scale, each statement's rows as (row number, cells), and
    the issues of the file itself. `offset` is the column of a statement row's first cell."""

    scale: str | None
    sheets: dict[str, list[tuple[int, list[Any]]]]
    offset: int
    issues: list[ImportIssue]


def _read_xlsx(content: bytes) -> _Book:
    book = _Book(None, {}, 0, [])
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, ValueError, OSError, ParseError):
        raise ImportParseError(
            [ImportIssue(None, None, None, "The file is not a valid .xlsx workbook")]
        ) from None
    try:
        for sheet in workbook.worksheets:
            rows = [list(r) for r in sheet.iter_rows(values_only=True, max_row=MAX_ROWS + 1)]
            if sheet.title == INSTRUCTIONS:
                book.scale = _scale_row([(i, r) for i, r in enumerate(rows, start=1)])
            elif sheet.title in STATEMENTS:
                book.sheets[sheet.title] = list(enumerate(rows, start=1))
            else:
                book.issues.append(
                    ImportIssue(sheet.title, None, None, f"Unknown sheet '{sheet.title}'")
                )
    finally:
        workbook.close()
    return book


def _read_csv(content: bytes) -> _Book:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportParseError(
            [ImportIssue(None, None, None, "The file is not UTF-8 text")]
        ) from None
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = next((d for d in ("\t", ";", ",") if d in first), ",")
    book = _Book(None, {}, 1, [])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    unknown: set[str] = set()
    for row in reader:
        if not any(str(c).strip() for c in row):
            continue
        head = row[0].strip()
        if head.lower() == "scale":
            book.scale = row[1].strip() if len(row) > 1 else ""
        elif head.upper() in STATEMENTS:
            book.sheets.setdefault(head.upper(), []).append((reader.line_num, row[1:]))
        elif head not in unknown:
            unknown.add(head)
            book.issues.append(
                ImportIssue(head, reader.line_num, "A", f"Unknown statement '{head}'")
            )
        if sum(len(rows) for rows in book.sheets.values()) > MAX_ROWS:
            raise ImportParseError([ImportIssue(None, None, None, "The file has too many rows")])
    return book


def _scale_row(rows: Sequence[tuple[int, list[Any]]]) -> str | None:
    for _, row in rows:
        if row and isinstance(row[0], str) and row[0].strip().lower() == "scale":
            value = row[1] if len(row) > 1 else None
            return "" if value is None else str(value).strip()
    return None


@dataclass(frozen=True)
class _Column:
    """A period column of one statement sheet."""

    index: int  # within the statement row
    letter: str
    fiscal_year: int
    fiscal_period: str
    start: date | None
    end: date

    @property
    def key(self) -> str:
        return period_key(self.fiscal_year, self.fiscal_period)

    @property
    def label(self) -> str:
        year = f"FY{self.fiscal_year}"
        return year if self.fiscal_period == "FY" else f"{self.fiscal_period} {year}"


class _Parser:
    def __init__(
        self,
        fmt: ImportFormat,
        book: _Book,
        items: dict[str, CanonicalItemDef],
        scale: str | None,
    ) -> None:
        self.fmt = fmt
        self.book = book
        self.items = items
        self.scale_arg = scale
        self.errors: list[ImportIssue] = list(book.issues)
        self.warnings: list[ImportIssue] = []
        self.values: list[PlanValue] = []
        self.columns: dict[str, list[_Column]] = {}

    def run(self) -> ImportPlan:
        scale = self._scale()
        for statement in STATEMENTS:
            if statement in self.book.sheets:
                self._statement(statement, self.book.sheets[statement], scale)
        self._cross_checks()
        periods = self._periods()
        if not self.errors and not self.values:
            self.errors.append(ImportIssue(None, None, None, "The file has no values to import"))
        if self.errors:
            raise ImportParseError(sorted(self.errors, key=_order))
        assert scale is not None
        return ImportPlan(
            self.fmt,
            scale,
            tuple(periods),
            tuple(self.values),
            tuple(sorted(self.warnings, key=_order)),
        )

    # -- scale ----------------------------------------------------------------------------------

    def _scale(self) -> str | None:
        found = self.book.scale
        if found is None or found == "":
            found = self.scale_arg
        if found is None or found == "":
            self.errors.append(
                ImportIssue(
                    INSTRUCTIONS if self.fmt == "xlsx" else None,
                    None,
                    None,
                    "The scale is missing: add a 'scale' row with units, thousands, millions "
                    "or billions",
                )
            )
            return None
        found = found.lower()
        if found not in SCALES:
            self.errors.append(
                ImportIssue(
                    INSTRUCTIONS if self.fmt == "xlsx" else None,
                    None,
                    None,
                    f"Unknown scale '{found}': use units, thousands, millions or billions",
                )
            )
            return None
        return found

    # -- one statement --------------------------------------------------------------------------

    def _statement(self, sheet: str, rows: list[tuple[int, list[Any]]], scale: str | None) -> None:
        headers, start = self._find_headers(sheet, rows)
        if headers is None:
            return
        columns = self._columns(sheet, headers)
        self.columns[sheet] = columns
        self._contiguity(sheet, columns)
        self._lines(sheet, rows[start:], columns, scale)

    def _find_headers(
        self, sheet: str, rows: list[tuple[int, list[Any]]]
    ) -> tuple[dict[str, tuple[int, list[Any]]] | None, int]:
        """The four header rows by name, and the position of the first line after them and the
        title row."""
        found: dict[str, tuple[int, list[Any]]] = {}
        after = len(rows)
        for position, (number, cells) in enumerate(rows):
            name = _text(_at(cells, 0)).lower()
            if name in HEADER_ROWS and name not in found:
                found[name] = (number, cells)
            elif name != COLUMN_TITLES[0] and not _blank_row(cells):
                after = position
                break
        missing = [n for n in HEADER_ROWS if n not in found]
        for name in missing:
            self._err(sheet, None, None, f"The sheet has no {name} row")
        return (None, 0) if missing else (found, after)

    def _columns(self, sheet: str, headers: dict[str, tuple[int, list[Any]]]) -> list[_Column]:
        width = max(len(cells) for _, cells in headers.values())
        flows = sheet != "BS"
        columns: list[_Column] = []
        seen: dict[str, str] = {}
        for index in range(FIRST_PERIOD, width):
            cells = {name: _at(headers[name][1], index) for name in HEADER_ROWS}
            if all(_blank(c) for c in cells.values()):
                continue
            letter = self._letter(index)
            rows = {name: headers[name][0] for name in HEADER_ROWS}
            column = self._column(sheet, flows, index, letter, cells, rows)
            if column is None:
                continue
            if column.key in seen:
                self.errors.append(
                    ImportIssue(
                        sheet,
                        rows["fiscal_year"],
                        letter,
                        f"{column.label} appears twice (columns {seen[column.key]} and {letter})",
                    )
                )
                continue
            seen[column.key] = letter
            columns.append(column)
        return columns

    def _column(
        self,
        sheet: str,
        flows: bool,
        index: int,
        letter: str,
        cells: dict[str, Any],
        rows: dict[str, int],
    ) -> _Column | None:
        ok = True

        def fail(name: str, message: str) -> None:
            nonlocal ok
            ok = False
            self.errors.append(ImportIssue(sheet, rows[name], letter, message))

        year = _whole_number(cells["fiscal_year"])
        if year is None or not 1000 <= year <= 9999:
            fail("fiscal_year", "fiscal_year must be a four-digit year")
        period = _text(cells["fiscal_period"]).upper()
        if period not in FISCAL_PERIODS:
            fail("fiscal_period", "fiscal_period must be FY, Q1, Q2, Q3 or Q4")
        start = _date(cells["period_start"])
        if flows and start is None:
            fail("period_start", "period_start must be a date (YYYY-MM-DD)")
        end = _date(cells["period_end"])
        if end is None:
            fail("period_end", "period_end must be a date (YYYY-MM-DD)")
        if not ok or year is None or end is None:
            return None
        if not flows:
            start = None
        elif start is not None and end < start:
            fail("period_end", "period_end is before period_start")
            return None
        column = _Column(index, letter, year, period, start, end)
        if flows and start is not None:
            days = (end - start).days
            if period == "FY" and not FY_DAYS[0] <= days <= FY_DAYS[1]:
                fail(
                    "period_end",
                    f"A fiscal year lasts {FY_DAYS[0]}-{FY_DAYS[1]} days; "
                    f"{column.label} lasts {days}",
                )
            elif period != "FY" and not QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
                fail(
                    "period_end",
                    f"A quarter lasts {QUARTER_DAYS[0]}-{QUARTER_DAYS[1]} days; "
                    f"{column.label} lasts {days}",
                )
        return column if ok else None

    def _letter(self, index: int) -> str:
        return get_column_letter(self.book.offset + index + 1)

    def _contiguity(self, sheet: str, columns: list[_Column]) -> None:
        """Quarters follow each other the day after, and the first and last meet the year."""
        if sheet == "BS":
            return
        rows = {name: n for n, name in enumerate(HEADER_ROWS, start=1)}
        by_year: dict[int, dict[str, _Column]] = defaultdict(dict)
        for column in columns:
            by_year[column.fiscal_year][column.fiscal_period] = column
        for year, periods in by_year.items():
            for n in range(1, 4):
                this, following = periods.get(f"Q{n}"), periods.get(f"Q{n + 1}")
                if this and following and this.end and following.start:
                    if (following.start - this.end).days != 1:
                        self.errors.append(
                            ImportIssue(
                                sheet,
                                rows["period_start"],
                                following.letter,
                                f"{following.fiscal_period} FY{year} must start the day after "
                                f"Q{n} ends ({this.end})",
                            )
                        )
            fy, q1, q4 = periods.get("FY"), periods.get("Q1"), periods.get("Q4")
            if fy and q1 and fy.start != q1.start:
                self.errors.append(
                    ImportIssue(
                        sheet,
                        rows["period_start"],
                        q1.letter,
                        f"Q1 FY{year} must start when the year starts ({fy.start})",
                    )
                )
            if fy and q4 and fy.end != q4.end:
                self.errors.append(
                    ImportIssue(
                        sheet,
                        rows["period_end"],
                        q4.letter,
                        f"Q4 FY{year} must end when the year ends ({fy.end})",
                    )
                )

    # -- lines ----------------------------------------------------------------------------------

    def _lines(
        self,
        sheet: str,
        rows: list[tuple[int, list[Any]]],
        columns: list[_Column],
        scale: str | None,
    ) -> None:
        by_index = {c.index: c for c in columns}
        first_seen: dict[str, int] = {}
        code_at = self._letter(0)
        for number, cells in rows:
            code = _text(_at(cells, 0))
            parent = _text(_at(cells, 2))
            typed = [i for i in range(FIRST_PERIOD, len(cells)) if not _blank(cells[i])]
            if not code and not parent and not typed:
                continue
            item = self.items.get(code)
            if item is None:
                if parent:  # a custom line: a new row under a parent
                    self._err(
                        sheet,
                        number,
                        code_at,
                        f"Custom lines arrive in S10c; this row adds {code or 'a line'} "
                        f"under {parent}",
                    )
                elif code:
                    self._err(sheet, number, code_at, f"Unknown code '{code}'")
                else:
                    self._err(sheet, number, code_at, "The row has values but no code")
                continue
            if item.statement != sheet:
                self._err(
                    sheet,
                    number,
                    code_at,
                    f"{code} belongs to the {item.statement} sheet, not {sheet}",
                )
                continue
            if code in first_seen:
                self._err(
                    sheet, number, code_at, f"{code} already appears on row {first_seen[code]}"
                )
                continue
            first_seen[code] = number
            if _flag(_at(cells, 4)) is None:
                self._err(
                    sheet,
                    number,
                    self._letter(4),
                    "children_complete must be TRUE, FALSE or blank",
                )
            if item.residual or (item.derive is not None and not item.concepts):
                if typed:
                    self.warnings.append(
                        ImportIssue(
                            sheet,
                            number,
                            code_at,
                            f"{code} is read-only (computed): its {len(typed)} values are ignored",
                        )
                    )
                continue
            for i in typed:
                column = by_index.get(i)
                if column is None:
                    self._err(
                        sheet,
                        number,
                        self._letter(i),
                        "A value under a column with no period header",
                    )
                else:
                    self._value(sheet, number, item, column, cells[i], scale)

    def _value(
        self,
        sheet: str,
        number: int,
        item: CanonicalItemDef,
        column: _Column,
        raw: Any,
        scale: str | None,
    ) -> None:
        typed = _number(raw)
        if typed is None:
            self._err(sheet, number, column.letter, f"'{_text(raw)}' is not a number")
            return
        if scale is None:  # the scale error is already recorded
            return
        factor = SCALES[scale] if item.unit in _SCALED_UNITS else 1
        value = typed * factor * item.sign
        if abs(value) >= VALUE_LIMIT:
            self._err(
                sheet, number, column.letter, f"{value:,} is too large (limit {VALUE_LIMIT:,})"
            )
        elif value != value.quantize(Decimal(1).scaleb(-VALUE_PLACES)):
            self._err(
                sheet,
                number,
                column.letter,
                f"{typed} has more than {VALUE_PLACES} decimal places",
            )
        else:
            self.values.append(
                PlanValue(
                    item.statement,
                    item.code,
                    column.fiscal_year,
                    column.fiscal_period,
                    _plain(value),
                    sheet,
                    number,
                    column.letter,
                )
            )

    def _err(self, sheet: str | None, row: int | None, column: str | None, message: str) -> None:
        self.errors.append(ImportIssue(sheet, row, column, message))

    # -- across statements ----------------------------------------------------------------------

    def _cross_checks(self) -> None:
        """One period carries the same dates on every statement, and a balance sheet's year-end
        values agree with its fourth quarter's (the same date)."""
        seen: dict[str, tuple[str, _Column]] = {}
        for sheet in STATEMENTS:
            for column in self.columns.get(sheet, []):
                first = seen.setdefault(column.key, (sheet, column))
                if first[1] is column:
                    continue
                other_sheet, other = first
                if other.end != column.end:
                    self.errors.append(
                        ImportIssue(
                            sheet,
                            4,
                            column.letter,
                            f"{column.label} ends {column.end} here but {other.end} "
                            f"on {other_sheet}",
                        )
                    )
                elif sheet != "BS" and other_sheet != "BS" and other.start != column.start:
                    self.errors.append(
                        ImportIssue(
                            sheet,
                            3,
                            column.letter,
                            f"{column.label} starts {column.start} here but {other.start} "
                            f"on {other_sheet}",
                        )
                    )
        end_of = {(s, c.key): c.end for s, columns in self.columns.items() for c in columns}
        instants: dict[tuple[str, date], dict[str, PlanValue]] = defaultdict(dict)
        for v in self.values:
            if self.items[v.code].kind == "instant":
                instants[(v.code, end_of[(v.sheet, v.period_key)])][v.fiscal_period] = v
        for (code, _), by_period in instants.items():
            year, q4 = by_period.get("FY"), by_period.get("Q4")
            if year and q4 and year.value != q4.value:
                self.warnings.append(
                    ImportIssue(
                        q4.sheet,
                        q4.row,
                        q4.column,
                        f"{code}: {year.period_key} and {q4.period_key} are the same date but "
                        f"differ ({year.value} and {q4.value}); the year's value is used",
                    )
                )

    def _periods(self) -> list[PlanPeriod]:
        """The periods that carry a value, one per fiscal period, in file order. The start comes
        from a statement that has one."""
        wanted = {(v.sheet, v.period_key) for v in self.values}
        merged: dict[str, PlanPeriod] = {}
        for sheet in STATEMENTS:
            for column in self.columns.get(sheet, []):
                if (sheet, column.key) not in wanted:
                    continue
                known = merged.get(column.key)
                if known is None:
                    merged[column.key] = PlanPeriod(
                        column.fiscal_year,
                        column.fiscal_period,
                        column.start,
                        column.end,
                        sheet,
                        column.letter,
                    )
                elif known.start is None and column.start is not None:
                    merged[column.key] = PlanPeriod(
                        known.fiscal_year,
                        known.fiscal_period,
                        column.start,
                        known.end,
                        known.sheet,
                        known.column,
                    )
        return sorted(
            merged.values(), key=lambda p: (p.fiscal_year, FISCAL_PERIODS.index(p.fiscal_period))
        )


def _order(issue: ImportIssue) -> tuple[int, int, int, str]:
    """File order: the file's own issues, IS, BS, CF, other sheets; then rows and columns."""
    if issue.sheet is None:
        rank = -1
    elif issue.sheet in STATEMENTS:
        rank = STATEMENTS.index(issue.sheet)
    else:
        rank = len(STATEMENTS)
    column = issue.column or ""
    return (rank, issue.row or 0, len(column), column)


# -- cell helpers -------------------------------------------------------------------------------


def _at(cells: Sequence[Any], index: int) -> Any:
    return cells[index] if index < len(cells) else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _blank_row(cells: Sequence[Any]) -> bool:
    return all(_blank(c) for c in cells)


def _whole_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = _text(value)
    return int(text) if text.isdigit() else None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _number(value: Any) -> Decimal | None:
    """A typed number: an int, a float, or text with thousands separators and a negative in
    parentheses. Booleans, non-finite and anything else are not numbers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value)) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return -number if negative else number


def _flag(value: Any) -> bool | None:
    """The `children_complete` cell: TRUE/FALSE/blank (and the usual spellings); None if it is
    anything else."""
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def _plain(value: Decimal) -> Decimal:
    """Without trailing zeros and never in exponent notation (`1000000`, not `1E+6`)."""
    return value.quantize(Decimal(1)) if value == value.to_integral_value() else value.normalize()
