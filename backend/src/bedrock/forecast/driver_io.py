"""Driver files: a scenario's own drivers as CSV or xlsx, and an uploaded file back into the rows
it sets (docs/erd/forecasting.md "Driver files (M4)"). Pure.

The layout is one header row `driver_code, label, unit, kind, FY<year>…`, then one row per
driver. A cell is the scenario's own stored value (pct as a fraction), blank where it inherits.
"""

import csv
import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from bedrock.forecast.drivers import DriverDef, DriverKind, UnknownDriver, check_bounds, driver_def
from bedrock.forecast.grid import DriverGrid
from bedrock.forecast.resolve import DriverRow
from bedrock.ingest.manual_import import parse_number

HEADER = ("driver_code", "label", "unit", "kind")
DRIVERS_SHEET = "Drivers"
RESOLVED_SHEET = "Resolved"
MAX_ROWS = 1000  # far more than any catalog; a bigger file is not a driver file
_FORMATS = {"pct": "0.00%", "days": "0.0", "USD": "#,##0"}  # a USD fraction stays General
_YEAR = re.compile(r"FY(\d{4})", re.IGNORECASE)
# A comma is accepted only as thousands grouping (1,234.5): a decimal comma (0,03, as a European
# Excel writes) would otherwise read as a number 100 times too large or more.
_GROUPED = re.compile(r"\(?-?[1-9]\d{0,2}(,\d{3})+(\.\d+)?\)?")
SCALE = Decimal("1E-10")  # driver_value.value is Numeric(28, 10)
_ROUNDED_BELOW = Decimal(10) ** 16  # larger values are out of every bound; left for check_bounds
_BOLD = Font(bold=True)


@dataclass(frozen=True)
class DriverFileIssue:
    """An error of the file. `row` is 1-based, `column` a letter; either is None when the error
    concerns the whole file."""

    row: int | None
    column: str | None
    message: str


class DriverFileError(ValueError):
    """The file cannot be imported: `issues` lists every error, in file order."""

    def __init__(self, issues: list[DriverFileIssue]) -> None:
        super().__init__(f"The file has {len(issues)} error(s)")
        self.issues = issues


@dataclass(frozen=True)
class FileRow:
    """One driver of the file: its kind (None when blank) and a value or None per year column."""

    code: str
    kind: DriverKind | None
    values: dict[int, Decimal | None]


@dataclass(frozen=True)
class DriverFilePlan:
    years: tuple[int, ...]  # the file's year columns, in file order
    rows: tuple[FileRow, ...]  # in file order


@dataclass(frozen=True)
class DriverChange:
    """A stored row the import changes: (kind, value) before and after; None where none."""

    driver_code: str
    fiscal_year: int
    old: Decimal | None
    new: Decimal | None
    old_kind: DriverKind | None
    new_kind: DriverKind | None


@dataclass(frozen=True)
class DriverImport:
    changes: list[DriverChange]
    rows: dict[str, list[DriverRow]]  # each changed driver -> all its rows after the import


# Export ------------------------------------------------------------------------------------------


def export_csv(grid: DriverGrid) -> bytes:
    """The Drivers table as UTF-8 CSV, numbers in plain decimal notation."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in _drivers_table(grid):
        writer.writerow(
            "" if c is None else _plain(c) if isinstance(c, Decimal) else c for c in row
        )
    return out.getvalue().encode()


def export_xlsx(grid: DriverGrid) -> bytes:
    """Sheet Drivers (the CSV's table, cells formatted by unit) and sheet Resolved (history and
    resolved values with their source, for reference; never read back)."""
    book = Workbook()
    drivers = book.active
    assert drivers is not None
    drivers.title = DRIVERS_SHEET
    _write(drivers, _drivers_table(grid), [r.unit for r in grid.rows], len(HEADER))
    resolved = book.create_sheet(RESOLVED_SHEET)
    _write(resolved, _resolved_table(grid), [r.unit for r in grid.rows], 3)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _drivers_table(grid: DriverGrid) -> list[list[Any]]:
    table: list[list[Any]] = [[*HEADER, *(f"FY{y}" for y in grid.forecast_years)]]
    for row in grid.rows:
        table.append([row.code, row.label, row.unit, row.kind, *row.own])
    return table


def _resolved_table(grid: DriverGrid) -> list[list[Any]]:
    forecast = [f"FY{y}E" for y in grid.forecast_years]
    table: list[list[Any]] = [
        [
            *HEADER[:3],
            *(f"FY{y}" for y in grid.history_years),
            *forecast,
            *(f"{f} source" for f in forecast),
        ]
    ]
    for row in grid.rows:
        values = [
            "flat" if v is None and s == "default" else v
            for v, s in zip(row.values, row.sources, strict=True)
        ]
        table.append([row.code, row.label, row.unit, *row.history, *values, *row.sources])
    return table


def _write(sheet: Any, table: list[list[Any]], units: Sequence[str], first: int) -> None:
    """Writes `table` (header first) from A1; numbers from column `first` on are formatted by
    their row's unit."""
    for number, row in enumerate(table, start=1):
        for column, value in enumerate(row, start=1):
            cell = sheet.cell(row=number, column=column, value=_cell(value))
            if number == 1:
                cell.font = _BOLD
            elif column > first and isinstance(value, Decimal):
                unit = units[number - 2]
                if unit != "USD" or value == value.to_integral_value():
                    cell.number_format = _FORMATS[unit]
    sheet.freeze_panes = sheet.cell(row=2, column=first + 1)
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 32
    for index in range(first + 1, len(table[0]) + 1):
        sheet.column_dimensions[get_column_letter(index)].width = 14


def _cell(value: Any) -> Any:
    if not isinstance(value, Decimal):
        return value
    return int(value) if value == value.to_integral_value() else float(value)


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# Parsing -----------------------------------------------------------------------------------------


def parse_driver_file(
    content: bytes,
    filename: str,
    catalog: Sequence[DriverDef],
    forecast_years: Sequence[int],
    is_base: bool,
) -> DriverFilePlan:
    """The rows a CSV or xlsx file sets (xlsx: its Drivers sheet), told apart by the content
    (an xlsx is a zip) or a `.xlsx` name. `catalog` is the scenario's drivers. `label` and `unit`
    are ignored. Raises DriverFileError with every error found."""
    if content.startswith(b"PK") or filename.lower().endswith(".xlsx"):
        rows, delimiter = _read_xlsx(content), None
    else:
        rows, delimiter = _read_csv(content)
    return _Parser(catalog, forecast_years, is_base, comma_allowed=delimiter != ";").run(rows)


# SyntaxError: the XML parse errors of both the stdlib (ParseError) and lxml (XMLSyntaxError),
# which openpyxl uses for workbook.xml and styles.xml when lxml is installed.
_BROKEN = (zipfile.BadZipFile, InvalidFileException, KeyError, ValueError, OSError, SyntaxError)


def _read_xlsx(content: bytes) -> list[tuple[int, list[Any]]]:
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except _BROKEN:
        raise _fatal("The file is not a valid .xlsx workbook") from None
    if DRIVERS_SHEET not in book.sheetnames:
        book.close()
        raise _fatal(f"The workbook has no {DRIVERS_SHEET} sheet")
    try:
        # read-only sheets parse their XML lazily, so a broken sheet fails while iterating
        rows = book[DRIVERS_SHEET].iter_rows(values_only=True, max_row=MAX_ROWS + 1)
        return [(n, list(r)) for n, r in enumerate(rows, start=1)]
    except _BROKEN:
        raise _fatal("The file is not a valid .xlsx workbook") from None
    finally:
        book.close()


def _read_csv(content: bytes) -> tuple[list[tuple[int, list[Any]]], str]:
    """The rows and the delimiter (detected from the first line, as the statement import)."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _fatal("The file is not UTF-8 text") from None
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = next((d for d in ("\t", ";", ",") if d in first), ",")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[tuple[int, list[Any]]] = []
    for row in reader:
        rows.append((reader.line_num, list(row)))
        if len(rows) > MAX_ROWS:
            break
    return rows, delimiter


def _fatal(message: str) -> DriverFileError:
    return DriverFileError([DriverFileIssue(None, None, message)])


class _Parser:
    def __init__(
        self,
        catalog: Sequence[DriverDef],
        forecast_years: Sequence[int],
        is_base: bool,
        comma_allowed: bool,
    ) -> None:
        self.comma_allowed = comma_allowed  # False in a `;` CSV, where a comma is a decimal one
        self.catalog = {d.code for d in catalog}
        self.forecast_years = list(forecast_years)
        self.is_base = is_base
        self.issues: list[DriverFileIssue] = []

    def run(self, rows: list[tuple[int, list[Any]]]) -> DriverFilePlan:
        filled = [(n, cells) for n, cells in rows if not all(_blank(c) for c in cells)]
        if not filled:
            raise _fatal("The file is empty")
        if len(rows) > MAX_ROWS:
            raise _fatal(f"The file has more than {MAX_ROWS} rows")
        (header_row, header), body = filled[0], filled[1:]
        if [_text(c).lower() for c in header[: len(HEADER)]] != list(HEADER):
            raise DriverFileError(
                [
                    DriverFileIssue(
                        header_row, "A", f"The header must start with {', '.join(HEADER)}"
                    )
                ]
            )
        columns = self._columns(header_row, header, body)
        seen: set[str] = set()
        parsed = [self._row(n, cells, columns, seen) for n, cells in body]
        if self.issues:
            raise DriverFileError(self.issues)
        return DriverFilePlan(tuple(columns.values()), tuple(parsed))

    def _columns(
        self, number: int, header: list[Any], body: list[tuple[int, list[Any]]]
    ) -> dict[int, int]:
        """Cell index -> fiscal year of each year column. A column with a blank header is skipped
        when it holds no value."""
        columns: dict[int, int] = {}
        span = f"FY{self.forecast_years[0]}-FY{self.forecast_years[-1]}"
        width = max(len(cells) for _, cells in [(number, header), *body])
        for index in range(len(HEADER), width):
            title = _text(_at(header, index))
            letter = get_column_letter(index + 1)
            if not title:
                for n, cells in body:
                    if not _blank(_at(cells, index)):
                        self._issue(n, letter, "A value under a column with no year")
                continue
            match = _YEAR.fullmatch(title)
            year = int(match.group(1)) if match else None
            if year is None or year not in self.forecast_years:
                self._issue(number, letter, f"Column '{title}' is not a forecast year ({span})")
            elif year in columns.values():
                self._issue(number, letter, f"FY{year} is given twice")
            else:
                columns[index] = year
        return columns

    def _row(
        self, number: int, cells: list[Any], columns: Mapping[int, int], seen: set[str]
    ) -> FileRow:
        code = _text(_at(cells, 0))
        known = self._code(number, code, seen)  # bounds are checked only for a known driver
        kind_text = _text(_at(cells, len(HEADER) - 1)).lower()
        kind: DriverKind | None = None
        if kind_text in ("value", "offset"):
            kind = "value" if kind_text == "value" else "offset"
        elif kind_text:
            self._issue(number, "D", "kind must be value, offset or blank")
            known = False
        if kind == "offset" and self.is_base:
            self._issue(number, "D", "Base cannot hold offsets")
            known = False
        values: dict[int, Decimal | None] = {}
        for index, year in columns.items():
            raw = _at(cells, index)
            if _blank(raw):
                values[year] = None
                continue
            letter = get_column_letter(index + 1)
            number_value, hint = self._number(raw)
            if number_value is None:
                self._issue(number, letter, f"'{_text(raw)}' is not a number{hint}")
                continue
            values[year] = number_value
            if known and kind is not None:
                message = check_bounds(code, kind, number_value)
                if message is not None:
                    self._issue(number, letter, message)
        if kind is None and not kind_text and any(v is not None for v in values.values()):
            self._issue(number, "D", "kind is blank but the row has values")
        return FileRow(code, kind, values)  # discarded when the file has an issue

    def _number(self, raw: Any) -> tuple[Decimal | None, str]:
        """The cell as a number rounded to the stored 10 decimals (G15), or None and a hint."""
        if isinstance(raw, str) and "," in raw:
            if not self.comma_allowed or not _GROUPED.fullmatch(raw.strip().replace(" ", "")):
                return None, " (use a dot for decimals)"
        value = parse_number(raw)
        if value is None:
            return None, ""
        if abs(value) < _ROUNDED_BELOW:
            value = Decimal(_plain(value.quantize(SCALE)))
        return value, ""

    def _code(self, number: int, code: str, seen: set[str]) -> bool:
        if not code:
            self._issue(number, "A", "driver_code is blank")
            return False
        try:
            driver_def(code)
        except UnknownDriver as error:
            self._issue(number, "A", str(error))
            return False
        if code not in self.catalog:
            self._issue(number, "A", f"{code} is not a driver of this scenario's revenue method")
            return False
        if code in seen:
            self._issue(number, "A", f"{code} is given twice")
            return False
        seen.add(code)
        return True

    def _issue(self, row: int, column: str, message: str) -> None:
        self.issues.append(DriverFileIssue(row, column, message))


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


# The import plan ---------------------------------------------------------------------------------


def plan_import(plan: DriverFilePlan, own: Sequence[DriverRow]) -> DriverImport:
    """What importing `plan` does to the scenario's own rows `own` (every stored year). A file
    row replaces its driver's rows in the file's year columns; the driver's rows in other years
    stay when the kind is unchanged, and go when it changes (one driver stores one kind). A row
    with a blank kind clears every row of the driver. Values that are the same double are equal
    (the column is a REAL, G15). Only drivers with a change are in `rows`."""
    stored: dict[str, dict[int, DriverRow]] = {}
    for row in own:
        stored.setdefault(row.code, {})[row.fiscal_year] = row
    changes: list[DriverChange] = []
    rows: dict[str, list[DriverRow]] = {}
    for file_row in plan.rows:
        before = stored.get(file_row.code, {})
        after = _after(file_row, before)
        changed = [
            DriverChange(
                file_row.code,
                year,
                None if old is None else old.value,
                None if new is None else new.value,
                None if old is None else old.kind,
                None if new is None else new.kind,
            )
            for year in sorted(before.keys() | after.keys())
            if not _same(old := before.get(year), new := after.get(year))
        ]
        if changed:
            changes.extend(changed)
            rows[file_row.code] = [after[y] for y in sorted(after)]
    return DriverImport(changes, rows)


def _after(file_row: FileRow, before: Mapping[int, DriverRow]) -> dict[int, DriverRow]:
    kind = file_row.kind
    if kind is None:
        return {}
    kept = {y: r for y, r in before.items() if y not in file_row.values and r.kind == kind}
    given = {
        y: DriverRow(file_row.code, y, kind, v) for y, v in file_row.values.items() if v is not None
    }
    return kept | given


def _same(old: DriverRow | None, new: DriverRow | None) -> bool:
    if old is None or new is None:
        return old is new
    return old.kind == new.kind and float(old.value) == float(new.value)
