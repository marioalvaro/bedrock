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
from bedrock.statements.fiscal_grid import annual_then_quarterly, period_grid
from bedrock.statements.periods import Period

ITEMS = load_canonical_items()
FY24 = Period("FY2024", "FY24", 2024, "FY", date(2023, 10, 1), date(2024, 9, 28))
Q4_24 = Period("FY2024Q4", "Q4 FY24", 2024, "Q4", date(2024, 6, 30), date(2024, 9, 28))
PERIODS = [FY24, Q4_24]
FYE = date(2024, 9, 28)
HEADERS = 2  # fiscal_year and fiscal_period; the dates come from the fiscal year end
FIRST_LINE = HEADERS + 1  # after the column titles


def template(fmt: str = "xlsx", scale: str = "millions", values: object = None) -> bytes:
    return build_template(ITEMS, PERIODS, fmt, scale, values, FYE)  # type: ignore[arg-type]


def sheet_rows(content: bytes, name: str) -> list[list[object]]:
    book = load_workbook(io.BytesIO(content), data_only=True)
    return [list(r) for r in book[name].iter_rows(values_only=True)]


def test_the_workbook_has_the_four_sheets_and_a_scale() -> None:
    content = template()

    book = load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["Instructions", "IS", "BS", "CF"]
    scale = [r[:2] for r in sheet_rows(content, "Instructions") if r and r[0] == "scale"]
    assert scale == [["scale", "millions"]]


def test_the_instructions_say_how_to_add_a_custom_line_and_mark_a_breakdown_complete() -> None:
    rows = sheet_rows(template(), "Instructions")

    text = " ".join(str(r[0]) for r in rows if r and r[0])
    assert "custom:" in text and "parent" in text
    assert "children_complete" in text and "complete" in text


def test_a_statement_sheet_has_two_header_rows_and_no_dates() -> None:
    rows = sheet_rows(template(scale="units"), "IS")

    assert rows[0][:6] == ["fiscal_year", None, None, None, None, 2024]
    assert rows[1][:6] == ["fiscal_period", None, None, None, None, "FY"]
    assert rows[0][5:7] == [2024, 2024] and rows[1][5:7] == ["FY", "Q4"]
    assert rows[2][:5] == ["code", "label", "parent", "unit", "children_complete"]
    assert rows[2][5:7] == ["FY24", "Q4 FY24"]
    assert not any(str(r[0]) in ("period_start", "period_end") for r in rows)


def test_the_fiscal_year_end_is_on_the_instructions_next_to_the_scale() -> None:
    rows = sheet_rows(template(), "Instructions")

    assert [r[:2] for r in rows if r and r[0] == "fiscal_year_end"] == [
        ["fiscal_year_end", "2024-09-28"]
    ]
    assert [r[0] for r in rows[:2]] == ["scale", "fiscal_year_end"]


def test_the_csv_carries_the_fiscal_year_end_after_the_scale() -> None:
    lines = template("csv").decode().splitlines()

    assert lines[:2] == ["scale,millions", "fiscal_year_end,2024-09-28"]


def test_the_instructions_explain_the_fiscal_year_end_and_the_prefilled_years() -> None:
    text = " ".join(str(r[0]) for r in sheet_rows(template(), "Instructions") if r and r[0])

    assert "fiscal_year_end" in text and "20" in text and "period_start" in text


def test_a_grid_of_twenty_years_gives_a_hundred_period_columns_to_fill() -> None:
    columns = annual_then_quarterly(period_grid(FYE, 2025))
    content = build_template(ITEMS, columns, "xlsx", "millions", None, FYE)

    rows = sheet_rows(content, "BS")
    assert len(rows[0]) == 5 + 100
    assert rows[1][5:25] == ["FY"] * 20 and rows[1][25:29] == ["Q1", "Q2", "Q3", "Q4"]
    assert rows[0][5] == 2006 and rows[0][24] == 2025 and rows[0][25] == 2006
    assert rows[2][5:7] == ["FY06", "FY07"] and rows[2][25:27] == ["Q1 FY06", "Q2 FY06"]


@pytest.mark.parametrize("statement", ["IS", "BS", "CF"])
def test_every_canonical_item_appears_once_in_display_order(statement: str) -> None:
    rows = sheet_rows(template(scale="units"), statement)[FIRST_LINE:]

    expected = [i for i in ITEMS if i.statement == statement]
    assert [r[0] for r in rows] == [i.code for i in expected]
    first = rows[0]
    assert (first[1], first[2], first[3]) == (
        expected[0].label,
        expected[0].parent or None,
        expected[0].unit,
    )


def test_read_only_rows_are_grey_and_everything_else_is_not() -> None:
    book = load_workbook(io.BytesIO(template(scale="units")))
    sheet = book["IS"]
    grey = {
        sheet.cell(row=r, column=1).value
        for r in range(FIRST_LINE + 1, sheet.max_row + 1)
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

    rows = sheet_rows(template(values=values), "IS")

    by_code = {r[0]: r[5:7] for r in rows[FIRST_LINE:]}
    assert by_code["revenue"] == [391035, None]
    assert by_code["eps_diluted"] == [6.08, None]
    assert by_code["shares_diluted"] == [15408.095, None]
    assert by_code["other_operating_expenses"] == [None, None]


def test_the_csv_form_has_a_leading_statement_column_and_the_same_content() -> None:
    values = {("revenue", "FY2024"): Decimal(391_035_000_000)}
    xlsx = template(values=values)
    text = template("csv", values=values).decode()

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["scale", "millions"]
    income = [r for r in rows if r and r[0] == "IS"]
    assert income[0][1] == "fiscal_year"
    revenue = next(r for r in income if r[1] == "revenue")
    assert revenue[6] == "391035"
    assert [r[1] for r in income[HEADERS + 1 :]] == [
        r[0] for r in sheet_rows(xlsx, "IS")[FIRST_LINE:]
    ]
    assert {r[0] for r in rows[2:]} == {"IS", "BS", "CF"}


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_a_prefilled_template_parses_back_to_the_same_values(fmt: str) -> None:
    values = {
        ("revenue", "FY2024"): Decimal(391_035_000_000),
        ("capex", "FY2024"): Decimal(-9_447_000_000),  # displayed negative
        ("eps_diluted", "FY2024Q4"): Decimal("0.97"),
        ("cash", "FY2024"): Decimal(29_943_000_000),
    }

    content = template(fmt, values=values)
    plan = parse_import(content, f"t.{fmt}", ITEMS)

    by_key = {(v.code, v.period_key): v.value for v in plan.values}
    sign = {i.code: i.sign for i in ITEMS}
    assert by_key == {key: value * sign[key[0]] for key, value in values.items()}


def test_a_blank_template_has_no_values_to_import() -> None:
    content = template(scale="units")

    with pytest.raises(ImportParseError) as raised:
        parse_import(content, "t.xlsx", ITEMS)

    assert "no values" in raised.value.errors[0].message


def test_a_company_with_no_periods_still_gets_a_valid_layout() -> None:
    content = build_template(ITEMS, [], "xlsx", "units", None, FYE)

    rows = sheet_rows(content, "IS")
    assert rows[0][0] == "fiscal_year"
    assert len(rows) == FIRST_LINE + len([i for i in ITEMS if i.statement == "IS"])


def _example_blocks(content: bytes) -> dict[str, list[list[object]]]:
    """The 'Example IS/BS/CF' blocks of the Instructions sheet: the rows after the heading, up to
    the next blank row, laid out like the statement sheets."""
    rows = sheet_rows(content, "Instructions")
    blocks: dict[str, list[list[object]]] = {}
    for index, row in enumerate(rows):
        head = str(row[0]) if row and row[0] else ""
        if head.startswith("Example "):
            block = []
            for line in rows[index + 1 :]:
                if not any(c is not None for c in line):
                    break
                block.append(line)
            blocks[head.removeprefix("Example ")] = block
    return blocks


def _example_by_code(block: list[list[object]]) -> dict[str, list[object]]:
    return {str(r[0]): r[5:] for r in block[HEADERS + 1 :]}


def test_the_instructions_show_a_filled_example_of_each_statement() -> None:
    blocks = _example_blocks(template())

    assert list(blocks) == ["IS", "BS", "CF"]
    for block in blocks.values():
        assert [r[0] for r in block[:HEADERS]] == ["fiscal_year", "fiscal_period"]
        assert block[HEADERS][:5] == ["code", "label", "parent", "unit", "children_complete"]
    income = _example_by_code(blocks["IS"])
    assert income["revenue"] == [1000, 1200]
    assert income["eps_diluted"] == [1.68, 2.22]
    assert _example_by_code(blocks["CF"])["capex"] == [-60, -70]  # displayed negative


def test_the_example_uses_the_template_labels_and_leaves_read_only_rows_blank() -> None:
    blocks = _example_blocks(template())

    assert blocks
    labels = {i.code: (i.label, i.parent, i.unit) for i in ITEMS}
    read_only = {i.code for i in ITEMS if i.residual or (i.derive and not i.concepts)}
    for block in blocks.values():
        for row in block[HEADERS + 1 :]:
            code = str(row[0])
            if code in labels:
                assert tuple(row[1:4]) == (labels[code][0], labels[code][1], labels[code][2])
            if code in read_only:
                assert row[5:7] == [None, None]


def test_the_example_shows_a_custom_breakdown_at_the_bottom_of_the_income_sheet() -> None:
    income = _example_blocks(template())["IS"]

    by_code = {str(r[0]): r for r in income[HEADERS + 1 :]}
    assert by_code["cost_of_revenue"][4] is True  # children_complete on the parent's row
    custom = [
        r for r in income[HEADERS + 1 :] if r[0] in (None, "") or str(r[0]).startswith("custom:")
    ]
    assert [(r[1], r[2]) for r in custom] == [
        ("Products", "cost_of_revenue"),
        ("Services", "cost_of_revenue"),
    ]
    assert income[-2:] == custom
    assert [sum(r[5 + i] for r in custom) for i in (0, 1)] == by_code["cost_of_revenue"][5:7]  # type: ignore[misc]


def test_the_example_is_internally_consistent() -> None:
    blocks = _example_blocks(template())
    income, balance, cash = (_example_by_code(blocks[s]) for s in ("IS", "BS", "CF"))

    for i in (0, 1):  # FY before, FY
        assert income["revenue"][i] - income["cost_of_revenue"][i] == income["gross_profit"][i]  # type: ignore[operator]
        assert (
            income["gross_profit"][i] - income["rnd"][i] - income["sga"][i]  # type: ignore[operator]
            == income["operating_income"][i]
        )
        assert income["pretax_income"][i] - income["income_tax"][i] == income["net_income"][i]  # type: ignore[operator]
        assert balance["total_assets"][i] == (  # type: ignore[operator]
            balance["total_liabilities"][i] + balance["total_equity"][i]  # type: ignore[operator]
        )
        assert balance["total_liabilities_and_equity"][i] == balance["total_assets"][i]
        assert income["net_income"][i] == cash["cf_net_income"][i]
    # The last year's cash flow moves the balance sheet's cash.
    flows = ("cfo", "cfi", "cff", "fx_effect")
    assert sum(cash[c][1] for c in flows) == cash["net_change_in_cash"][1]  # type: ignore[misc]
    assert balance["cash"][1] - balance["cash"][0] == cash["net_change_in_cash"][1]  # type: ignore[operator]


def test_the_example_imports_cleanly_and_does_not_disturb_the_scale_row() -> None:
    content = template(scale="thousands")
    blocks = _example_blocks(content)
    rows = [["scale", "millions"], ["fiscal_year_end", "2024-12-31"]]  # as the text says
    for statement, block in blocks.items():
        rows += [
            [statement, *("" if c is None else ("TRUE" if c is True else c) for c in r)]
            for r in block
        ]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)

    plan = parse_import(out.getvalue().encode(), "example.csv", ITEMS)

    assert plan.scale == "millions"
    year = next(p for p in plan.periods if p.key == "FY2024")
    assert (year.start, year.end) == (date(2024, 1, 1), date(2024, 12, 31))
    by_key = {(v.code, v.period_key): v.value for v in plan.values}
    assert by_key[("revenue", "FY2024")] == Decimal(1_200_000_000)
    assert by_key[("capex", "FY2024")] == Decimal(70_000_000)  # typed -70, stored as reported
    assert [(line.label, line.parent) for line in plan.lines] == [
        ("Products", "cost_of_revenue"),
        ("Services", "cost_of_revenue"),
    ]
    # The real scale row is still the one the parser reads from the Instructions sheet.
    scale_rows = [r[:2] for r in sheet_rows(content, "Instructions") if r and r[0] == "scale"]
    assert scale_rows == [["scale", "thousands"]]
