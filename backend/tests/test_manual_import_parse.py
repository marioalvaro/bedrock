"""The manual import parser: xlsx and CSV into one plan, every error located (erd/data.md,
"Parsing and validation")."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from bedrock.ingest.manual_import import ImportParseError, ImportPlan, parse_import
from bedrock.mapping.config import load_canonical_items

from .import_data import (
    FY2006,
    Q1_2006,
    Q2_2006,
    Q3_2006,
    Q4_2006,
    csv_file,
    statement_rows,
    workbook,
)

ITEMS = load_canonical_items()


def parse(content: bytes, filename: str = "aapl.xlsx", scale: str | None = None) -> ImportPlan:
    return parse_import(content, filename, ITEMS, scale=scale)


def errors(content: bytes, filename: str = "aapl.xlsx", scale: str | None = None) -> list[Any]:
    with pytest.raises(ImportParseError) as raised:
        parse(content, filename, scale)
    return raised.value.errors


def located(issue: Any) -> tuple[str | None, int | None, str | None]:
    return (issue.sheet, issue.row, issue.column)


FORMATS = pytest.mark.parametrize("fmt", ["xlsx", "csv"])


def build(
    fmt: str, statements: dict[str, list[list[Any]]], scale: str | None = "millions"
) -> tuple[bytes, str]:
    return (
        (workbook(statements, scale), "aapl.xlsx")
        if fmt == "xlsx"
        else (csv_file(statements, scale), "aapl.csv")
    )


def income(
    lines: dict[str, list[Any]], periods: tuple[Any, ...] = (FY2006,)
) -> dict[str, list[list[Any]]]:
    return {"IS": statement_rows(periods, lines)}


@FORMATS
def test_a_value_is_scaled_to_units(fmt: str) -> None:
    plan = parse(*build(fmt, income({"revenue": [19315]})))

    (value,) = plan.values
    assert (value.statement, value.code, value.fiscal_year, value.fiscal_period) == (
        "IS",
        "revenue",
        2006,
        "FY",
    )
    assert value.value == Decimal(19_315_000_000)
    assert plan.scale == "millions"
    assert plan.format == fmt
    (period,) = plan.periods
    assert (period.fiscal_year, period.fiscal_period, period.start, period.end) == FY2006


def test_values_are_plain_decimals_never_in_exponent_notation() -> None:
    plan = parse(workbook(income({"revenue": [1], "eps_basic": ["0.5"]})))

    assert {v.code: str(v.value) for v in plan.values} == {"revenue": "1000000", "eps_basic": "0.5"}


@pytest.mark.parametrize(
    ("scale", "factor"),
    [("units", 1), ("thousands", 1_000), ("millions", 1_000_000), ("billions", 1_000_000_000)],
)
def test_scale_applies_to_usd_and_shares_and_never_to_per_share(scale: str, factor: int) -> None:
    lines = {"revenue": [2], "shares_basic": [3], "eps_basic": ["1.55"]}
    plan = parse(workbook(income(lines), scale))

    by_code = {v.code: v.value for v in plan.values}
    assert by_code == {
        "revenue": Decimal(2 * factor),
        "shares_basic": Decimal(3 * factor),
        "eps_basic": Decimal("1.55"),
    }


def test_the_displayed_sign_becomes_the_reported_sign() -> None:
    statements = {
        "IS": statement_rows([FY2006], {"revenue": [100]}),
        "CF": statement_rows([FY2006], {"capex": [-10959], "dividends_paid": [-5], "cfo": [7]}),
    }

    plan = parse(workbook(statements, "units"))

    by_code = {v.code: v.value for v in plan.values}
    assert by_code == {
        "revenue": Decimal(100),
        "capex": Decimal(10959),
        "dividends_paid": Decimal(5),
        "cfo": Decimal(7),
    }


@FORMATS
def test_a_balance_sheet_is_an_instant_with_no_start(fmt: str) -> None:
    periods = [(2006, "FY", date(2005, 9, 25), date(2006, 9, 30))]
    statements = {"BS": statement_rows(periods, {"cash": [10110]})}

    plan = parse(*build(fmt, statements))

    assert plan.periods[0].start is None
    assert plan.periods[0].end == date(2006, 9, 30)


def test_a_balance_sheet_column_may_leave_the_start_blank() -> None:
    periods = [(2006, "FY", None, date(2006, 9, 30))]

    plan = parse(workbook({"BS": statement_rows(periods, {"cash": [1]})}))

    assert [v.code for v in plan.values] == ["cash"]


def test_blank_cells_are_skipped_and_zero_is_a_value() -> None:
    periods = [FY2006, Q1_2006]

    plan = parse(
        workbook(income({"revenue": [None, 0], "cost_of_revenue": [5, None]}, tuple(periods)))
    )

    assert {(v.code, v.fiscal_period, v.value) for v in plan.values} == {
        ("revenue", "Q1", Decimal(0)),
        ("cost_of_revenue", "FY", Decimal(5_000_000)),
    }


def test_text_numbers_with_separators_and_parentheses_are_accepted() -> None:
    plan = parse(workbook(income({"revenue": ["1,234.5"], "cost_of_revenue": ["(7)"]})))

    by_code = {v.code: v.value for v in plan.values}
    assert by_code == {"revenue": Decimal("1234500000"), "cost_of_revenue": Decimal(-7_000_000)}


def test_header_dates_may_be_dates_datetimes_or_iso_text() -> None:
    periods = [
        (2006, "FY", date(2005, 9, 25), datetime(2006, 9, 30)),
        (2006, "Q1", "2005-09-25", "2005-12-31"),
    ]

    plan = parse(workbook(income({"revenue": [1, 2]}, tuple(periods))))

    assert [(p.fiscal_period, p.start, p.end) for p in plan.periods] == [
        ("FY", date(2005, 9, 25), date(2006, 9, 30)),
        ("Q1", date(2005, 9, 25), date(2005, 12, 31)),
    ]


def test_read_only_rows_are_ignored_with_one_warning_each() -> None:
    lines = {
        "revenue": [1],
        "other_operating_expenses": [5],  # a residual
        "total_operating_costs": [6],  # computed only
    }
    plan = parse(workbook(income(lines)))

    assert [v.code for v in plan.values] == ["revenue"]
    assert {located(w) for w in plan.warnings} == {("IS", 7, "A"), ("IS", 8, "A")}
    assert all("read-only" in w.message for w in plan.warnings)


def test_the_scale_argument_stands_in_for_a_missing_scale() -> None:
    content = workbook(income({"revenue": [1]}), scale=None)

    assert parse(content, scale="thousands").values[0].value == Decimal(1000)
    (issue,) = errors(content)
    assert "scale" in issue.message


def test_an_unknown_scale_is_an_error() -> None:
    (issue,) = errors(workbook(income({"revenue": [1]}), scale="millionz"))

    assert "scale" in issue.message and "millionz" in issue.message


def test_a_balance_sheet_year_end_value_that_disagrees_with_q4_is_a_warning() -> None:
    periods = (FY2006, Q4_2006)
    statements = {"BS": statement_rows(periods, {"cash": [10, 11]})}

    plan = parse(workbook(statements))

    assert len(plan.warnings) == 1
    assert "FY2006" in plan.warnings[0].message and "Q4" in plan.warnings[0].message


def test_a_file_without_values_is_an_error() -> None:
    (issue,) = errors(workbook(income({"revenue": [None]})))

    assert "no values" in issue.message


def test_bytes_that_are_not_an_xlsx_are_an_error() -> None:
    (issue,) = errors(b"this is not a zip file", "aapl.xlsx")

    assert "xlsx" in issue.message


def test_an_unsupported_extension_is_an_error() -> None:
    (issue,) = errors(b"a,b", "aapl.pdf")

    assert ".xlsx" in issue.message and ".csv" in issue.message


def test_an_unknown_sheet_is_an_error() -> None:
    statements = {**income({"revenue": [1]}), "Notes": [["hello"]]}

    (issue,) = errors(workbook(statements))

    assert located(issue) == ("Notes", None, None)


def test_a_csv_row_for_an_unknown_statement_is_an_error() -> None:
    content = csv_file({"XX": statement_rows([FY2006], {"revenue": [1]})})

    assert {issue.sheet for issue in errors(content, "aapl.csv")} == {"XX"}


def test_a_missing_header_row_is_an_error() -> None:
    rows = statement_rows([FY2006], {"revenue": [1]})
    del rows[0]  # no fiscal_year row

    issues = errors(workbook({"IS": rows}))

    assert any(issue.sheet == "IS" and "fiscal_year" in issue.message for issue in issues)


@pytest.mark.parametrize(
    ("period", "row", "needle"),
    [
        (("x", "FY", date(2005, 9, 25), date(2006, 9, 30)), 1, "fiscal_year"),
        ((2006, "H1", date(2005, 9, 25), date(2006, 9, 30)), 2, "fiscal_period"),
        ((2006, "FY", "not a date", date(2006, 9, 30)), 3, "period_start"),
        ((2006, "FY", date(2005, 9, 25), None), 4, "period_end"),
        ((2006, "FY", date(2006, 9, 30), date(2005, 9, 25)), 4, "before"),
    ],
)
def test_a_malformed_header_is_located_on_its_row_and_column(
    period: Any, row: int, needle: str
) -> None:
    issues = errors(workbook(income({"revenue": [1]}, (period,))))

    assert (issues[0].sheet, issues[0].row, issues[0].column) == ("IS", row, "F")
    assert needle in issues[0].message


def test_a_fiscal_year_must_last_350_to_380_days() -> None:
    short = (2006, "FY", date(2006, 1, 1), date(2006, 9, 30))

    issues = errors(workbook(income({"revenue": [1]}, (short,))))

    assert located(issues[0]) == ("IS", 4, "F")
    assert "350" in issues[0].message


def test_quarters_must_be_contiguous_inside_their_year() -> None:
    gap = (2006, "Q2", date(2006, 1, 15), date(2006, 4, 1))

    issues = errors(workbook(income({"revenue": [1, 2]}, (Q1_2006, gap))))

    assert located(issues[0]) == ("IS", 3, "G")
    assert "Q1" in issues[0].message


def test_the_year_and_its_quarters_must_share_their_edges() -> None:
    late_q4 = (2006, "Q4", date(2006, 7, 2), date(2006, 10, 7))
    periods = (FY2006, Q1_2006, Q2_2006, Q3_2006, late_q4)
    lines = {"revenue": [1, 2, 3, 4, 5]}

    issues = errors(workbook(income(lines, periods)))

    assert any("year" in i.message and i.column == "J" for i in issues)


def test_a_non_numeric_value_is_located() -> None:
    issues = errors(workbook(income({"revenue": ["abc"]})))

    assert located(issues[0]) == ("IS", 6, "F")
    assert "abc" in issues[0].message


@pytest.mark.parametrize("bad", ["inf", "nan", 10**15, True])
def test_non_finite_huge_and_boolean_values_are_errors(bad: Any) -> None:
    issues = errors(workbook(income({"revenue": [bad]}), scale="units"))

    assert located(issues[0]) == ("IS", 6, "F")


def test_a_duplicate_row_is_an_error() -> None:
    rows = statement_rows(
        [FY2006], [["revenue", None, None, None, None, 1], ["revenue", None, None, None, None, 2]]
    )

    issues = errors(workbook({"IS": rows}))

    assert located(issues[0]) == ("IS", 7, "A")
    assert "revenue" in issues[0].message and "row 6" in issues[0].message


def test_a_duplicate_period_column_is_an_error() -> None:
    issues = errors(workbook(income({"revenue": [1, 2]}, (FY2006, FY2006))))

    assert located(issues[0]) == ("IS", 1, "G")
    assert "FY2006" in issues[0].message


def test_an_unknown_code_is_an_error() -> None:
    issues = errors(workbook(income({"revnue": [1]})))

    assert located(issues[0]) == ("IS", 6, "A")
    assert "revnue" in issues[0].message


def test_a_code_on_the_wrong_statement_is_an_error() -> None:
    issues = errors(workbook(income({"cfo": [1]})))

    assert located(issues[0]) == ("IS", 6, "A")
    assert "CF" in issues[0].message


@pytest.mark.parametrize("code", [None, "custom:products", "products"])
def test_a_custom_line_is_refused_until_s10c(code: str | None) -> None:
    rows = statement_rows(
        [FY2006],
        [
            [code, "Products", "cost_of_revenue", "USD", None, 5],
            ["revenue", None, None, None, None, 1],
        ],
    )

    issues = errors(workbook({"IS": rows}))

    assert located(issues[0]) == ("IS", 6, "A")
    assert "custom lines" in issues[0].message.lower()


def test_a_value_under_a_blank_period_header_is_an_error() -> None:
    rows = statement_rows([FY2006], {"revenue": [1, 2]})
    for header_row in rows[:5]:
        header_row.append(None)  # the title row too

    issues = errors(workbook({"IS": rows}))

    assert located(issues[0]) == ("IS", 6, "G")


def test_the_same_period_must_carry_the_same_dates_on_every_statement() -> None:
    other = (2006, "FY", date(2005, 9, 25), date(2006, 9, 29))
    statements = {
        "IS": statement_rows([FY2006], {"revenue": [1]}),
        "CF": statement_rows([other], {"cfo": [1]}),
    }

    issues = errors(workbook(statements))

    assert any(i.sheet == "CF" and i.column == "F" and "IS" in i.message for i in issues)


def test_every_error_is_reported_in_one_round_in_sheet_order() -> None:
    statements = {
        "BS": statement_rows([FY2006], {"nope": [1]}),
        "IS": statement_rows([FY2006], {"revenue": ["abc"], "nope2": [1]}),
    }

    issues = errors(workbook(statements))

    assert [located(i) for i in issues] == [("IS", 6, "F"), ("IS", 7, "A"), ("BS", 6, "A")]


def test_csv_errors_carry_the_statement_and_the_line_number() -> None:
    # line 1 is the scale; the statement block starts on line 2
    content = csv_file(income({"revenue": ["abc"]}))

    issues = errors(content, "aapl.csv")

    assert located(issues[0]) == ("IS", 7, "G")


@pytest.mark.parametrize("delimiter", [";", "\t"])
def test_csv_may_use_semicolons_or_tabs(delimiter: str) -> None:
    plan = parse(csv_file(income({"revenue": [19315]}), delimiter=delimiter), "aapl.csv")

    assert plan.values[0].value == Decimal(19_315_000_000)
