"""Driver files: a scenario's own drivers as CSV or xlsx, and an uploaded file back into the rows
it sets (docs/erd/forecasting.md "Driver files (M4)"). Pure.

The layout is one header row `driver_code, label, unit, kind, FY<year>…, FY<year>Q<n>…`, then one
row per driver. A cell is the scenario's own stored value (pct as a fraction), blank where it
inherits. The quarter columns are the quarters the forecast runs quarter by quarter. A year is set
either annually or by quarter (docs "Year modes"): the annual cell of a year set by quarter and the
quarter cells of a year set annually are blank in an export and an error in an import.
"""

import csv
import io
import re
import zipfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from bedrock.forecast.drivers import (
    QUARTERS,
    DriverDef,
    DriverKind,
    UnknownDriver,
    check_bounds,
    driver_def,
)
from bedrock.forecast.grid import DriverGrid, GridRow
from bedrock.forecast.resolve import DriverRow
from bedrock.ingest.manual_import import parse_number

HEADER = ("driver_code", "label", "unit", "kind")
DRIVERS_SHEET = "Drivers"
RESOLVED_SHEET = "Resolved"
MAX_ROWS = 1000  # far more than any catalog; a bigger file is not a driver file
_FORMATS = {"pct": "0.00%", "days": "0.0", "USD": "#,##0"}  # a USD fraction stays General
_YEAR = re.compile(r"FY(\d{4})", re.IGNORECASE)
_QUARTER = re.compile(r"FY(\d{4})Q([1-4])", re.IGNORECASE)
FY_FIRST = ("FY", *QUARTERS)  # the order of a year's periods
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
    """One driver of the file: its kind (None when blank) and a value or None per year column
    (`values`) and per quarter column (`quarter_values`, keyed by (fiscal year, "Q1".."Q4"))."""

    code: str
    kind: DriverKind | None
    values: dict[int, Decimal | None]
    quarter_values: dict[tuple[int, str], Decimal | None] = field(default_factory=dict)


@dataclass(frozen=True)
class DriverFilePlan:
    years: tuple[int, ...]  # the file's year columns, in file order
    rows: tuple[FileRow, ...]  # in file order
    quarters: tuple[tuple[int, str], ...] = ()  # the file's quarter columns, in file order


@dataclass(frozen=True)
class DriverChange:
    """A stored row the import changes: (kind, value) before and after; None where none."""

    driver_code: str
    fiscal_year: int
    old: Decimal | None
    new: Decimal | None
    old_kind: DriverKind | None
    new_kind: DriverKind | None
    fiscal_period: str = "FY"  # or the quarter, Q1..Q4, of `fiscal_year`


@dataclass(frozen=True)
class DriverImport:
    changes: list[DriverChange]
    rows: dict[str, list[DriverRow]]  # each changed driver -> all its rows after the import


# Export ------------------------------------------------------------------------------------------


def export_csv(grid: DriverGrid, quarterly: DriverGrid | None = None) -> bytes:
    """The Drivers table as UTF-8 CSV, numbers in plain decimal notation. `quarterly` (the same
    case's quarterly grid) adds a column per forecast quarter."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in _drivers_table(grid, quarterly):
        writer.writerow(
            "" if c is None else _plain(c) if isinstance(c, Decimal) else c for c in row
        )
    return out.getvalue().encode()


def export_xlsx(grid: DriverGrid, quarterly: DriverGrid | None = None) -> bytes:
    """Sheet Drivers (the CSV's table, cells formatted by unit) and sheet Resolved (history and
    resolved values with their source, for reference; never read back), with the quarters of
    `quarterly` after the years."""
    book = Workbook()
    drivers = book.active
    assert drivers is not None
    drivers.title = DRIVERS_SHEET
    _write(drivers, _drivers_table(grid, quarterly), [r.unit for r in grid.rows], len(HEADER))
    resolved = book.create_sheet(RESOLVED_SHEET)
    _write(resolved, _resolved_table(grid, quarterly), [r.unit for r in grid.rows], 3)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _period_key(year: int, period: str) -> str:
    return f"FY{year}" if period == "FY" else f"FY{year}{period}"


def _by_code(grid: DriverGrid | None) -> dict[str, GridRow]:
    return {} if grid is None else {r.code: r for r in grid.rows}


def _drivers_table(grid: DriverGrid, quarterly: DriverGrid | None = None) -> list[list[Any]]:
    quarters = [] if quarterly is None else quarterly.forecast_periods
    header = [
        *HEADER,
        *(f"FY{y}" for y in grid.forecast_years),
        *(_period_key(p.fiscal_year, p.fiscal_period) for p in quarters),
    ]
    table: list[list[Any]] = [header]
    by_code = _by_code(quarterly)
    modes = {m.fiscal_year: m.mode for m in grid.year_modes}
    for row in grid.rows:
        mine = by_code.get(row.code)
        # a driver that cannot be set per quarter has no row in the quarterly grid: blanks
        cells = [None] * len(quarters) if mine is None else mine.own
        table.append(
            [
                row.code,
                row.label,
                row.unit,
                row.kind,
                # the annual cell of a year set by quarter is hidden, the quarters of a year set
                # annually are empty: neither is part of the file
                *(
                    None if modes.get(y) == "quarterly" else v
                    for y, v in zip(grid.forecast_years, row.own, strict=True)
                ),
                *(
                    None if modes.get(p.fiscal_year) == "annual" else v
                    for p, v in zip(quarters, cells, strict=True)
                ),
            ]
        )
    return table


def _resolved_table(grid: DriverGrid, quarterly: DriverGrid | None = None) -> list[list[Any]]:
    forecast = [f"FY{y}E" for y in grid.forecast_years]
    header: list[Any] = [
        *HEADER[:3],
        *(f"FY{y}" for y in grid.history_years),
        *forecast,
        *(f"{f} source" for f in forecast),
    ]
    q_past = [] if quarterly is None else quarterly.history_periods
    q_next = [] if quarterly is None else quarterly.forecast_periods
    if quarterly is not None:
        q_forecast = [f"{_period_key(p.fiscal_year, p.fiscal_period)}E" for p in q_next]
        header += [
            *(_period_key(p.fiscal_year, p.fiscal_period) for p in q_past),
            *q_forecast,
            *(f"{f} source" for f in q_forecast),
        ]
    table: list[list[Any]] = [header]
    by_code = _by_code(quarterly)
    by_quarter = [m.mode == "quarterly" for m in grid.year_modes] or [False] * len(
        grid.forecast_years
    )
    for row in grid.rows:
        values = _resolved_values(row)
        sources: list[Any] = list(row.sources)
        for i, quarterly_year in enumerate(by_quarter):
            if quarterly_year:  # the year's figure is what its quarters add up to
                rolled = row.rollup[i] if i < len(row.rollup) else None
                values[i], sources[i] = rolled, "quarters"
        cells = [*row.history, *values, *sources]
        if quarterly is not None:
            mine = by_code.get(row.code)
            if mine is None:
                cells += [None] * (len(q_past) + 2 * len(q_next))
            else:
                cells += [*mine.history, *_resolved_values(mine), *mine.sources]
        table.append([row.code, row.label, row.unit, *cells])
    return table


def _resolved_values(row: GridRow) -> list[Any]:
    return [
        "flat" if v is None and s == "default" else v
        for v, s in zip(row.values, row.sources, strict=True)
    ]


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
    forecast_quarters: Sequence[tuple[int, str]] = (),
    quarterly_years: Collection[int] = (),
) -> DriverFilePlan:
    """The rows a CSV or xlsx file sets (xlsx: its Drivers sheet), told apart by the content
    (an xlsx is a zip) or a `.xlsx` name. `catalog` is the scenario's drivers, `forecast_quarters`
    the quarters the forecast runs quarter by quarter (the allowed `FY<yyyy>Q<n>` columns),
    `quarterly_years` the years set by quarter (a value under their annual column, or under the
    quarter column of any other year, is an error; a blank quarter has no row). `label` and
    `unit` are ignored. Raises DriverFileError with every error found."""
    if content.startswith(b"PK") or filename.lower().endswith(".xlsx"):
        rows, delimiter = _read_xlsx(content), None
    else:
        rows, delimiter = _read_csv(content)
    parser = _Parser(
        catalog, forecast_years, is_base, delimiter != ";", forecast_quarters, quarterly_years
    )
    return parser.run(rows)


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
        forecast_quarters: Sequence[tuple[int, str]] = (),
        quarterly_years: Collection[int] = (),
    ) -> None:
        self.quarterly_years = set(quarterly_years)
        self.comma_allowed = comma_allowed  # False in a `;` CSV, where a comma is a decimal one
        self.catalog = {d.code for d in catalog}
        self.per_quarter = {d.code for d in catalog if d.quarterly}
        self.forecast_years = list(forecast_years)
        self.forecast_quarters = list(forecast_quarters)
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
        years = tuple(c[0] for c in columns.values() if c[1] == "FY")
        quarters = tuple(c for c in columns.values() if c[1] != "FY")
        return DriverFilePlan(years, tuple(parsed), quarters)

    def _columns(
        self, number: int, header: list[Any], body: list[tuple[int, list[Any]]]
    ) -> dict[int, tuple[int, str]]:
        """Cell index -> (fiscal year, "FY" or the quarter) of each year and quarter column. A
        column with a blank header is skipped when it holds no value."""
        columns: dict[int, tuple[int, str]] = {}
        span = f"FY{self.forecast_years[0]}-FY{self.forecast_years[-1]}"
        quarters = (
            "no forecast quarters"
            if not self.forecast_quarters
            else f"{_period_key(*self.forecast_quarters[0])}-"
            f"{_period_key(*self.forecast_quarters[-1])}"
        )
        width = max(len(cells) for _, cells in [(number, header), *body])
        for index in range(len(HEADER), width):
            title = _text(_at(header, index))
            letter = get_column_letter(index + 1)
            if not title:
                for n, cells in body:
                    if not _blank(_at(cells, index)):
                        self._issue(n, letter, "A value under a column with no year")
                continue
            year_match, quarter_match = _YEAR.fullmatch(title), _QUARTER.fullmatch(title)
            column: tuple[int, str] | None = None
            if quarter_match:
                column = (int(quarter_match.group(1)), f"Q{quarter_match.group(2)}")
                if column not in self.forecast_quarters:
                    self._issue(
                        number, letter, f"Column '{title}' is not a forecast quarter ({quarters})"
                    )
                    continue
            elif year_match and int(year_match.group(1)) in self.forecast_years:
                column = (int(year_match.group(1)), "FY")
            else:
                self._issue(number, letter, f"Column '{title}' is not a forecast year ({span})")
                continue
            if column in columns.values():
                self._issue(number, letter, f"{_period_key(*column)} is given twice")
            else:
                columns[index] = column
        return columns

    def _row(
        self,
        number: int,
        cells: list[Any],
        columns: Mapping[int, tuple[int, str]],
        seen: set[str],
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
        quarter_values: dict[tuple[int, str], Decimal | None] = {}
        for index, (year, period) in columns.items():
            raw = _at(cells, index)
            if _blank(raw):
                cell = None
            else:
                letter = get_column_letter(index + 1)
                cell, hint = self._number(raw)
                if cell is None:
                    self._issue(number, letter, f"'{_text(raw)}' is not a number{hint}")
                    continue
                if period == "FY" and year in self.quarterly_years:
                    self._issue(number, letter, f"FY{year} is set by quarter")
                elif period != "FY" and year not in self.quarterly_years:
                    self._issue(
                        number, letter, f"FY{year} is set annually; switch it to by quarter first"
                    )
                elif period != "FY" and known and code not in self.per_quarter:
                    self._issue(number, letter, f"{code} cannot be set per quarter")
                elif known and kind is not None:
                    message = check_bounds(code, kind, cell)
                    if message is not None:
                        self._issue(number, letter, message)
            if period == "FY":
                values[year] = cell
            else:
                quarter_values[(year, period)] = cell
        given = [*values.values(), *quarter_values.values()]
        if kind is None and not kind_text and any(v is not None for v in given):
            self._issue(number, "D", "kind is blank but the row has values")
        return FileRow(code, kind, values, quarter_values)  # discarded when the file has an issue

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


def plan_import(
    plan: DriverFilePlan, own: Sequence[DriverRow], quarterly_years: Collection[int] = ()
) -> DriverImport:
    """What importing `plan` does to the scenario's own rows `own` (every year and quarter). A
    file row replaces its driver's rows in the file's year and quarter columns; the driver's rows
    in other periods stay when the kind is unchanged, and go when it changes (one driver stores
    one kind). A row with a blank kind clears every row of the driver. Values that are the same
    double are equal (the column is a REAL, G15). The annual cell of a year in `quarterly_years`
    (set by quarter) is hidden in the file: blank, it leaves the stored annual row alone. Only
    drivers with a change are in `rows`."""
    stored: dict[str, dict[tuple[int, str], DriverRow]] = {}
    for row in own:
        stored.setdefault(row.code, {})[(row.fiscal_year, row.fiscal_period)] = row
    changes: list[DriverChange] = []
    rows: dict[str, list[DriverRow]] = {}
    for file_row in plan.rows:
        before = stored.get(file_row.code, {})
        after = _after(file_row, before, set(quarterly_years))
        changed = [
            DriverChange(
                file_row.code,
                year,
                None if old is None else old.value,
                None if new is None else new.value,
                None if old is None else old.kind,
                None if new is None else new.kind,
                period,
            )
            for year, period in sorted(before.keys() | after.keys(), key=_order)
            if not _same(old := before.get((year, period)), new := after.get((year, period)))
        ]
        if changed:
            changes.extend(changed)
            rows[file_row.code] = [after[k] for k in sorted(after, key=_order)]
    return DriverImport(changes, rows)


def _order(key: tuple[int, str]) -> tuple[int, int]:
    """A year before its quarters, quarters in order."""
    return key[0], FY_FIRST.index(key[1])


def _after(
    file_row: FileRow, before: Mapping[tuple[int, str], DriverRow], quarterly_years: Collection[int]
) -> dict[tuple[int, str], DriverRow]:
    kind = file_row.kind
    if kind is None:
        return {}
    cells = {
        (y, "FY"): v
        for y, v in file_row.values.items()
        if v is not None or y not in quarterly_years
    } | file_row.quarter_values
    kept = {k: r for k, r in before.items() if k not in cells and r.kind == kind}
    given = {
        (y, p): DriverRow(file_row.code, y, kind, v, p)
        for (y, p), v in cells.items()
        if v is not None
    }
    return kept | given


def _same(old: DriverRow | None, new: DriverRow | None) -> bool:
    if old is None or new is None:
        return old is new
    return old.kind == new.kind and float(old.value) == float(new.value)
