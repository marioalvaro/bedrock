"""Custom child lines in the cell engine (FR-DATA-16): their cells, and a complete breakdown
building an empty parent (erd/data.md, "Custom lines")."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.cells import SolvedCells, solve_cells
from bedrock.statements.imports import StoredValue, company_calendar, imported_frames
from bedrock.statements.rules import Rules
from tests.engine_data import facts, flow_facts, fy_dates, item
from tests.test_import_pipeline import AT, ITEMS, MAPS, B, quarter, sec_rows


def custom(code: str, parent: str, statement: str = "IS", kind: str = "flow") -> CanonicalItemDef:
    return replace(item(code, statement, kind=kind, parent=parent), custom=True)


PRODUCTS = custom("custom:products", "cost_of_revenue")
SERVICES = custom("custom:services", "cost_of_revenue")
PHONES = custom("custom:phones", "custom:products")
DEPOSITS = custom("custom:deposits", "cash", "BS", "instant")
LINES = [*ITEMS, PRODUCTS, SERVICES, PHONES, DEPOSITS]
BY_CODE = {i.code: i for i in LINES}


def value(code: str, fy: int, period: str, amount: int, *, at: datetime = AT) -> StoredValue:
    instant = BY_CODE[code].kind == "instant"
    if period == "FY":
        start, end, _ = fy_dates(fy)
    else:
        start, end = quarter(fy, int(period[1]))
    return StoredValue(
        1, "m.xlsx", at, code, fy, period, None if instant else start, end, Decimal(amount) * B
    )


def solve(
    values: list[StoredValue],
    complete: frozenset[str] = frozenset(),
    rows=None,  # type: ignore[no-untyped-def]
    lines: list[CanonicalItemDef] = LINES,
) -> SolvedCells:
    canonical = map_facts(select_vintage(facts(rows or sec_rows())), MAPS, ITEMS)
    frames = imported_frames(values, lines)
    rules = Rules(
        imported=frames.newest, imported_vintages=frames.vintages, complete_parents=complete
    )
    return solve_cells(canonical, lines, company_calendar(canonical, rules.imported), rules)


def test_a_custom_flow_fills_its_cells_and_q4_is_the_remainder() -> None:
    values = [
        value("custom:products", 2024, p, v)
        for p, v in (("FY", 40), ("Q1", 9), ("Q2", 10), ("Q3", 11))
    ]

    cells = solve(values).cells

    assert (
        cells[("custom:products", "FY2024")].value,
        cells[("custom:products", "FY2024")].provenance,
    ) == (Decimal(40 * B), "imported")
    q4 = cells[("custom:products", "FY2024Q4")]
    assert (q4.value, q4.provenance) == (Decimal(10 * B), "derived")
    assert q4.derivation is not None and q4.derivation.formula == "FY - Q1 - Q2 - Q3"


def test_a_custom_instant_has_the_year_end_balance_in_q4() -> None:
    cells = solve([value("custom:deposits", 2024, "FY", 1)]).cells

    assert cells[("custom:deposits", "FY2024Q4")].value == Decimal(1 * B)


def test_a_complete_breakdown_builds_an_empty_parent() -> None:
    values = [value("custom:products", 2024, "FY", 3), value("custom:services", 2024, "FY", 4)]

    cells = solve(values, frozenset({"cost_of_revenue"})).cells

    parent = cells[("cost_of_revenue", "FY2024")]
    assert (parent.value, parent.provenance) == (Decimal(7 * B), "derived")
    assert parent.derivation is not None
    assert parent.derivation.formula == "sum of custom breakdown"
    assert [(i.code, i.value) for i in parent.derivation.inputs] == [
        ("custom:products", Decimal(3 * B)),
        ("custom:services", Decimal(4 * B)),
    ]


def test_a_built_parent_feeds_the_formulas_that_read_it() -> None:
    values = [value("custom:products", 2024, "FY", 3), value("custom:services", 2024, "FY", 4)]

    cells = solve(values, frozenset({"cost_of_revenue"})).cells

    assert cells[("gross_profit", "FY2024")].value == Decimal(33 * B)  # 40 - 7


def test_an_incomplete_breakdown_leaves_the_parent_empty() -> None:
    values = [value("custom:products", 2024, "FY", 3), value("custom:services", 2024, "FY", 4)]

    cells = solve(values).cells

    assert cells[("cost_of_revenue", "FY2024")].value is None


def test_a_child_missing_in_a_period_leaves_the_parent_empty_in_that_period() -> None:
    values = [
        value("custom:products", 2024, "FY", 3),
        value("custom:services", 2024, "FY", 4),
        value("custom:products", 2023, "FY", 2),  # no services in 2023
    ]

    cells = solve(values, frozenset({"cost_of_revenue"})).cells

    assert cells[("cost_of_revenue", "FY2024")].value == Decimal(7 * B)
    assert cells[("cost_of_revenue", "FY2023")].value is None


def test_quarters_of_the_parent_follow_the_quarters_of_its_children() -> None:
    values = [
        value("custom:products", 2024, p, v)
        for p, v in (("FY", 40), ("Q1", 9), ("Q2", 10), ("Q3", 11))
    ] + [
        value("custom:services", 2024, p, v)
        for p, v in (("FY", 20), ("Q1", 4), ("Q2", 5), ("Q3", 6))
    ]

    cells = solve(values, frozenset({"cost_of_revenue"})).cells

    got = [cells[("cost_of_revenue", f"FY2024{p}")].value for p in ("", "Q1", "Q2", "Q3", "Q4")]
    assert got == [Decimal(n * B) for n in (60, 13, 15, 17, 15)]
    assert sum(got[1:], Decimal(0)) == got[0]  # Q1..Q4 add up to the year


def test_a_sec_value_is_never_replaced_by_the_sum() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (B, B, B, B)})
    values = [value("custom:products", 2024, "FY", 1), value("custom:services", 2024, "FY", 1)]

    solved = solve(values, frozenset({"cost_of_revenue"}), rows)

    parent = solved.cells[("cost_of_revenue", "FY2024")]
    assert (parent.value, parent.provenance) == (Decimal(4 * B), "reported")


def test_a_complete_breakdown_that_does_not_foot_a_present_parent_is_a_warning() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (B, B, B, B)})
    values = [value("custom:products", 2024, "FY", 1), value("custom:services", 2024, "FY", 1)]

    solved = solve(values, frozenset({"cost_of_revenue"}), rows)

    (warning,) = [w for w in solved.warnings if w.rule == "custom_breakdown"]
    assert (warning.code, warning.period_key) == ("cost_of_revenue", "FY2024")
    assert warning.value == Decimal(2 * B) and "4" in warning.reason


def test_a_complete_breakdown_that_foots_gives_no_warning() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (B, B, B, B)})
    values = [value("custom:products", 2024, "FY", 1), value("custom:services", 2024, "FY", 3)]

    solved = solve(values, frozenset({"cost_of_revenue"}), rows)

    assert [w for w in solved.warnings if w.rule == "custom_breakdown"] == []


def test_a_breakdown_not_marked_complete_gives_no_warning() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (B, B, B, B)})

    solved = solve([value("custom:products", 2024, "FY", 1)], frozenset(), rows)

    assert solved.warnings == ()


def test_a_breakdown_with_a_missing_child_gives_no_footing_warning() -> None:
    rows = sec_rows() + flow_facts("CostOfRevenue", {2024: (B, B, B, B)})

    solved = solve([value("custom:products", 2024, "FY", 1)], frozenset({"cost_of_revenue"}), rows)

    assert [w for w in solved.warnings if w.rule == "custom_breakdown"] == []


def test_a_nested_breakdown_builds_each_level() -> None:
    values = [value("custom:phones", 2024, "FY", 3), value("custom:services", 2024, "FY", 4)]

    cells = solve(values, frozenset({"cost_of_revenue", "custom:products"})).cells

    assert cells[("custom:products", "FY2024")].value == Decimal(3 * B)
    assert cells[("custom:products", "FY2024")].derivation is not None
    assert cells[("cost_of_revenue", "FY2024")].value == Decimal(7 * B)


def test_a_computed_line_is_never_built_from_children() -> None:
    computed = item("op_costs", derive="revenue - gross_profit")
    child = custom("custom:rent", "op_costs")
    lines = [*ITEMS, computed, child]
    frames = imported_frames([value_for(child, 3)], lines)
    canonical = map_facts(select_vintage(facts(sec_rows())), MAPS, ITEMS)
    rules = Rules(
        imported=frames.newest,
        imported_vintages=frames.vintages,
        complete_parents=frozenset({"op_costs"}),
    )

    cells = solve_cells(canonical, lines, company_calendar(canonical, rules.imported), rules).cells

    assert cells[("op_costs", "FY2024")].value is None


def value_for(line: CanonicalItemDef, amount: int) -> StoredValue:
    start, end, _ = fy_dates(2024)
    return StoredValue(1, "m.xlsx", AT, line.code, 2024, "FY", start, end, Decimal(amount) * B)


def test_custom_lines_change_no_canonical_cell() -> None:
    values = [
        value("custom:products", 2024, "FY", 3),
        value("custom:services", 2024, "FY", 4),
        value("custom:deposits", 2024, "FY", 1),
    ]
    sec_rows_only = sec_rows()
    canonical = map_facts(select_vintage(facts(sec_rows_only)), MAPS, ITEMS)
    plain = solve_cells(canonical, ITEMS, company_calendar(canonical, None), Rules())

    with_custom = solve(values)  # not marked complete

    for key, cell in plain.cells.items():
        assert with_custom.cells[key] == cell, key
