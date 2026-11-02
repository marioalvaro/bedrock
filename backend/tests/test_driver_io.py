"""Driver files: CSV and xlsx export, parsing and the import plan (docs/erd/forecasting.md "Driver
files (M4)"). Pure, on synthetic grids."""

import csv
import io
import random
import zipfile
from dataclasses import replace
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from bedrock.forecast.driver_io import (
    DriverChange,
    DriverFileError,
    DriverFilePlan,
    FileRow,
    export_csv,
    export_xlsx,
    parse_driver_file,
    plan_import,
)
from bedrock.forecast.drivers import DriverDef, drivers_for
from bedrock.forecast.grid import DriverGrid, GridPeriod, GridRow
from bedrock.forecast.resolve import DriverRow

D = Decimal
YEARS = [2026, 2027, 2028]
CATALOG: list[DriverDef] = drivers_for("growth")
HEADER = ["driver_code", "label", "unit", "kind", "FY2026", "FY2027", "FY2028"]


def _row(
    code: str,
    own: list[Decimal | None],
    kind: str | None,
    values: list[Decimal | None] | None = None,
    sources: list[str | None] | None = None,
) -> GridRow:
    d = next(d for d in CATALOG if d.code == code)
    return GridRow(
        code=code,
        label=d.label,
        group=d.group,
        unit=d.unit,
        history=[D("0.1"), None, D("0.2")],
        values=values if values is not None else [D("0.05")] * len(YEARS),
        sources=sources if sources is not None else ["default"] * len(YEARS),  # type: ignore[list-item]
        own=own,
        kind=kind,  # type: ignore[arg-type]
    )


def _grid() -> DriverGrid:
    """Base-on-Bull style: an offset row, an inherited row, a flat one, a USD value row and a
    required driver with no value."""
    rows = {
        "revenue_growth": _row(
            "revenue_growth",
            [D("0.03"), D("0.03"), None],
            "offset",
            sources=["offset", "offset", "default"],
        ),
        "receivable_days": _row(
            "receivable_days", [None] * 3, None, values=[None] * 3, sources=["default"] * 3
        ),
        "tax_rate": _row("tax_rate", [None] * 3, None, values=[None] * 3, sources=[None] * 3),
        "buybacks": _row(
            "buybacks",
            [D("1000000"), D("2000000.5"), None],
            "value",
            sources=["own", "own", "default"],
        ),
    }
    ordered = [rows.get(d.code) or _row(d.code, [None] * 3, None) for d in CATALOG]
    return DriverGrid(1, "base", [2023, 2024, 2025], YEARS, ordered, [])


def _csv_rows(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8"))))


def _csv(rows: list[list[object]]) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue().encode()


def _xlsx(rows: list[list[object]], sheet: str = "Drivers") -> bytes:
    book = Workbook()
    page = book.active
    assert page is not None
    page.title = sheet
    for row in rows:
        page.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _parse(content: bytes, is_base: bool = False, name: str = "f.csv") -> DriverFilePlan:
    return parse_driver_file(content, name, CATALOG, YEARS, is_base)


def _errors(content: bytes, is_base: bool = False, name: str = "f.csv") -> list[tuple]:
    with pytest.raises(DriverFileError) as caught:
        _parse(content, is_base, name)
    return [(i.row, i.column, i.message) for i in caught.value.issues]


# Export ------------------------------------------------------------------------------------------


def test_the_csv_has_one_header_then_a_row_per_driver_in_catalog_order() -> None:
    rows = _csv_rows(export_csv(_grid()))

    assert rows[0] == HEADER
    assert [r[0] for r in rows[1:]] == [d.code for d in CATALOG]


def test_a_csv_row_holds_the_own_values_and_blanks_for_inherited_years() -> None:
    rows = {r[0]: r for r in _csv_rows(export_csv(_grid()))}

    assert rows["revenue_growth"][2:] == ["pct", "offset", "0.03", "0.03", ""]
    assert rows["buybacks"][2:] == ["USD", "value", "1000000", "2000000.5", ""]
    assert rows["gross_margin"][2:] == ["pct", "", "", "", ""]


def test_csv_numbers_are_plain_decimals_never_exponents() -> None:
    grid = _grid()
    big = [r for r in grid.rows if r.code != "buybacks"]
    big.append(_row("buybacks", [D("1E+14"), D("1E-10"), None], "value"))
    rows = {r[0]: r for r in _csv_rows(export_csv(DriverGrid(1, "base", [], YEARS, big, [])))}

    assert rows["buybacks"][4:] == ["100000000000000", "0.0000000001", ""]


def test_the_xlsx_drivers_sheet_matches_the_csv_with_percent_cells() -> None:
    book = load_workbook(io.BytesIO(export_xlsx(_grid())))
    sheet = book["Drivers"]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]

    assert book.sheetnames == ["Drivers", "Resolved"]
    assert rows[0] == HEADER
    assert [r[0] for r in rows[1:]] == [d.code for d in CATALOG]
    by_code = {r[0]: (n, r) for n, r in enumerate(rows, start=1)}
    number, growth = by_code["revenue_growth"]
    assert growth[3:] == ["offset", 0.03, 0.03, None]
    assert "%" in sheet.cell(row=number, column=5).number_format
    number, buybacks = by_code["buybacks"]
    assert buybacks[3:] == ["value", 1000000, 2000000.5, None]
    assert "%" not in sheet.cell(row=number, column=5).number_format


def test_the_resolved_sheet_lists_history_resolved_values_and_sources() -> None:
    sheet = load_workbook(io.BytesIO(export_xlsx(_grid())))["Resolved"]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]

    assert rows[0] == [
        "driver_code",
        "label",
        "unit",
        "FY2023",
        "FY2024",
        "FY2025",
        "FY2026E",
        "FY2027E",
        "FY2028E",
        "FY2026E source",
        "FY2027E source",
        "FY2028E source",
    ]
    by_code = {r[0]: r for r in rows[1:]}
    assert by_code["revenue_growth"][3:] == [
        0.1,
        None,
        0.2,
        0.05,
        0.05,
        0.05,
        "offset",
        "offset",
        "default",
    ]
    assert by_code["receivable_days"][6:] == [
        "flat",
        "flat",
        "flat",
        "default",
        "default",
        "default",
    ]
    assert by_code["tax_rate"][6:] == [None] * 6


# Parsing -----------------------------------------------------------------------------------------


def test_an_exported_csv_parses_back_to_the_own_rows() -> None:
    plan = _parse(export_csv(_grid()))

    assert plan.years == (2026, 2027, 2028)
    rows = {r.code: r for r in plan.rows}
    assert [r.code for r in plan.rows] == [d.code for d in CATALOG]
    assert rows["revenue_growth"] == FileRow(
        "revenue_growth", "offset", {2026: D("0.03"), 2027: D("0.03"), 2028: None}
    )
    assert rows["buybacks"].values == {2026: D("1000000"), 2027: D("2000000.5"), 2028: None}
    assert rows["gross_margin"] == FileRow("gross_margin", None, dict.fromkeys(YEARS))


def test_an_exported_xlsx_parses_back_to_the_own_rows() -> None:
    assert _parse(export_xlsx(_grid()), name="f.xlsx") == _parse(export_csv(_grid()))


def test_the_format_is_read_from_the_content_not_the_name() -> None:
    assert _parse(export_xlsx(_grid()), name="drivers.csv") == _parse(export_csv(_grid()))


def test_a_driver_absent_from_the_file_is_not_in_the_plan() -> None:
    plan = _parse(_csv([HEADER, ["gross_margin", "", "", "value", "0.4", "0.41", "0.42"]]))

    assert [r.code for r in plan.rows] == ["gross_margin"]


def test_text_numbers_follow_the_import_rules() -> None:
    plan = _parse(_csv([HEADER, ["buybacks", "", "", "offset", "1,000", "(5)", " 2.5 "]]))

    assert plan.rows[0].values == {2026: D(1000), 2027: D(-5), 2028: D("2.5")}


def test_kind_is_case_insensitive_and_blank_rows_are_skipped() -> None:
    plan = _parse(_csv([HEADER, [], ["gross_margin", "", "", " Value ", "0.4", "", ""]]))

    assert plan.rows[0].kind == "value"


def test_the_file_may_omit_forecast_year_columns() -> None:
    plan = _parse(_csv([HEADER[:5], ["gross_margin", "", "", "value", "0.4"]]))

    assert plan.years == (2026,)
    assert plan.rows[0].values == {2026: D("0.4")}


def test_a_semicolon_csv_is_read() -> None:
    text = "\n".join([";".join(HEADER), "gross_margin;;;value;0.4;;"]).encode()

    assert _parse(text).rows[0].values[2026] == D("0.4")


@pytest.mark.parametrize(
    ("row", "error"),
    [
        (["nope", "", "", "value", "1", "", ""], (2, "A", "Unknown driver 'nope'")),
        (
            ["segment_growth:7", "", "", "value", "0.1", "", ""],
            (2, "A", "segment_growth:7 is not a driver of this scenario's revenue method"),
        ),
        (
            ["volume_growth", "", "", "value", "0.1", "", ""],
            (2, "A", "volume_growth is not a driver of this scenario's revenue method"),
        ),
        (["", "Label", "", "value", "1", "", ""], (2, "A", "driver_code is blank")),
        (
            ["gross_margin", "", "", "values", "0.4", "", ""],
            (2, "D", "kind must be value, offset or blank"),
        ),
        (
            ["gross_margin", "", "", "", "0.4", "", ""],
            (2, "D", "kind is blank but the row has values"),
        ),
        (["gross_margin", "", "", "value", "1e5", "", ""], (2, "E", "'1e5' is not a number")),
        (["gross_margin", "", "", "value", "", "²", ""], (2, "F", "'²' is not a number")),
        (["gross_margin", "", "", "value", "", "", "abc"], (2, "G", "'abc' is not a number")),
        (
            ["gross_margin", "", "", "value", "1.5", "", ""],
            (2, "E", "gross_margin must be in [-1, 1]"),
        ),
        (
            ["gross_margin", "", "", "offset", "", "-2", ""],
            (2, "F", "gross_margin offset must be in [-1, 1]"),
        ),
        (
            ["buybacks", "", "", "value", "1000000000000000", "", ""],
            (2, "E", "buybacks must be in [0, 10^15)"),
        ),
    ],
)
def test_each_row_error_names_its_row_and_column(row: list[str], error: tuple) -> None:
    assert _errors(_csv([HEADER, row])) == [error]


def test_an_offset_on_base_is_an_error() -> None:
    content = _csv([HEADER, ["gross_margin", "", "", "offset", "0.01", "", ""]])

    assert _errors(content, is_base=True) == [(2, "D", "Base cannot hold offsets")]
    assert _parse(content).rows[0].kind == "offset"


def test_a_column_that_is_not_a_forecast_year_is_an_error() -> None:
    content = _csv([[*HEADER, "FY2040", "Notes"], ["gross_margin", "", "", "value", "", "", ""]])

    assert _errors(content) == [
        (1, "H", "Column 'FY2040' is not a forecast year (FY2026-FY2028)"),
        (1, "I", "Column 'Notes' is not a forecast year (FY2026-FY2028)"),
    ]


def test_a_blank_column_is_ignored_unless_it_holds_values() -> None:
    assert _parse(_csv([[*HEADER, ""], ["gross_margin", "", "", "value", "", "", "", ""]])).rows
    content = _csv([[*HEADER, ""], ["gross_margin", "", "", "value", "", "", "", "0.4"]])

    assert _errors(content) == [(2, "H", "A value under a column with no year")]


def test_a_year_or_a_driver_given_twice_is_an_error() -> None:
    assert _errors(_csv([[*HEADER, "FY2027"]])) == [(1, "H", "FY2027 is given twice")]
    row = ["gross_margin", "", "", "value", "", "", ""]
    assert _errors(_csv([HEADER, row, row])) == [(3, "A", "gross_margin is given twice")]


def test_a_bad_header_is_an_error() -> None:
    assert _errors(_csv([["code", "label", "unit", "kind", "FY2026"]])) == [
        (1, "A", "The header must start with driver_code, label, unit, kind")
    ]


def test_an_empty_file_is_an_error() -> None:
    assert _errors(b"") == [(None, None, "The file is empty")]


def test_every_error_is_reported_in_file_order() -> None:
    content = _csv(
        [
            HEADER,
            ["nope", "", "", "value", "", "", ""],
            ["gross_margin", "", "", "value", "x", "2", ""],
        ]
    )

    assert _errors(content) == [
        (2, "A", "Unknown driver 'nope'"),
        (3, "E", "'x' is not a number"),
        (3, "F", "gross_margin must be in [-1, 1]"),
    ]


def test_an_xlsx_without_a_drivers_sheet_is_an_error() -> None:
    content = _xlsx([HEADER], sheet="Other")

    assert _errors(content, name="f.xlsx") == [(None, None, "The workbook has no Drivers sheet")]


def test_a_broken_xlsx_and_non_utf8_text_are_errors() -> None:
    assert _errors(b"PK\x03\x04broken", name="f.xlsx") == [
        (None, None, "The file is not a valid .xlsx workbook")
    ]
    assert _errors(b"\xff\xfe\x00bad", name="f.csv") == [(None, None, "The file is not UTF-8 text")]


def test_a_decimal_comma_is_an_error_not_a_bigger_number() -> None:
    """Excel in a European locale writes `;` CSVs with decimal commas: 0,03 must not read as 3."""
    semicolon = "\n".join([";".join(HEADER), "revenue_growth;;;value;0,03;1,000;"]).encode()
    quoted = _csv([HEADER, ["revenue_growth", "", "", "value", "0,03", "", ""]])
    hint = "use a dot for decimals"

    assert _errors(semicolon) == [
        (2, "E", f"'0,03' is not a number ({hint})"),
        (2, "F", f"'1,000' is not a number ({hint})"),
    ]
    assert _errors(quoted) == [(2, "E", f"'0,03' is not a number ({hint})")]
    assert _parse(_csv([HEADER, ["buybacks", "", "", "value", "12,345,678.5", "", ""]])).rows[
        0
    ].values[2026] == D("12345678.5")


def test_values_are_rounded_to_the_stored_ten_decimals() -> None:
    """Excel arithmetic gives 0.04000000000000001; the column keeps 10 decimals (G15), so an
    unrounded value would show as a change on every import."""
    content = _csv([HEADER, ["gross_margin", "", "", "value", "0.04000000000000001", "", ""]])

    plan = _parse(content)

    assert str(plan.rows[0].values[2026]) == "0.04"
    assert plan_import(plan, _own("gross_margin", "value", {2026: "0.04"})).changes == []


@pytest.mark.parametrize("part", ["xl/worksheets/sheet1.xml", "xl/workbook.xml", "xl/styles.xml"])
def test_a_corrupt_workbook_part_is_an_error_not_a_crash(part: str) -> None:
    source = zipfile.ZipFile(
        io.BytesIO(_xlsx([HEADER, ["gross_margin", None, None, "value", 0.4]]))
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as broken:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == part:
                data = data[: len(data) // 2]
            broken.writestr(item, data)

    assert _errors(out.getvalue(), name="f.xlsx") == [
        (None, None, "The file is not a valid .xlsx workbook")
    ]


def test_xlsx_cells_typed_as_numbers_and_booleans() -> None:
    content = _xlsx([HEADER, ["gross_margin", None, None, "value", 0.4, 1, True]])

    assert _errors(content, name="f.xlsx") == [(2, "G", "'True' is not a number")]


def test_an_xlsx_infinite_cell_is_not_a_number() -> None:
    content = _xlsx([HEADER, ["buybacks", None, None, "value", "inf", None, None]])

    assert _errors(content, name="f.xlsx") == [(2, "E", "'inf' is not a number")]


# The import plan ---------------------------------------------------------------------------------


def _own(code: str, kind: str, values: dict[int, str]) -> list[DriverRow]:
    return [DriverRow(code, y, kind, D(v)) for y, v in values.items()]  # type: ignore[arg-type]


def _plan(*rows: FileRow, years: tuple[int, ...] = tuple(YEARS)) -> DriverFilePlan:
    return DriverFilePlan(years, rows)


def test_an_unchanged_file_has_no_changes_and_nothing_to_write() -> None:
    own = _own("gross_margin", "offset", {2026: "0.01", 2027: "0.01"})
    file = FileRow("gross_margin", "offset", {2026: D("0.01"), 2027: D("0.010"), 2028: None})

    result = plan_import(_plan(file), own)

    assert result.changes == []
    assert result.rows == {}


def test_one_edited_cell_is_one_change_and_rewrites_its_driver() -> None:
    own = _own("gross_margin", "value", {2026: "0.4", 2027: "0.4"})
    file = FileRow("gross_margin", "value", {2026: D("0.4"), 2027: D("0.45"), 2028: None})

    result = plan_import(_plan(file), own)

    assert result.changes == [
        DriverChange("gross_margin", 2027, D("0.4"), D("0.45"), "value", "value")
    ]
    assert result.rows == {
        "gross_margin": [
            DriverRow("gross_margin", 2026, "value", D("0.4")),
            DriverRow("gross_margin", 2027, "value", D("0.45")),
        ]
    }


def test_rows_outside_the_file_years_are_kept_when_the_kind_stays() -> None:
    own = _own("revenue_growth", "offset", {y: "0.03" for y in range(2026, 2036)})
    file = FileRow("revenue_growth", "offset", {2026: D("0.04"), 2027: D("0.03"), 2028: D("0.03")})

    result = plan_import(_plan(file), own)

    assert [c.fiscal_year for c in result.changes] == [2026]
    assert [r.fiscal_year for r in result.rows["revenue_growth"]] == list(range(2026, 2036))
    assert result.rows["revenue_growth"][0].value == D("0.04")


def test_a_kind_change_drops_the_rows_outside_the_file_years() -> None:
    own = _own("revenue_growth", "offset", {2026: "0.03", 2029: "0.03"})
    file = FileRow("revenue_growth", "value", {2026: D("0.03"), 2027: None, 2028: None})

    result = plan_import(_plan(file), own)

    assert result.changes == [
        DriverChange("revenue_growth", 2026, D("0.03"), D("0.03"), "offset", "value"),
        DriverChange("revenue_growth", 2029, D("0.03"), None, "offset", None),
    ]
    assert result.rows == {
        "revenue_growth": [DriverRow("revenue_growth", 2026, "value", D("0.03"))]
    }


def test_an_all_blank_row_clears_every_row_of_the_driver() -> None:
    own = _own("revenue_growth", "offset", {2026: "0.03", 2035: "0.03"})
    file = FileRow("revenue_growth", None, dict.fromkeys(YEARS))

    result = plan_import(_plan(file), own)

    assert [(c.fiscal_year, c.new, c.new_kind) for c in result.changes] == [
        (2026, None, None),
        (2035, None, None),
    ]
    assert result.rows == {"revenue_growth": []}


def test_a_new_driver_adds_rows_and_a_driver_absent_from_the_file_is_untouched() -> None:
    own = _own("tax_rate", "value", {2026: "0.2"})
    file = FileRow("gross_margin", "value", {2026: D("0.4"), 2027: None, 2028: None})

    result = plan_import(_plan(file), own)

    assert result.changes == [DriverChange("gross_margin", 2026, None, D("0.4"), None, "value")]
    assert set(result.rows) == {"gross_margin"}


def test_values_stored_as_the_same_double_are_not_a_change() -> None:
    """SQLite stores the value as a REAL (G15): 1234567.89 reads back as 1234567.8899999999."""
    own = _own("buybacks", "value", {2026: "1234567.8899999999"})
    file = FileRow("buybacks", "value", {2026: D("1234567.89"), 2027: None, 2028: None})

    assert plan_import(_plan(file), own).changes == []


def test_changes_follow_the_file_order_then_the_year() -> None:
    file_a = FileRow("tax_rate", "value", {2026: D("0.2"), 2027: D("0.2"), 2028: None})
    file_b = FileRow("gross_margin", "value", {2026: D("0.4"), 2027: None, 2028: None})

    result = plan_import(_plan(file_a, file_b), [])

    assert [(c.driver_code, c.fiscal_year) for c in result.changes] == [
        ("tax_rate", 2026),
        ("tax_rate", 2027),
        ("gross_margin", 2026),
    ]


# Round-trip --------------------------------------------------------------------------------------


def _random_grid(rng: random.Random) -> tuple[DriverGrid, list[DriverRow]]:
    rows: list[GridRow] = []
    own_rows: list[DriverRow] = []
    for d in CATALOG:
        kind = rng.choice(["value", "offset", None])
        own: list[Decimal | None] = [None] * len(YEARS)
        if kind is not None:
            for i, year in enumerate(YEARS):
                if rng.random() < 0.7:
                    own[i] = _random_value(rng, d.unit, kind)
                    own_rows.append(DriverRow(d.code, year, kind, own[i]))  # type: ignore[arg-type]
        stored = kind if any(v is not None for v in own) else None
        rows.append(_row(d.code, own, stored))
    return DriverGrid(1, "base", [2023, 2024, 2025], YEARS, rows, []), own_rows


def _random_value(rng: random.Random, unit: str, kind: str) -> Decimal:
    """A value inside every bound of its unit and kind, with at most 10 decimals (the column's
    scale) and 15 significant digits (what the stored REAL keeps)."""
    sign = rng.choice([-1, 1]) if kind == "offset" else 1
    if unit == "pct":
        return sign * D(rng.randint(0, 9_999_999_999)) / D(10**10)
    if unit == "days":
        return sign * D(rng.randint(0, 7_300_000)) / D(10_000)
    return sign * D(rng.randint(0, 10**14 - 1)) / D(rng.choice([1, 10, 100]))


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_export_then_import_changes_nothing(seed: int, fmt: str) -> None:
    grid, own = _random_grid(random.Random(seed))
    content = export_csv(grid) if fmt == "csv" else export_xlsx(grid)

    plan = _parse(content, name=f"f.{fmt}")

    assert plan_import(plan, own).changes == []
    assert plan_import(plan, []).rows == {
        code: rows for code in {r.code for r in own} if (rows := [r for r in own if r.code == code])
    }


# Quarter columns (docs/erd/forecasting.md "Quarterly drivers" -> Driver files) -------------------

QUARTERS = [(2026, "Q3"), (2026, "Q4"), (2027, "Q1")]
QHEADER = [*HEADER, "FY2026Q3", "FY2026Q4", "FY2027Q1"]


def _qgrid_rows(quarter_own: dict[str, list[Decimal | None]]) -> DriverGrid:
    """The quarterly grid beside `_grid()`: a row per driver, history of 2 quarters."""
    rows = [
        GridRow(
            code=d.code,
            label=d.label,
            group=d.group,
            unit=d.unit,
            history=[D("0.1"), None],
            values=[D("0.07")] * 3,
            sources=["year", "year", "year"],
            own=quarter_own.get(d.code, [None] * 3),
            kind="value" if d.code in quarter_own else None,
        )
        for d in CATALOG
    ]
    return DriverGrid(
        1,
        "base",
        [2023, 2024, 2025],
        YEARS,
        rows,
        [],
        "quarterly",
        [GridPeriod(2025, "Q3", "Q3 FY25A"), GridPeriod(2025, "Q4", "Q4 FY25A")],
        [GridPeriod(y, q, f"{q} FY{y % 100}E") for y, q in QUARTERS],
    )


QUARTER_OWN = {
    "gross_margin": [D("0.45"), None, D("0.5")],
    "buybacks": [D("250000"), None, None],
}


def _with_quarters() -> tuple[DriverGrid, DriverGrid]:
    """The annual grid and the quarterly one of a case whose gross margin has only quarter rows
    (the kind of a driver is the same in both grids)."""
    grid = _grid()
    rows = [replace(r, kind="value") if r.code == "gross_margin" else r for r in grid.rows]
    return replace(grid, rows=rows), _qgrid_rows(QUARTER_OWN)


def _qparse(content: bytes, is_base: bool = False, name: str = "f.csv") -> DriverFilePlan:
    return parse_driver_file(content, name, CATALOG, YEARS, is_base, QUARTERS)


def _qerrors(
    content: bytes, is_base: bool = False, catalog: list[DriverDef] | None = None
) -> list[tuple[int | None, str | None, str]]:
    with pytest.raises(DriverFileError) as caught:
        parse_driver_file(content, "f.csv", catalog or CATALOG, YEARS, is_base, QUARTERS)
    return [(i.row, i.column, i.message) for i in caught.value.issues]


def test_the_csv_adds_a_column_per_span_quarter_after_the_years() -> None:
    annual, quarterly = _with_quarters()

    rows = {r[0]: r for r in _csv_rows(export_csv(annual, quarterly))}

    assert rows["driver_code"] == QHEADER
    assert rows["gross_margin"][2:] == ["pct", "value", "", "", "", "0.45", "", "0.5"]
    assert rows["buybacks"][2:] == ["USD", "value", "1000000", "2000000.5", "", "250000", "", ""]
    assert rows["revenue_growth"][4:] == ["0.03", "0.03", "", "", "", ""]  # annual cells as before


def test_without_a_quarterly_grid_the_file_is_the_years_only_file() -> None:
    assert export_csv(_grid(), None) == export_csv(_grid())
    assert _csv_rows(export_csv(_grid(), None))[0] == HEADER


def test_the_xlsx_quarter_cells_follow_the_unit_formats() -> None:
    annual, quarterly = _with_quarters()
    sheet = load_workbook(io.BytesIO(export_xlsx(annual, quarterly)))["Drivers"]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]

    assert rows[0] == QHEADER
    number, gross = next((n, r) for n, r in enumerate(rows, start=1) if r[0] == "gross_margin")
    assert gross[7:] == [0.45, None, 0.5]
    assert "%" in sheet.cell(row=number, column=8).number_format


def test_the_resolved_sheet_adds_the_quarters_history_values_and_sources() -> None:
    annual, quarterly = _with_quarters()
    sheet = load_workbook(io.BytesIO(export_xlsx(annual, quarterly)))["Resolved"]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]

    assert rows[0][12:] == [
        "FY2025Q3",
        "FY2025Q4",
        "FY2026Q3E",
        "FY2026Q4E",
        "FY2027Q1E",
        "FY2026Q3E source",
        "FY2026Q4E source",
        "FY2027Q1E source",
    ]
    gross = next(r for r in rows[1:] if r[0] == "gross_margin")
    assert gross[12:] == [0.1, None, 0.07, 0.07, 0.07, "year", "year", "year"]


def test_an_exported_file_with_quarters_parses_back_to_the_own_cells() -> None:
    annual, quarterly = _with_quarters()
    plan = _qparse(export_csv(annual, quarterly))

    assert plan.years == (2026, 2027, 2028)
    assert plan.quarters == tuple(QUARTERS)
    rows = {r.code: r for r in plan.rows}
    assert rows["gross_margin"].quarter_values == {
        (2026, "Q3"): D("0.45"),
        (2026, "Q4"): None,
        (2027, "Q1"): D("0.5"),
    }
    assert rows["gross_margin"].kind == "value"
    assert rows["buybacks"].quarter_values[(2026, "Q3")] == D("250000")


def test_a_file_may_omit_the_quarter_columns_and_an_old_file_parses_as_before() -> None:
    plan = _qparse(export_csv(_grid()))

    assert plan.quarters == ()
    assert plan.rows[0].quarter_values == {}


def test_a_quarter_column_that_is_not_in_the_span_is_an_error_at_its_header() -> None:
    header = [*HEADER, "FY2099Q1", "FY2026Q5", "FY2026Q3", "FY2026Q3"]

    errors = _qerrors(_csv([header, ["gross_margin", "", "", "value", "", "", "", "0.4"]]))

    span = "FY2026Q3-FY2027Q1"
    assert (1, "H", f"Column 'FY2099Q1' is not a forecast quarter ({span})") in errors
    assert any(e[:2] == (1, "I") for e in errors)  # FY2026Q5 is neither a year nor a quarter
    assert (1, "K", "FY2026Q3 is given twice") in errors


def test_a_quarter_cell_is_checked_like_a_year_cell() -> None:
    rows = [
        QHEADER,
        ["gross_margin", "", "", "value", "", "", "", "1.5", "1e5", "0,4"],
        ["tax_rate", "", "", "offset", "", "", "", "0.01"],
    ]

    errors = _qerrors(_csv(rows), is_base=True)

    assert (2, "H", "gross_margin must be in [-1, 1]") in errors
    assert (2, "I", "'1e5' is not a number") in errors
    assert (2, "J", "'0,4' is not a number (use a dot for decimals)") in errors
    assert (3, "D", "Base cannot hold offsets") in errors


def test_a_value_under_a_quarter_column_of_a_driver_that_cannot_be_set_per_quarter() -> None:
    annual_only = [replace(d, quarterly=False) if d.code == "tax_rate" else d for d in CATALOG]
    rows = [QHEADER, ["tax_rate", "", "", "value", "", "", "", "0.2"]]

    assert _qerrors(_csv(rows), catalog=annual_only) == [
        (2, "H", "tax_rate cannot be set per quarter")
    ]


def test_a_quarter_row_replaces_the_quarters_in_the_file_and_keeps_the_others() -> None:
    own = [
        DriverRow("gross_margin", 2026, "value", D("0.4")),
        DriverRow("gross_margin", 2026, "value", D("0.41"), "Q3"),
        DriverRow("gross_margin", 2026, "value", D("0.42"), "Q4"),
        DriverRow("gross_margin", 2028, "value", D("0.43"), "Q1"),  # a quarter outside the file
    ]
    file = FileRow(
        "gross_margin",
        "value",
        {2026: D("0.4")},
        {(2026, "Q3"): D("0.5"), (2026, "Q4"): None, (2027, "Q1"): D("0.6")},
    )
    plan = DriverFilePlan((2026,), (file,), tuple(QUARTERS))

    result = plan_import(plan, own)

    assert result.changes == [
        DriverChange("gross_margin", 2026, D("0.41"), D("0.5"), "value", "value", "Q3"),
        DriverChange("gross_margin", 2026, D("0.42"), None, "value", None, "Q4"),
        DriverChange("gross_margin", 2027, None, D("0.6"), None, "value", "Q1"),
    ]
    assert sorted((r.fiscal_year, r.fiscal_period) for r in result.rows["gross_margin"]) == [
        (2026, "FY"),
        (2026, "Q3"),
        (2027, "Q1"),
        (2028, "Q1"),
    ]


def test_a_kind_change_drops_the_quarters_too() -> None:
    own = [
        DriverRow("gross_margin", 2026, "offset", D("0.01")),
        DriverRow("gross_margin", 2028, "offset", D("0.02"), "Q1"),
    ]
    file = FileRow("gross_margin", "value", {2026: D("0.4")}, {})

    result = plan_import(DriverFilePlan((2026,), (file,), ()), own)

    assert [(c.fiscal_year, c.fiscal_period, c.new) for c in result.changes] == [
        (2026, "FY", D("0.4")),
        (2028, "Q1", None),
    ]
    assert [(r.fiscal_year, r.fiscal_period) for r in result.rows["gross_margin"]] == [(2026, "FY")]


def test_a_blank_kind_clears_the_quarters_as_well() -> None:
    own = [DriverRow("gross_margin", 2026, "value", D("0.4"), "Q3")]
    file = FileRow("gross_margin", None, dict.fromkeys(YEARS), dict.fromkeys(QUARTERS))

    result = plan_import(DriverFilePlan(tuple(YEARS), (file,), tuple(QUARTERS)), own)

    assert [(c.fiscal_period, c.new) for c in result.changes] == [("Q3", None)]
    assert result.rows == {"gross_margin": []}


def _random_quarters(rng: random.Random, rows: list[GridRow]) -> tuple[DriverGrid, list[DriverRow]]:
    """A quarterly grid whose rows hold random own quarter values of their driver's kind."""
    quarter_rows: list[GridRow] = []
    stored: list[DriverRow] = []
    for row in rows:
        own: list[Decimal | None] = [None] * len(QUARTERS)
        if row.kind is not None:
            for i, (year, quarter) in enumerate(QUARTERS):
                if rng.random() < 0.5:
                    own[i] = _random_value(rng, row.unit, row.kind)
                    stored.append(DriverRow(row.code, year, row.kind, own[i], quarter))  # type: ignore[arg-type]
        quarter_rows.append(replace(row, history=[None, None], values=[None] * 3, own=own))
    grid = _qgrid_rows({})
    return replace(grid, rows=quarter_rows), stored


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_export_then_import_with_quarter_values_changes_nothing(seed: int, fmt: str) -> None:
    rng = random.Random(seed)
    annual, own = _random_grid(rng)
    quarterly, quarter_rows = _random_quarters(rng, annual.rows)
    content = (export_csv if fmt == "csv" else export_xlsx)(annual, quarterly)

    plan = _qparse(content, name=f"f.{fmt}")

    assert plan_import(plan, [*own, *quarter_rows]).changes == []
    again = plan_import(plan, [])
    stored_back = [r for rows in again.rows.values() for r in rows if r.fiscal_period != "FY"]
    assert sorted((r.code, r.fiscal_year, r.fiscal_period) for r in stored_back) == sorted(
        (r.code, r.fiscal_year, r.fiscal_period) for r in quarter_rows
    )
