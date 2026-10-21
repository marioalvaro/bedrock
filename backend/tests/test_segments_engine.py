"""segment_grid and parse_import (FR-DATA-11): pure engine tests with hand-built tables."""

import random
from datetime import date
from decimal import Decimal

import pytest

from bedrock.services.adjustments import AMOUNT_LIMIT
from bedrock.statements.build import Row, StatementTable
from bedrock.statements.periods import Period
from bedrock.statements.segments import (
    KPI_CODE,
    METRICS,
    NAME_MAX,
    VALUE_LIMIT,
    ImportIssue,
    SegmentGrid,
    SeriesData,
    ValueData,
    parse_import,
    segment_grid,
)

D = Decimal


def _fy(year: int) -> Period:
    return Period(
        f"FY{year}", f"FY{year % 100}", year, "FY", date(year - 1, 7, 1), date(year, 6, 30)
    )


def _q(year: int, q: int) -> Period:
    return Period(
        f"FY{year}Q{q}",
        f"Q{q} FY{year % 100}",
        year,
        f"Q{q}",
        date(year - 1, 7 + 3 * (q - 1), 1),
        date(year - 1, 9 + 3 * (q - 1), 28),
    )


def _row(code: str, values: list[Decimal | None]) -> Row:
    return Row(
        code=code,
        label=code,
        unit="USD",
        kind="flow",
        depth=0,
        values=values,
        provenance=["reported" if v is not None else None for v in values],
        yoy=[None] * len(values),
        common_size=[None] * len(values),
    )


def _table(periods: list[Period], **rows: list[Decimal | None]) -> StatementTable:
    return StatementTable(
        statement="IS",
        freq="quarterly" if periods and periods[0].fiscal_period != "FY" else "annual",
        periods=periods,
        rows=[_row(code, vals) for code, vals in rows.items()],
        balance_check=None,
        warnings=[],
    )


def _s(
    id: int,
    dimension: str = "business",
    name: str = "A",
    metric: str = "revenue",
    unit: str = "USD",
    order: int = 0,
) -> SeriesData:
    return SeriesData(id, dimension, name, metric, unit, order)


def _v(series_id: int, year: int, value: str, fp: str = "FY") -> ValueData:
    return ValueData(series_id, year, fp, D(value))


# --- segment_grid ----------------------------------------------------------------------------


def test_unallocated_is_the_canonical_line_minus_the_sum_of_the_series() -> None:
    table = _table([_fy(2023), _fy(2024)], revenue=[D("100"), D("120")])
    grid = segment_grid(
        [_s(1, name="A"), _s(2, name="B", order=1)],
        [_v(1, 2023, "60"), _v(2, 2023, "30"), _v(1, 2024, "70"), _v(2, 2024, "40")],
        table,
        "annual",
    )

    (block,) = grid.blocks
    assert block.unallocated == [D("10"), D("10")]
    assert [r.values for r in block.series] == [[D("60"), D("70")], [D("30"), D("40")]]


def test_negative_unallocated_is_kept() -> None:
    table = _table([_fy(2024)], revenue=[D("100")])
    grid = segment_grid([_s(1)], [_v(1, 2024, "130")], table, "annual")

    assert grid.blocks[0].unallocated == [D("-30")]


def test_unallocated_is_null_when_the_income_statement_has_no_value() -> None:
    table = _table([_fy(2023), _fy(2024)], revenue=[None, D("100")])
    grid = segment_grid([_s(1)], [_v(1, 2023, "5"), _v(1, 2024, "5")], table, "annual")

    assert grid.blocks[0].unallocated == [None, D("95")]


def test_unallocated_is_null_when_no_series_has_a_value_in_the_period() -> None:
    table = _table([_fy(2023), _fy(2024)], revenue=[D("90"), D("100")])
    grid = segment_grid([_s(1)], [_v(1, 2024, "5")], table, "annual")

    assert grid.blocks[0].unallocated == [None, D("95")]
    assert grid.blocks[0].series[0].values == [None, D("5")]


def test_a_block_whose_metric_row_is_missing_has_all_null_unallocated() -> None:
    table = _table([_fy(2024)], revenue=[D("100")])
    grid = segment_grid([_s(1, metric="operating_income")], [_v(1, 2024, "5")], table, "annual")

    assert grid.blocks[0].unallocated == [None]


def test_blocks_are_ordered_and_empty_blocks_are_left_out() -> None:
    table = _table([_fy(2024)], revenue=[D("100")], operating_income=[D("10")])
    series = [
        _s(1, "kpi", "Stores", "stores", "count"),
        _s(2, "geo", "US", "operating_income"),
        _s(3, "geo", "US", "revenue"),
        _s(4, "business", "X", "operating_income"),
        _s(5, "business", "X", "revenue"),
    ]
    grid = segment_grid(series, [], table, "annual")

    assert [(b.dimension, b.metric) for b in grid.blocks] == [
        ("business", "revenue"),
        ("business", "operating_income"),
        ("geo", "revenue"),
        ("geo", "operating_income"),
        ("kpi", None),
    ]


def test_the_kpi_block_has_no_metric_and_no_unallocated_and_one_block_for_all_kpis() -> None:
    table = _table([_fy(2024)], revenue=[D("100")])
    series = [
        _s(1, "kpi", "Stores", "stores", "count", 1),
        _s(2, "kpi", "Margin", "margin", "pct", 0),
    ]
    grid = segment_grid(series, [_v(1, 2024, "500")], table, "annual")

    (block,) = grid.blocks
    assert block.metric is None
    assert block.unallocated is None
    assert [r.name for r in block.series] == ["Margin", "Stores"]
    assert block.series[0].metric == "margin"
    assert block.series[0].unit == "pct"


def test_series_are_ordered_by_display_order_then_id() -> None:
    table = _table([_fy(2024)], revenue=[D("100")])
    series = [_s(3, order=1), _s(2, order=1), _s(9, order=0)]
    grid = segment_grid(series, [], table, "annual")

    assert [r.id for r in grid.blocks[0].series] == [9, 2, 3]


def test_no_series_gives_no_blocks_but_still_the_income_statement_periods() -> None:
    table = _table([_fy(2023), _fy(2024)], revenue=[D("1"), D("2")])
    grid = segment_grid([], [], table, "annual")

    assert grid.blocks == []
    assert [p.key for p in grid.periods] == ["FY2023", "FY2024"]


def test_a_value_older_than_every_income_statement_period_adds_a_dateless_column_first() -> None:
    table = _table([_fy(2023), _fy(2024)], revenue=[D("100"), D("120")])
    grid = segment_grid([_s(1)], [_v(1, 2019, "7")], table, "annual")

    first = grid.periods[0]
    assert (first.key, first.label, first.fiscal_year, first.fiscal_period) == (
        "FY2019",
        "FY19",
        2019,
        "FY",
    )
    assert first.start is None and first.end is None
    assert [p.key for p in grid.periods] == ["FY2019", "FY2023", "FY2024"]
    assert grid.periods[1].start == date(2022, 7, 1)
    assert grid.blocks[0].series[0].values == [D("7"), None, None]
    assert grid.blocks[0].unallocated == [None, None, None]


def test_a_value_between_income_statement_periods_lands_in_order() -> None:
    table = _table([_fy(2020), _fy(2024)], revenue=[D("1"), D("2")])
    grid = segment_grid([_s(1)], [_v(1, 2022, "7")], table, "annual")

    assert [p.key for p in grid.periods] == ["FY2020", "FY2022", "FY2024"]


def test_annual_ignores_quarterly_values() -> None:
    table = _table([_fy(2024)], revenue=[D("100")])
    values = [_v(1, 2024, "60"), _v(1, 2024, "999", "Q1"), _v(1, 2030, "5", "Q2")]
    grid = segment_grid([_s(1)], values, table, "annual")

    assert [p.key for p in grid.periods] == ["FY2024"]
    assert grid.blocks[0].series[0].values == [D("60")]


def test_quarterly_ignores_annual_values_and_orders_quarters_within_the_year() -> None:
    table = _table([_q(2024, 1), _q(2024, 2)], revenue=[D("10"), D("20")])
    values = [_v(1, 2024, "999"), _v(1, 2024, "4", "Q2"), _v(1, 2023, "3", "Q4")]
    grid = segment_grid([_s(1)], values, table, "quarterly")

    assert [p.key for p in grid.periods] == ["FY2023Q4", "FY2024Q1", "FY2024Q2"]
    assert [p.label for p in grid.periods] == ["Q4 FY23", "Q1 FY24", "Q2 FY24"]
    assert grid.blocks[0].series[0].values == [D("3"), None, D("4")]
    assert grid.blocks[0].unallocated == [None, None, D("16")]


def test_a_quarterly_only_period_has_no_dates() -> None:
    table = _table([_q(2024, 2)], revenue=[D("20")])
    grid = segment_grid([_s(1)], [_v(1, 2024, "4", "Q1")], table, "quarterly")

    assert grid.periods[0].start is None and grid.periods[0].end is None
    assert grid.periods[1].end == date(2024 - 1, 12, 28)


def test_values_of_unknown_series_are_ignored() -> None:
    table = _table([_fy(2024)], revenue=[D("100")])
    grid = segment_grid([_s(1)], [_v(99, 2018, "5")], table, "annual")

    assert [p.key for p in grid.periods] == ["FY2024"]


def test_each_block_reconciles_against_its_own_metric() -> None:
    table = _table([_fy(2024)], revenue=[D("100")], operating_income=[D("30")])
    series = [_s(1, metric="revenue"), _s(2, metric="operating_income"), _s(3, "geo")]
    values = [_v(1, 2024, "90"), _v(2, 2024, "35"), _v(3, 2024, "40")]
    grid: SegmentGrid = segment_grid(series, values, table, "annual")

    got = {(b.dimension, b.metric): b.unallocated for b in grid.blocks}
    assert got == {
        ("business", "revenue"): [D("10")],
        ("business", "operating_income"): [D("-5")],
        ("geo", "revenue"): [D("60")],
    }


def test_property_segments_plus_unallocated_equal_the_income_statement_value() -> None:
    rng = random.Random(7)
    years = [2021, 2022, 2023, 2024]
    for _ in range(300):
        n = rng.randint(1, 5)
        totals: list[Decimal | None] = [
            None if rng.random() < 0.2 else D(rng.randint(-(10**9), 10**9)) / D(100) for _ in years
        ]
        table = _table([_fy(y) for y in years], revenue=totals)
        series = [_s(i + 1, name=f"S{i}", order=i) for i in range(n)]
        values = [
            _v(i + 1, y, str(D(rng.randint(-(10**9), 10**9)) / D(100)))
            for i in range(n)
            for y in years
            if rng.random() < 0.7
        ]
        block = segment_grid(series, values, table, "annual").blocks[0]

        assert block.unallocated is not None
        for i, total in enumerate(totals):
            parts = [r.values[i] for r in block.series if r.values[i] is not None]
            got = block.unallocated[i]
            if total is None or not parts:
                assert got is None
            else:
                assert got is not None
                assert sum(parts, D(0)) + got == total


def test_value_limit_matches_the_adjustment_amount_limit() -> None:
    assert VALUE_LIMIT == AMOUNT_LIMIT


def test_public_rule_constants() -> None:
    assert NAME_MAX == 80
    assert METRICS == frozenset({"revenue", "operating_income"})
    assert KPI_CODE.match("a_1") and not KPI_CODE.match("A")


# --- parse_import ----------------------------------------------------------------------------

HEADER = "name,metric,unit,FY2023,FY2024"


def _ok(text: str, dimension: str = "business", scale: str = "units"):  # type: ignore[no-untyped-def]
    plan = parse_import(text, dimension, scale)  # type: ignore[arg-type]
    assert plan.errors == []
    return plan.series


def _errors(text: str, dimension: str = "business", scale: str = "units") -> list[ImportIssue]:
    plan = parse_import(text, dimension, scale)  # type: ignore[arg-type]
    assert plan.series == []
    assert plan.errors
    return plan.errors


def test_a_comma_separated_row_becomes_a_series_with_its_values_in_column_order() -> None:
    (s,) = _ok(f"{HEADER}\niPhone,revenue,USD,100,200")

    assert (s.row, s.name, s.metric, s.unit) == (2, "iPhone", "revenue", "USD")
    assert [(v.fiscal_year, v.fiscal_period, v.value) for v in s.values] == [
        (2023, "FY", D("100")),
        (2024, "FY", D("200")),
    ]


def test_a_tab_in_the_header_line_selects_tab_even_if_rows_hold_commas() -> None:
    text = "name\tmetric\tunit\tFY2024\nMac\trevenue\tUSD\t1,234"
    (s,) = _ok(text)

    assert s.values[0].value == D("1234")


def test_quoted_fields_may_contain_the_delimiter() -> None:
    (s,) = _ok(f'{HEADER}\n"Europe, Middle East",revenue,USD,"1,000",5')

    assert s.name == "Europe, Middle East"
    assert s.values[0].value == D("1000")


def test_quarter_period_headers_parse() -> None:
    (s,) = _ok("name,metric,unit,Q1 FY2024,Q4 FY2023\nA,revenue,USD,1,2")

    assert [(v.fiscal_year, v.fiscal_period) for v in s.values] == [(2024, "Q1"), (2023, "Q4")]


def test_blank_cells_are_skipped() -> None:
    (s,) = _ok(f"{HEADER}\nA,revenue,USD,,7")

    assert [(v.fiscal_year, v.value) for v in s.values] == [(2024, D("7"))]


def test_a_row_of_only_blank_value_cells_is_still_a_series_with_no_values() -> None:
    (s,) = _ok(f"{HEADER}\nA,revenue,USD,,")

    assert s.values == []


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("1,234,567.5", "1234567.5"),
        ("(1,234)", "-1234"),
        ("-12.5", "-12.5"),
        ("  42  ", "42"),
        (".5", "0.5"),
    ],
)
def test_number_forms(cell: str, expected: str) -> None:
    (s,) = _ok(f'name,metric,unit,FY2024\nA,revenue,USD,"{cell}"')

    assert s.values[0].value == D(expected)


@pytest.mark.parametrize(
    ("scale", "factor"), [("units", "1"), ("K", "1000"), ("M", "1000000"), ("B", "1000000000")]
)
def test_scale_multiplies_usd_values(scale: str, factor: str) -> None:
    (s,) = _ok("name,metric,unit,FY2024\nA,revenue,USD,2.5", scale=scale)

    assert s.values[0].value == D("2.5") * D(factor)


def test_scale_applies_to_usd_per_unit_but_not_to_pct_or_count() -> None:
    text = (
        "name,metric,unit,FY2024\n"
        "ARPU,arpu,USD_per_unit,2\n"
        "Margin,margin,pct,5\n"
        "Stores,stores,count,3"
    )
    arpu, margin, stores = _ok(text, dimension="kpi", scale="M")

    assert arpu.values[0].value == D("2000000")
    assert margin.values[0].value == D("0.05")
    assert stores.values[0].value == D("3")


def test_pct_with_and_without_a_percent_sign_is_stored_as_a_fraction() -> None:
    a, b = _ok("name,metric,unit,FY2024\nA,m,pct,5.2\nB,n,pct,5.2%", dimension="kpi")

    assert a.values[0].value == D("0.052")
    assert b.values[0].value == D("0.052")


def test_count_is_stored_as_typed() -> None:
    (s,) = _ok("name,metric,unit,FY2024\nStores,stores,count,1234", dimension="kpi", scale="B")

    assert s.values[0].value == D("1234")


def test_blank_trailing_lines_and_whitespace_only_lines_are_ignored() -> None:
    series = _ok(f"{HEADER}\nA,revenue,USD,1,2\n\n   \n\n")

    assert len(series) == 1


def test_row_numbers_count_physical_lines_with_the_header_as_row_one() -> None:
    series = _ok(f"{HEADER}\nA,revenue,USD,1,2\n\nB,revenue,USD,1,2")

    assert [s.row for s in series] == [2, 4]


def test_empty_text_is_one_whole_text_error() -> None:
    for text in ("", "  \n "):
        (e,) = _errors(text)
        assert (e.row, e.column) == (1, None)


def test_a_wrong_header_column_is_reported_at_its_position() -> None:
    (e,) = _errors("name,kind,unit,FY2024\nA,revenue,USD,1")

    assert (e.row, e.column) == (1, 2)


def test_a_missing_header_column_is_a_whole_row_error() -> None:
    errors = _errors("name,metric")

    assert [(e.row, e.column) for e in errors] == [(1, None)]


def test_a_bad_period_label_is_reported_at_its_column() -> None:
    (e,) = _errors("name,metric,unit,FY2024,2023\nA,revenue,USD,1,2")

    assert (e.row, e.column) == (1, 5)


@pytest.mark.parametrize("label", ["FY24", "Q5 FY2024", "FY2024Q1", "fy2024 ", "Q1FY2024"])
def test_malformed_period_labels_are_rejected(label: str) -> None:
    errs = _errors(f"name,metric,unit,{label.strip()}\nA,revenue,USD,1")

    assert (errs[0].row, errs[0].column) == (1, 4)


def test_a_duplicate_period_column_is_reported_at_the_second_one() -> None:
    (e,) = _errors("name,metric,unit,FY2024,Q1 FY2024,FY2024\nA,revenue,USD,1,2,3")

    assert (e.row, e.column) == (1, 6)


def test_a_header_with_no_period_column_is_an_error() -> None:
    (e,) = _errors("name,metric,unit\nA,revenue,USD")

    assert (e.row, e.column) == (1, None)


@pytest.mark.parametrize("cell", ["abc", "1.2.3", "NaN", "Infinity", "1e5", "12%", "--5", "(-5)"])
def test_a_bad_number_is_reported_at_its_cell(cell: str) -> None:
    (e,) = _errors(f"name,metric,unit,FY2024\nA,revenue,USD,{cell}")

    assert (e.row, e.column) == (2, 4)
    assert repr(cell) in e.message


def test_a_value_at_or_over_the_limit_is_rejected_after_scaling() -> None:
    (e,) = _errors("name,metric,unit,FY2024\nA,revenue,USD,1000000", scale="B")
    assert (e.row, e.column) == (2, 4)

    (e2,) = _errors(f"name,metric,unit,FY2024\nA,revenue,USD,{VALUE_LIMIT}")
    assert (e2.row, e2.column) == (2, 4)

    (s,) = _ok(f"name,metric,unit,FY2024\nA,revenue,USD,{VALUE_LIMIT - 1}")
    assert s.values[0].value == VALUE_LIMIT - 1


def test_a_negative_value_at_the_limit_is_rejected() -> None:
    (e,) = _errors(f"name,metric,unit,FY2024\nA,revenue,USD,-{VALUE_LIMIT}")

    assert (e.row, e.column) == (2, 4)


def test_more_than_ten_decimals_after_scaling_is_rejected_but_ten_pass() -> None:
    (e,) = _errors("name,metric,unit,FY2024\nA,revenue,USD,0.00000000001")
    assert (e.row, e.column) == (2, 4)

    (s,) = _ok("name,metric,unit,FY2024\nA,revenue,USD,0.0000000001")
    assert s.values[0].value == D("0.0000000001")

    # a pct is divided by 100, which can add two places
    (e2,) = _errors("name,metric,unit,FY2024\nA,m,pct,0.000000001", dimension="kpi")
    assert (e2.row, e2.column) == (2, 4)


def test_trailing_zero_decimals_do_not_count() -> None:
    (s,) = _ok("name,metric,unit,FY2024\nA,revenue,USD,1.50000000000000")

    assert s.values[0].value == D("1.5")


def test_a_metric_not_allowed_for_business_or_geo_is_reported_at_column_two() -> None:
    (e,) = _errors("name,metric,unit,FY2024\nA,ebitda,USD,1")
    assert (e.row, e.column) == (2, 2)

    (e2,) = _errors("name,metric,unit,FY2024\nA,Revenue,USD,1", dimension="geo")
    assert (e2.row, e2.column) == (2, 2)


@pytest.mark.parametrize("code", ["Stores", "1stores", "a-b", "a" * 41, ""])
def test_a_kpi_code_must_be_a_slug(code: str) -> None:
    (e,) = _errors(f"name,metric,unit,FY2024\nA,{code},count,1", dimension="kpi")

    assert (e.row, e.column) == (2, 2)


def test_a_kpi_code_of_forty_characters_is_accepted() -> None:
    _ok(f"name,metric,unit,FY2024\nA,{'a' * 40},count,1", dimension="kpi")


def test_units_other_than_usd_are_rejected_for_business_and_geo() -> None:
    (e,) = _errors("name,metric,unit,FY2024\nA,revenue,pct,1", dimension="geo")
    assert (e.row, e.column) == (2, 3)


def test_an_unknown_kpi_unit_is_rejected() -> None:
    (e,) = _errors("name,metric,unit,FY2024\nA,m,EUR,1", dimension="kpi")
    assert (e.row, e.column) == (2, 3)


def test_a_blank_name_is_reported_at_column_one() -> None:
    (e,) = _errors("name,metric,unit,FY2024\n  ,revenue,USD,1")

    assert (e.row, e.column) == (2, 1)


def test_a_name_over_eighty_characters_is_rejected_but_eighty_pass() -> None:
    (e,) = _errors(f"name,metric,unit,FY2024\n{'x' * 81},revenue,USD,1")
    assert (e.row, e.column) == (2, 1)

    (s,) = _ok(f"name,metric,unit,FY2024\n {'x' * 80} ,revenue,USD,1")
    assert s.name == "x" * 80


def test_a_duplicate_name_and_metric_row_is_a_whole_row_error_on_the_later_row() -> None:
    (e,) = _errors(f"{HEADER}\nA,revenue,USD,1,2\nB,revenue,USD,1,2\nA,revenue,USD,3,4")

    assert (e.row, e.column) == (4, None)


def test_the_same_name_with_another_metric_is_not_a_duplicate() -> None:
    series = _ok(f"{HEADER}\nA,revenue,USD,1,2\nA,operating_income,USD,1,2")

    assert len(series) == 2


def test_several_errors_are_reported_together_and_the_plan_has_no_series() -> None:
    text = (
        "name,metric,unit,FY2024,FY2024\n"
        "A,revenue,USD,1,2\n"  # fine row
        "B,bogus,USD,x,2\n"  # bad metric and bad number
        ",revenue,USD,1,2\n"  # blank name
    )
    plan = parse_import(text, "business", "units")

    assert plan.series == []
    assert {(e.row, e.column) for e in plan.errors} == {(1, 5), (3, 2), (3, 4), (4, 1)}


def test_a_cell_beyond_the_header_columns_is_an_error_but_a_short_row_is_fine() -> None:
    (e,) = _errors(f"{HEADER}\nA,revenue,USD,1,2,3")
    assert (e.row, e.column) == (2, 6)

    (s,) = _ok(f"{HEADER}\nA,revenue,USD,1")
    assert len(s.values) == 1


def test_an_unknown_dimension_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        parse_import(f"{HEADER}\nA,revenue,USD,1,2", "sector", "units")  # type: ignore[arg-type]


def test_a_kpi_unit_error_names_all_four_units() -> None:
    (e,) = _errors("name,metric,unit,FY2024\nA,m,EUR,1", dimension="kpi")

    for unit in ("USD", "pct", "count", "USD_per_unit"):
        assert unit in e.message


def test_a_pct_in_parentheses_with_a_percent_sign_is_negative() -> None:
    a, b, c = _ok(
        'name,metric,unit,FY2024\nA,a,pct,"(5.2%)"\nB,b,pct,-5.2%\nC,c,pct,(5.2)', dimension="kpi"
    )

    assert [x.values[0].value for x in (a, b, c)] == [D("-0.052")] * 3


def test_a_percent_sign_is_only_valid_on_pct() -> None:
    (e,) = _errors("name,metric,unit,FY2024\nA,revenue,USD,(5%)")

    assert (e.row, e.column) == (2, 4)


def test_a_leading_bom_is_ignored() -> None:
    (s,) = _ok("\ufeff" + f"{HEADER}\nA,revenue,USD,1,2")

    assert s.name == "A" and len(s.values) == 2


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_crlf_gives_the_same_plan_as_lf(newline: str) -> None:
    for delim in (",", "\t"):
        lf = "name,metric,unit,FY2024\nA,revenue,USD,1\n\nB,revenue,USD,2".replace(",", delim)
        text = lf.replace("\n", newline)
        assert parse_import(text, "business", "units") == parse_import(lf, "business", "units")


def test_a_quoted_newline_shifts_the_physical_row_of_the_next_error() -> None:
    (e,) = _errors('name,metric,unit,FY2024\n"A\nB",revenue,USD,1\nC,bogus,USD,1')

    assert (e.row, e.column) == (4, 2)


def test_a_blank_trailing_header_column_is_ignored() -> None:
    a, b = _ok("name,metric,unit,FY2024,\nA,revenue,USD,1,\nB,revenue,USD,2")

    assert [len(x.values) for x in (a, b)] == [1, 1]


def test_a_value_under_a_blank_trailing_header_is_reported_at_its_column() -> None:
    (e,) = _errors("name,metric,unit,FY2024,\nA,revenue,USD,1,9")

    assert (e.row, e.column) == (2, 5)
    assert "blank header" in e.message


def test_a_blank_header_cell_in_the_middle_is_a_bad_period_label() -> None:
    (e,) = _errors("name,metric,unit,,FY2024\nA,revenue,USD,1,2")

    assert (e.row, e.column) == (1, 4)


def test_rows_lists_every_valid_identity_in_file_order_on_success() -> None:
    plan = parse_import(f"{HEADER}\nA,revenue,USD,1,2\n\nB,operating_income,USD,3", "business", "M")

    assert [(r.row, r.name, r.metric, r.unit) for r in plan.rows] == [
        (2, "A", "revenue", "USD"),
        (4, "B", "operating_income", "USD"),
    ]


def test_rows_keeps_a_row_whose_only_problem_is_a_bad_cell() -> None:
    plan = parse_import(f"{HEADER}\nA,revenue,USD,x,2\nB,revenue,USD,1,2", "business", "units")

    assert plan.series == [] and plan.errors
    assert [r.name for r in plan.rows] == ["A", "B"]


def test_rows_drops_rows_with_a_bad_identity() -> None:
    text = (
        f"{HEADER}\n"
        "A,revenue,USD,1,2\n"
        ",revenue,USD,1,2\n"  # blank name
        "C,bogus,USD,1,2\n"  # bad metric
        "D,revenue,pct,1,2\n"  # bad unit
        "A,revenue,USD,3,4\n"  # duplicate
        "E,revenue,USD,1,2"
    )
    plan = parse_import(text, "business", "units")

    assert [(r.row, r.name) for r in plan.rows] == [(2, "A"), (7, "E")]


def test_empty_text_has_no_rows() -> None:
    assert parse_import("", "business", "units").rows == []
