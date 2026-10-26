"""The import template: sheets, header rows, one row per canonical item, prefill (erd/data.md,
"Template")."""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from bedrock.ingest.import_template import build_template
from bedrock.ingest.manual_import import ImportParseError, parse_import
from bedrock.mapping.config import load_canonical_items
from bedrock.statements.periods import Period

ITEMS = load_canonical_items()
FY24 = Period("FY2024", "FY24", 2024, "FY", date(2023, 10, 1), date(2024, 9, 28))
Q4_24 = Period("FY2024Q4", "Q4 FY24", 2024, "Q4", date(2024, 6, 30), date(2024, 9, 28))
PERIODS = [FY24, Q4_24]


def sheet_rows(content: bytes, name: str) -> list[list[object]]:
    book = load_workbook(io.BytesIO(content), data_only=True)
    return [list(r) for r in book[name].iter_rows(values_only=True)]


def test_the_workbook_has_the_four_sheets_and_a_scale() -> None:
    content = build_template(ITEMS, PERIODS, "xlsx", "millions")

    book = load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["Instructions", "IS", "BS", "CF"]
    scale = [r for r in sheet_rows(content, "Instructions") if r and r[0] == "scale"]
    assert scale == [["scale", "millions"]]


def test_the_instructions_say_how_to_add_a_custom_line_and_mark_a_breakdown_complete() -> None:
    rows = sheet_rows(build_template(ITEMS, PERIODS, "xlsx", "millions"), "Instructions")

    text = " ".join(str(r[0]) for r in rows if r and r[0])
    assert "custom:" in text and "parent" in text
    assert "children_complete" in text and "complete" in text


def test_a_statement_sheet_has_four_header_rows_and_the_period_columns() -> None:
    rows = sheet_rows(build_template(ITEMS, PERIODS, "xlsx", "units"), "IS")

    assert rows[0][:6] == ["fiscal_year", None, None, None, None, 2024]
    assert rows[1][5:7] == ["FY", "Q4"]
    assert rows[2][5:7] == ["2023-10-01", "2024-06-30"]
    assert rows[3][5:7] == ["2024-09-28", "2024-09-28"]
    assert rows[3][0] == "period_end"
    assert rows[4][:5] == ["code", "label", "parent", "unit", "children_complete"]


@pytest.mark.parametrize("statement", ["IS", "BS", "CF"])
def test_every_canonical_item_appears_once_in_display_order(statement: str) -> None:
    rows = sheet_rows(build_template(ITEMS, PERIODS, "xlsx", "units"), statement)[5:]

    expected = [i for i in ITEMS if i.statement == statement]
    assert [r[0] for r in rows] == [i.code for i in expected]
    first = rows[0]
    assert (first[1], first[2], first[3]) == (
        expected[0].label,
        expected[0].parent or None,
        expected[0].unit,
    )


def test_read_only_rows_are_grey_and_everything_else_is_not() -> None:
    book = load_workbook(io.BytesIO(build_template(ITEMS, PERIODS, "xlsx", "units")))
    sheet = book["IS"]
    grey = {
        sheet.cell(row=r, column=1).value
        for r in range(6, sheet.max_row + 1)
        if sheet.cell(row=r, column=1).fill.fgColor.rgb not in (None, "00000000")
    }

    read_only = {
        i.code
        for i in ITEMS
        if i.statement == "IS" and (i.residual or (i.derive and not i.concepts))
    }
    assert grey == read_only and "other_operating_expenses" in grey


def test_prefill_writes_the_displayed_values_in_the_chosen_scale() -> None:
    values = {
        ("revenue", "FY2024"): Decimal(391_035_000_000),
        ("eps_diluted", "FY2024"): Decimal("6.08"),
        ("shares_diluted", "FY2024"): Decimal(15_408_095_000),
        ("other_operating_expenses", "FY2024"): Decimal(5),  # read-only: left blank
    }

    rows = sheet_rows(build_template(ITEMS, PERIODS, "xlsx", "millions", values), "IS")

    by_code = {r[0]: r[5:7] for r in rows[5:]}
    assert by_code["revenue"] == [391035, None]
    assert by_code["eps_diluted"] == [6.08, None]
    assert by_code["shares_diluted"] == [15408.095, None]
    assert by_code["other_operating_expenses"] == [None, None]


def test_the_csv_form_has_a_leading_statement_column_and_the_same_content() -> None:
    values = {("revenue", "FY2024"): Decimal(391_035_000_000)}
    xlsx = build_template(ITEMS, PERIODS, "xlsx", "millions", values)
    text = build_template(ITEMS, PERIODS, "csv", "millions", values).decode()

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["scale", "millions"]
    income = [r for r in rows if r and r[0] == "IS"]
    assert income[0][1] == "fiscal_year"
    revenue = next(r for r in income if r[1] == "revenue")
    assert revenue[6] == "391035"
    assert [r[1] for r in income[5:]] == [r[0] for r in sheet_rows(xlsx, "IS")[5:]]
    assert {r[0] for r in rows[1:]} == {"IS", "BS", "CF"}


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_a_prefilled_template_parses_back_to_the_same_values(fmt: str) -> None:
    values = {
        ("revenue", "FY2024"): Decimal(391_035_000_000),
        ("capex", "FY2024"): Decimal(-9_447_000_000),  # displayed negative
        ("eps_diluted", "FY2024Q4"): Decimal("0.97"),
        ("cash", "FY2024"): Decimal(29_943_000_000),
    }

    content = build_template(ITEMS, PERIODS, fmt, "millions", values)  # type: ignore[arg-type]
    plan = parse_import(content, f"t.{fmt}", ITEMS)

    by_key = {(v.code, v.period_key): v.value for v in plan.values}
    sign = {i.code: i.sign for i in ITEMS}
    assert by_key == {key: value * sign[key[0]] for key, value in values.items()}


def test_a_blank_template_has_no_values_to_import() -> None:
    content = build_template(ITEMS, PERIODS, "xlsx", "units")

    with pytest.raises(ImportParseError) as raised:
        parse_import(content, "t.xlsx", ITEMS)

    assert "no values" in raised.value.errors[0].message


def test_a_company_with_no_periods_still_gets_a_valid_layout() -> None:
    content = build_template(ITEMS, [], "xlsx", "units")

    rows = sheet_rows(content, "IS")
    assert rows[0][0] == "fiscal_year"
    assert len(rows) == 5 + len([i for i in ITEMS if i.statement == "IS"])
