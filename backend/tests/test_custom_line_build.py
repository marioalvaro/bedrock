"""Custom lines in the statement tables: rows under their parent, the Other row, the views that
must not change (FR-DATA-16; erd/data.md, "Custom lines")."""

from decimal import Decimal

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.coverage import table_coverage
from bedrock.statements.custom_lines import complete_parents, merge_lines
from bedrock.statements.imports import imported_frames
from bedrock.statements.rules import Rules
from tests.engine_data import facts, flow_facts
from tests.test_custom_line_cells import (
    DEPOSITS,
    PHONES,
    PRODUCTS,
    SERVICES,
    value,
)
from tests.test_import_pipeline import ITEMS, MAPS, B, sec_rows
from tests.test_statements_normalize import adj

CUSTOM = [PRODUCTS, SERVICES, PHONES, DEPOSITS]
LINES = merge_lines(ITEMS, CUSTOM)


def table(
    values,  # type: ignore[no-untyped-def]
    complete: frozenset[str] = frozenset(),
    freq="annual",  # type: ignore[no-untyped-def]
    statement: str = "IS",
    rows=None,  # type: ignore[no-untyped-def]
    adjustments=(),  # type: ignore[no-untyped-def]
) -> StatementTable:
    canonical = map_facts(select_vintage(facts(rows or sec_rows())), MAPS, ITEMS)
    frames = imported_frames(values, LINES)
    rules = Rules(
        imported=frames.newest, imported_vintages=frames.vintages, complete_parents=complete
    )
    return build_statement(canonical, LINES, statement, freq, adjustments=adjustments, rules=rules)


def row(t: StatementTable, code: str):  # type: ignore[no-untyped-def]
    return next(r for r in t.rows if r.code == code)


def at(t: StatementTable, code: str, key: str) -> Decimal | None:
    r = row(t, code)
    return r.values[[p.key for p in t.periods].index(key)]


def test_merge_puts_each_custom_line_after_its_parent_and_nested_ones_after_theirs() -> None:
    codes = [i.code for i in LINES]

    assert codes == [
        "revenue",
        "cost_of_revenue",
        "custom:products",
        "custom:phones",
        "custom:services",
        "gross_profit",
        "cash",
        "custom:deposits",
    ]


def test_merge_leaves_out_a_line_whose_parent_is_missing() -> None:
    orphan = CanonicalItemDef(
        "custom:x", "IS", "X", "flow", "USD", 1, "nothing", (), None, False, (), custom=True
    )

    assert [i.code for i in merge_lines(ITEMS, [orphan])] == [i.code for i in ITEMS]


def test_custom_rows_sit_indented_under_their_parent_and_say_so() -> None:
    t = table([value("custom:products", 2024, "FY", 3), value("custom:phones", 2024, "FY", 1)])

    products, phones = row(t, "custom:products"), row(t, "custom:phones")
    assert (products.custom, products.parent, products.depth) == (True, "cost_of_revenue", 1)
    assert (phones.custom, phones.parent, phones.depth) == (True, "custom:products", 2)
    assert (row(t, "revenue").custom, row(t, "revenue").parent) == (False, None)
    assert at(t, "custom:products", "FY2024") == Decimal(3 * B)
    assert row(t, "custom:products").provenance[-1] == "imported"


def test_the_other_row_is_the_parent_less_its_children_after_the_last_child() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (3 * B,) * 4})
    t = table(
        [value("custom:products", 2024, "FY", 3), value("custom:services", 2024, "FY", 4)],
        rows=rows,
    )

    codes = [r.code for r in t.rows]
    other = row(t, "other:cost_of_revenue")
    assert codes[codes.index("custom:services") + 1] == "other:cost_of_revenue"
    assert other.label == "Other Cost of revenue"
    assert (other.custom, other.parent, other.depth) == (True, "cost_of_revenue", 1)
    assert at(t, "other:cost_of_revenue", "FY2024") == Decimal(12 * B - 7 * B)  # 12 - (3 + 4)
    assert row(t, "other:cost_of_revenue").provenance[-1] == "derived"


def test_a_nested_breakdown_has_an_other_row_inside_its_parents_block() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (3 * B,) * 4})
    t = table(
        [
            value("custom:products", 2024, "FY", 5),
            value("custom:phones", 2024, "FY", 2),
            value("custom:services", 2024, "FY", 4),
        ],
        rows=rows,
    )

    codes = [r.code for r in t.rows]
    assert codes.index("custom:phones") < codes.index("other:custom:products")
    assert codes.index("other:custom:products") < codes.index("custom:services")
    assert at(t, "other:custom:products", "FY2024") == Decimal(3 * B)  # 5 - 2
    assert row(t, "other:custom:products").depth == 2


def test_the_other_row_uses_the_children_that_have_values() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (3 * B,) * 4})
    t = table([value("custom:products", 2024, "FY", 3)], rows=rows)

    assert at(t, "other:cost_of_revenue", "FY2024") == Decimal(9 * B)


def test_the_other_row_is_empty_where_the_parent_or_every_child_is() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (3 * B,) * 4})
    t = table([value("custom:products", 2023, "FY", 3)], rows=rows)  # 2024 has no child

    assert at(t, "other:cost_of_revenue", "FY2024") is None  # no child has a value
    assert at(t, "other:cost_of_revenue", "FY2023") is None  # the parent has no value


def test_a_parent_built_from_a_complete_breakdown_has_an_empty_other() -> None:
    t = table(
        [value("custom:products", 2024, "FY", 3), value("custom:services", 2024, "FY", 4)],
        frozenset({"cost_of_revenue"}),
    )

    assert at(t, "cost_of_revenue", "FY2024") == Decimal(7 * B)
    assert at(t, "other:cost_of_revenue", "FY2024") == Decimal(0)


def test_a_line_with_no_custom_children_gets_no_other_row() -> None:
    t = table([value("custom:products", 2024, "FY", 3)])

    assert "other:revenue" not in [r.code for r in t.rows]


def test_the_other_row_exists_for_a_declared_line_even_with_no_values() -> None:
    t = table([], statement="BS")

    assert "other:cash" in [r.code for r in t.rows]
    assert all(v is None for v in row(t, "other:cash").values)


def test_ttm_custom_rows_and_other_add_the_last_four_quarters() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (3 * B,) * 4, 2023: (3 * B,) * 4})
    values = [
        value("custom:products", fy, p, 1) for fy in (2023, 2024) for p in ("Q1", "Q2", "Q3", "FY")
    ]
    values = [v for v in values if v.fiscal_period != "FY"] + [
        value("custom:products", fy, "FY", 4) for fy in (2023, 2024)
    ]

    t = table(values, freq="ttm", rows=rows)

    last = t.periods[-1].key
    assert at(t, "custom:products", last) == Decimal(4 * B)
    assert at(t, "other:cost_of_revenue", last) == Decimal(12 * B - 4 * B)


def test_yoy_and_common_size_work_on_custom_rows() -> None:
    t = table([value("custom:products", 2023, "FY", 2), value("custom:products", 2024, "FY", 3)])

    r = row(t, "custom:products")
    assert r.yoy[-1] == Decimal("0.500000")
    assert r.common_size[-1] == Decimal("0.075000")  # 3 of revenue 40


def test_custom_and_other_rows_cannot_be_adjusted() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (3 * B,) * 4})
    t = table(
        [value("custom:products", 2024, "FY", 1), value("custom:services", 2024, "FY", 1)],
        rows=rows,
    )

    flags = {r.code: r.adjustable for r in t.rows}
    assert flags["cost_of_revenue"] is True
    assert [flags[c] for c in ("custom:products", "custom:services", "other:cost_of_revenue")] == [
        False,
        False,
        False,
    ]


def test_the_normalized_view_keeps_custom_lines_reported_and_other_follows_the_parent() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (3 * B,) * 4})
    values = [value("custom:products", 2024, "FY", 3)]

    reported = table(values, rows=rows)
    normalized = table(values, rows=rows, adjustments=[adj(1, "cost_of_revenue", 2024, "FY", B)])

    assert at(normalized, "custom:products", "FY2024") == at(reported, "custom:products", "FY2024")
    assert at(normalized, "cost_of_revenue", "FY2024") == Decimal(13 * B)
    assert at(normalized, "other:cost_of_revenue", "FY2024") == Decimal(10 * B)


def test_custom_values_do_not_move_the_coverage_of_a_statement() -> None:
    plain = table([])
    with_custom = table(
        [value("custom:products", 2024, "FY", 3), value("custom:services", 2024, "FY", 4)],
        frozenset(),
    )
    mapped = {"revenue", "cost_of_revenue", "gross_profit", "cash"}

    a = table_coverage(plain, ITEMS, mapped, [])
    b = table_coverage(with_custom, ITEMS, mapped, [])

    assert (a.cells, a.filled, a.by_provenance, a.causes) == (
        b.cells,
        b.filled,
        b.by_provenance,
        b.causes,
    )


def test_a_period_only_custom_values_fill_is_still_no_filing_data() -> None:
    # 2022 has no canonical value; a custom value there must not turn it into a gap.
    plain = table([])
    only_custom = table([value("custom:products", 2022, "FY", 3)])
    mapped = {"revenue", "cost_of_revenue", "gross_profit", "cash"}

    a = table_coverage(plain, ITEMS, mapped, [])
    b = table_coverage(only_custom, ITEMS, mapped, [])

    assert b.empty_by_cause["no_filing_data"] > 0  # the 2022 column has no canonical data
    assert b.empty_by_cause["not_reported"] == a.empty_by_cause["not_reported"]
    assert b.by_provenance == a.by_provenance


def test_a_parent_is_complete_when_every_line_under_it_is_marked() -> None:
    lines = [
        ("custom:a", "cost_of_revenue", True),
        ("custom:b", "cost_of_revenue", True),
        ("custom:c", "revenue", True),
        ("custom:d", "revenue", False),
        ("custom:e", "custom:a", False),
    ]

    assert complete_parents(lines) == frozenset({"cost_of_revenue"})


def test_no_lines_means_no_complete_parent() -> None:
    assert complete_parents([]) == frozenset()
