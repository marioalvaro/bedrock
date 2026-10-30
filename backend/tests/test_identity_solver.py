"""Identity solving in `solve_cells` (docs/erd/data.md "R1: identities"), on synthetic frames."""

from collections.abc import Iterable, Sequence
from decimal import Decimal

import pytest

from bedrock.mapping.config import CanonicalItemDef, IdentityDef, SolveRule, parse_formula
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.cells import Cell, solve_cells
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.rules import Rules, RuleWarning
from tests.engine_data import Row, facts, flow_facts, fy_dates, instant_facts, item, mappings

B = 1_000_000_000  # values are in billions, well above the USD 1 M tolerance floor


def scaled(values: Sequence[int]) -> tuple[int, ...]:
    return tuple(v * B for v in values)


def identity(identity_id: str, equation: str, **solve: SolveRule) -> IdentityDef:
    left, right = equation.split("=")
    terms = (*parse_formula(left), *((-s, c) for s, c in parse_formula(right)))
    return IdentityDef(identity_id, equation, terms, solve)


EXACT = SolveRule("exact", None)
ZERO = SolveRule("zero_only", None)


def bounded(ratio: str) -> SolveRule:
    return SolveRule("bounded", Decimal(ratio))


GP = identity("gp", "gross_profit = revenue - cost_of_revenue", cost_of_revenue=EXACT)

IS_ITEMS = [item("revenue"), item("cost_of_revenue"), item("gross_profit")]
IS_MAP = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("gross_profit", "GrossProfit", 0),
)


def solve(
    rows: Iterable[Row],
    items: list[CanonicalItemDef],
    maps: object,
    identities: Sequence[IdentityDef],
    nci_filings: frozenset[str] | None = None,
) -> tuple[dict[tuple[str, str], Cell], list[RuleWarning]]:
    canonical = map_facts(select_vintage(facts(rows)), maps, items)  # type: ignore[arg-type]
    result = solve_cells(
        canonical, items, fiscal_calendar(canonical), Rules(tuple(identities), nci_filings)
    )
    return result.cells, list(result.warnings)


def income(revenue: Sequence[int], gross: Sequence[int]) -> list[Row]:
    return [
        *flow_facts("Revenues", {2023: scaled(revenue)}),
        *flow_facts("GrossProfit", {2023: scaled(gross)}),
    ]


def value(cells: dict[tuple[str, str], Cell], code: str, period: str) -> Decimal | None:
    return cells[(code, period)].value


# --- the solver ----------------------------------------------------------------------------


def test_one_empty_term_is_solved_in_the_year_and_every_quarter() -> None:
    cells, warnings = solve(income((100, 110, 120, 130), (40, 45, 50, 55)), IS_ITEMS, IS_MAP, [GP])

    assert value(cells, "cost_of_revenue", "FY2023") == 270 * B
    assert [value(cells, "cost_of_revenue", f"FY2023Q{n}") for n in (1, 2, 3)] == [
        60 * B,
        65 * B,
        70 * B,
    ]
    assert warnings == []


def test_a_solved_cell_is_derived_and_explains_the_identity() -> None:
    cells, _ = solve(income((100, 110, 120, 130), (40, 45, 50, 55)), IS_ITEMS, IS_MAP, [GP])

    cell = cells[("cost_of_revenue", "FY2023")]
    assert cell.provenance == "derived"
    assert cell.source is None
    assert cell.solved_by == "gp"
    assert cell.derivation is not None
    assert cell.derivation.formula == "identity gp: cost_of_revenue = revenue - gross_profit"
    assert [(i.code, i.value) for i in cell.derivation.inputs] == [
        ("revenue", 460 * B),
        ("gross_profit", 190 * B),
    ]


def test_q4_of_a_solved_flow_is_fy_less_the_quarters_so_the_year_adds_up() -> None:
    cells, _ = solve(income((100, 110, 120, 130), (40, 45, 50, 55)), IS_ITEMS, IS_MAP, [GP])

    quarters = [value(cells, "cost_of_revenue", f"FY2023Q{n}") for n in (1, 2, 3, 4)]
    assert quarters[3] == 75 * B
    assert sum(q for q in quarters if q is not None) == value(cells, "cost_of_revenue", "FY2023")
    assert cells[("cost_of_revenue", "FY2023Q4")].derivation is not None


def test_two_empty_terms_are_not_solved() -> None:
    rows = flow_facts("Revenues", {2023: scaled((100, 110, 120, 130))})

    cells, warnings = solve(rows, IS_ITEMS, IS_MAP, [GP])

    assert value(cells, "cost_of_revenue", "FY2023") is None
    assert value(cells, "gross_profit", "FY2023") is None
    assert warnings == []


def test_a_term_that_is_not_under_solve_is_never_filled() -> None:
    # revenue is the single empty term, but only cost_of_revenue may be solved
    rows = [
        *flow_facts("CostOfRevenue", {2023: scaled((60, 65, 70, 75))}),
        *flow_facts("GrossProfit", {2023: scaled((40, 45, 50, 55))}),
    ]

    cells, _ = solve(rows, IS_ITEMS, IS_MAP, [GP])

    assert value(cells, "revenue", "FY2023") is None


def test_a_non_empty_cell_is_never_touched() -> None:
    rows = [
        *income((100, 110, 120, 130), (40, 45, 50, 55)),
        *flow_facts("CostOfRevenue", {2023: scaled((61, 65, 70, 75))}),  # disagrees with the rest
    ]

    cells, warnings = solve(rows, IS_ITEMS, IS_MAP, [GP])

    assert value(cells, "cost_of_revenue", "FY2023") == 271 * B
    assert cells[("cost_of_revenue", "FY2023")].provenance == "reported"
    assert warnings == []


def test_a_residual_is_never_solved() -> None:
    items = [*IS_ITEMS, item("other", derive="gross_profit - revenue", residual=True)]
    on_residual = identity("r", "gross_profit = revenue - other", other=EXACT)

    cells, _ = solve(income((100, 110, 120, 130), (40, 45, 50, 55)), items, IS_MAP, [on_residual])

    # the residual keeps its own formula: gross_profit - revenue
    assert cells[("other", "FY2023")].derivation is not None
    assert cells[("other", "FY2023")].solved_by is None


# --- modes ---------------------------------------------------------------------------------

# a balance sheet has no flow to date the fiscal calendar: a revenue line does
CALENDAR = flow_facts("Revenues", {2023: scaled((1, 1, 1, 1))})

EQUITY_ITEMS = [
    item("revenue"),
    item("total_equity", "BS", kind="instant"),
    item("equity_parent", "BS", kind="instant"),
    item("nci", "BS", kind="instant"),
]
EQUITY_MAP = mappings(
    ("revenue", "Revenues", 0),
    ("total_equity", "EquityIncl", 0),
    ("equity_parent", "Equity", 0),
    ("nci", "Minority", 0),
)
EQUITY = identity("equity", "total_equity = equity_parent + nci", nci=ZERO, equity_parent=EXACT)


def balances(concept: str, year_end: int, quarters: Sequence[int | None]) -> list[Row]:
    return instant_facts(
        concept, {2023: (*[None if q is None else q * B for q in quarters], year_end * B)}
    )


def test_zero_only_accepts_a_zero_within_the_tolerance_and_stores_exactly_zero() -> None:
    rows = [
        *CALENDAR,
        *instant_facts("EquityIncl", {2023: scaled((50, 60, 70, 80))}),
        *instant_facts("Equity", {2023: (50 * B, 60 * B, 70 * B, 80 * B + 400_000)}),
    ]

    cells, warnings = solve(rows, EQUITY_ITEMS, EQUITY_MAP, [EQUITY])

    cell = cells[("nci", "FY2023")]
    assert cell.value == Decimal(0)  # -400,000 is within USD 1 M
    assert cell.provenance == "zero_inferred"
    assert cell.solved_by == "equity"
    assert warnings == []


def test_zero_only_rejects_a_real_difference_and_warns() -> None:
    rows = [
        *CALENDAR,
        *instant_facts("EquityIncl", {2023: scaled((50, 60, 70, 80))}),
        *instant_facts("Equity", {2023: scaled((50, 60, 70, 75))}),
    ]

    cells, warnings = solve(rows, EQUITY_ITEMS, EQUITY_MAP, [EQUITY])

    assert value(cells, "nci", "FY2023") is None
    [warning] = [w for w in warnings if w.period_key == "FY2023"]
    assert (warning.rule, warning.code, warning.value) == ("equity", "nci", 5 * B)
    assert "tolerance" in warning.reason


def test_exact_stores_the_result_as_derived_even_when_it_is_large() -> None:
    rows = [
        *CALENDAR,
        *instant_facts("EquityIncl", {2023: scaled((50, 60, 70, 80))}),
        *instant_facts("Minority", {2023: scaled((5, 5, 5, 20))}),
    ]

    cells, _ = solve(rows, EQUITY_ITEMS, EQUITY_MAP, [EQUITY])

    assert value(cells, "equity_parent", "FY2023") == 60 * B
    assert cells[("equity_parent", "FY2023")].provenance == "derived"


CASH_ITEMS = [
    item("net_change_in_cash", "CF"),
    item("cfo", "CF"),
    item("cff", "CF"),
    item("fx_effect", "CF"),
]
CASH_MAP = mappings(
    ("net_change_in_cash", "NetChange", 0),
    ("cfo", "Cfo", 0),
    ("cff", "Cff", 0),
    ("fx_effect", "Fx", 0),
)


def cash(net_change: Sequence[int]) -> list[Row]:
    return [
        *flow_facts("NetChange", {2023: scaled(net_change)}),
        *flow_facts("Cfo", {2023: scaled((100, 100, 100, 100))}),
        *flow_facts("Cff", {2023: scaled((-50, -50, -50, -50))}),
    ]


def test_bounded_accepts_a_result_within_the_ratio_of_the_largest_term() -> None:
    fx = identity("cash", "net_change_in_cash = cfo + cff + fx_effect", fx_effect=bounded("0.05"))

    cells, warnings = solve(cash((48, 48, 48, 48)), CASH_ITEMS, CASH_MAP, [fx])

    # fx = 48 - 100 + 50 = -2 B per quarter; the largest |term| is 100 B (cfo); 2 <= 5
    assert value(cells, "fx_effect", "FY2023") == -8 * B
    assert cells[("fx_effect", "FY2023")].provenance == "derived"
    assert warnings == []


def test_bounded_rejects_a_result_beyond_the_ratio_and_warns() -> None:
    fx = identity("cash", "net_change_in_cash = cfo + cff + fx_effect", fx_effect=bounded("0.05"))

    cells, warnings = solve(cash((40, 40, 40, 40)), CASH_ITEMS, CASH_MAP, [fx])

    # fx = 40 - 100 + 50 = -10 B per quarter, 10% of the 100 B cfo
    assert value(cells, "fx_effect", "FY2023") is None
    assert {w.period_key for w in warnings} == {"FY2023", "FY2023Q1", "FY2023Q2", "FY2023Q3"}
    assert all(w.rule == "cash" and w.code == "fx_effect" for w in warnings)


def test_a_rejected_flow_leaves_q4_empty_too() -> None:
    fx = identity("cash", "net_change_in_cash = cfo + cff + fx_effect", fx_effect=bounded("0.05"))

    cells, _ = solve(cash((40, 40, 40, 40)), CASH_ITEMS, CASH_MAP, [fx])

    assert value(cells, "fx_effect", "FY2023Q4") is None


# --- guards --------------------------------------------------------------------------------


def test_operands_from_different_filings_are_not_solved_and_warn() -> None:
    rows = [
        *flow_facts("Revenues", {2023: scaled((100, 110, 120, 130))}),
        *flow_facts("GrossProfit", {2023: scaled((40, 45, 50, 55))}),
    ]
    _, end, _ = fy_dates(2023)
    rows = [
        {**r, "accession_no": "K-RESTATED"}
        if r["concept"] == "GrossProfit" and r["period_end"] == end
        else r
        for r in rows
    ]

    cells, warnings = solve(rows, IS_ITEMS, IS_MAP, [GP])

    assert value(cells, "cost_of_revenue", "FY2023") is None
    [warning] = [w for w in warnings if w.period_key == "FY2023"]
    assert warning.rule == "gp" and warning.value is None
    assert "different filings" in warning.reason
    assert value(cells, "cost_of_revenue", "FY2023Q1") == 60 * B  # the quarters are unaffected
    # Q4 is never solved on its own (its operands are FY - Q1..Q3 and would fill it while the
    # year is empty); with no year there is nothing for Q4 to follow
    assert value(cells, "cost_of_revenue", "FY2023Q4") is None


def test_two_operands_carrying_the_same_fact_make_the_identity_circular() -> None:
    items = [item("revenue"), item("cost_of_revenue"), item("gross_profit")]
    maps = mappings(
        ("revenue", "Revenues", 0),
        ("cost_of_revenue", "CostOfRevenue", 0),
        ("gross_profit", "Revenues", 0),  # the same fact under two codes
    )

    cells, warnings = solve(
        flow_facts("Revenues", {2023: scaled((100, 110, 120, 130))}), items, maps, [GP]
    )

    assert value(cells, "cost_of_revenue", "FY2023") is None
    assert warnings == []


def test_a_derived_operand_built_from_the_others_does_not_make_a_zero() -> None:
    # total_liabilities = LE - equity when `Liabilities` is not tagged: solving temporary equity
    # from it would give 0 for any company, redeemable interests or not
    items = [
        item("revenue"),
        item("total_liabilities_and_equity", "BS", kind="instant"),
        item(
            "total_liabilities",
            "BS",
            kind="instant",
            derive="total_liabilities_and_equity - total_equity",
        ),
        item("temporary_equity", "BS", kind="instant"),
        item("total_equity", "BS", kind="instant"),
    ]
    maps = mappings(
        ("revenue", "Revenues", 0),
        ("total_liabilities_and_equity", "LE", 0),
        ("total_equity", "Equity", 0),
    )
    balance = identity(
        "bs",
        "total_liabilities_and_equity = total_liabilities + temporary_equity + total_equity",
        temporary_equity=ZERO,
    )
    rows = [
        *CALENDAR,
        *instant_facts("LE", {2023: scaled((300, 310, 320, 330))}),
        *instant_facts("Equity", {2023: scaled((100, 110, 120, 130))}),
    ]

    cells, warnings = solve(rows, items, maps, [balance])

    assert value(cells, "total_liabilities", "FY2023") == 200 * B
    assert value(cells, "temporary_equity", "FY2023") is None
    assert warnings == []


def test_a_value_solved_by_one_identity_is_not_an_operand_of_another() -> None:
    items = [item(c) for c in ("x", "y", "z", "w", "v")]
    maps = mappings(("x", "X", 0), ("y", "Y", 0), ("w", "W", 0))
    first = identity("a", "x = y + z", z=EXACT)
    second = identity("b", "z = w + v", v=EXACT)
    rows = [
        *flow_facts("X", {2023: scaled((10, 10, 10, 10))}),
        *flow_facts("Y", {2023: scaled((4, 4, 4, 4))}),
        *flow_facts("W", {2023: scaled((1, 1, 1, 1))}),
    ]

    cells, _ = solve(rows, items, maps, [first, second])

    assert value(cells, "z", "FY2023") == 24 * B
    assert value(cells, "v", "FY2023") is None


def test_a_derive_formula_may_use_a_solved_value() -> None:
    items = [*IS_ITEMS, item("cost_plus_one", derive="cost_of_revenue + revenue")]

    cells, _ = solve(income((100, 110, 120, 130), (40, 45, 50, 55)), items, IS_MAP, [GP])

    assert value(cells, "cost_plus_one", "FY2023") == (270 + 460) * B


def test_two_identities_giving_different_values_the_first_in_file_order_wins_and_warns() -> None:
    items = [item(c) for c in ("x", "y", "z", "w")]
    maps = mappings(("x", "X", 0), ("y", "Y", 0), ("w", "W", 0))
    first = identity("a", "x = y + z", z=EXACT)
    second = identity("b", "w = z", z=EXACT)
    rows = [
        *flow_facts("X", {2023: scaled((10, 10, 10, 10))}),
        *flow_facts("Y", {2023: scaled((4, 4, 4, 4))}),
        *flow_facts("W", {2023: scaled((7, 7, 7, 7))}),
    ]

    cells, warnings = solve(rows, items, maps, [first, second])

    assert value(cells, "z", "FY2023") == 24 * B
    assert cells[("z", "FY2023")].solved_by == "a"
    [warning] = [w for w in warnings if w.period_key == "FY2023"]
    assert warning.rule == "b" and warning.code == "z" and warning.value == 28 * B
    assert "a" in warning.reason


def test_two_identities_agreeing_on_a_value_record_no_warning() -> None:
    items = [item(c) for c in ("x", "y", "z", "w")]
    maps = mappings(("x", "X", 0), ("y", "Y", 0), ("w", "W", 0))
    first = identity("a", "x = y + z", z=EXACT)
    second = identity("b", "w = z", z=EXACT)
    rows = [
        *flow_facts("X", {2023: scaled((10, 10, 10, 10))}),
        *flow_facts("Y", {2023: scaled((4, 4, 4, 4))}),
        *flow_facts("W", {2023: scaled((6, 6, 6, 6))}),
    ]

    cells, warnings = solve(rows, items, maps, [first, second])

    assert value(cells, "z", "FY2023") == 24 * B
    assert warnings == []


def test_a_warning_is_recorded_once_per_cell_however_many_passes_run() -> None:
    fx = identity("cash", "net_change_in_cash = cfo + cff + fx_effect", fx_effect=bounded("0.05"))

    _, warnings = solve(cash((40, 40, 40, 40)), CASH_ITEMS, CASH_MAP, [fx])

    keys = [(w.rule, w.code, w.period_key) for w in warnings]
    assert len(keys) == len(set(keys))


# --- instants ------------------------------------------------------------------------------


def test_an_instant_is_solved_at_the_year_and_quarters_and_q4_copies_the_year() -> None:
    items = [
        item("revenue"),
        item("total_assets", "BS", kind="instant"),
        item("total_liabilities_and_equity", "BS", kind="instant"),
    ]
    maps = mappings(
        ("revenue", "Revenues", 0),
        ("total_liabilities_and_equity", "LE", 0),
        ("total_assets", "Assets", 0),
    )
    both_ways = identity(
        "ta",
        "total_assets = total_liabilities_and_equity",
        total_assets=EXACT,
        total_liabilities_and_equity=EXACT,
    )

    cells, _ = solve(
        [*CALENDAR, *instant_facts("LE", {2023: scaled((300, 310, 320, 330))})],
        items,
        maps,
        [both_ways],
    )

    assert [value(cells, "total_assets", f"FY2023Q{n}") for n in (1, 2, 3, 4)] == [
        300 * B,
        310 * B,
        320 * B,
        330 * B,
    ]
    assert cells[("total_assets", "FY2023Q4")] == cells[("total_assets", "FY2023")]


@pytest.mark.parametrize("quarter", [1, 2, 3])
def test_a_discrete_quarter_is_solved_from_its_own_filing(quarter: int) -> None:
    cells, _ = solve(income((100, 110, 120, 130), (40, 45, 50, 55)), IS_ITEMS, IS_MAP, [GP])

    assert cells[("cost_of_revenue", f"FY2023Q{quarter}")].provenance == "derived"
