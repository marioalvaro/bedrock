"""Combined lines in the cell engine (docs/erd/data-coverage.md "Combined lines", engine rules 1-4),
on synthetic frames. Pure."""

from collections.abc import Iterable
from decimal import Decimal

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import build_statement
from bedrock.statements.cells import Cell, solve_cells
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.rules import RuleWarning
from tests.engine_data import Row, facts, flow_facts, instant_facts, item, mappings

B = 1_000_000_000
YEAR = ("FY2023Q1", "FY2023Q2", "FY2023Q3", "FY2023Q4", "FY2023")

BS_ITEMS = [
    item("revenue"),  # its flows give the fiscal calendar
    item("total_current_liabilities", "BS", kind="instant"),
    item("accounts_payable", "BS", kind="instant", parent="total_current_liabilities"),
    item("accrued_liabilities", "BS", kind="instant", parent="total_current_liabilities"),
    item(
        "other_current_liabilities",
        "BS",
        kind="instant",
        parent="total_current_liabilities",
        derive="total_current_liabilities - accounts_payable - accrued_liabilities",
        residual=True,
    ),
]
COMBINED = "AccountsPayableAndAccruedLiabilitiesCurrent"
BS_MAP = mappings(
    ("revenue", "Revenues", 0),
    ("total_current_liabilities", "LiabilitiesCurrent", 0),
    ("accounts_payable", "AccountsPayableCurrent", 0),
    ("accounts_payable", COMBINED, 1, False, "accrued_liabilities"),
    ("accrued_liabilities", "AccruedLiabilitiesCurrent", 0),
)


def solve(
    rows: Iterable[Row], items: list[CanonicalItemDef], maps: object
) -> tuple[dict[tuple[str, str], Cell], list[RuleWarning]]:
    canonical = map_facts(select_vintage(facts(rows)), maps, items)  # type: ignore[arg-type]
    result = solve_cells(canonical, items, fiscal_calendar(canonical))
    return result.cells, list(result.warnings)


def balances(**values: tuple[int | None, ...]) -> list[Row]:
    """Instants of FY2023 (Q1, Q2, Q3, year end), in billions, by concept."""
    return [
        *(
            row
            for concept, v in values.items()
            for row in instant_facts(
                concept, {2023: tuple(None if x is None else x * B for x in v)}
            )
        ),
        *flow_facts("Revenues", {2023: (1, 1, 1, 1)}),  # a calendar for the instants
    ]


def test_the_carrier_shows_the_combined_value_and_names_what_it_covers() -> None:
    cells, warnings = solve(
        balances(LiabilitiesCurrent=(100, 100, 100, 100), **{COMBINED: (60, 61, 62, 63)}),
        BS_ITEMS,
        BS_MAP,
    )

    for key, expected in zip(YEAR, (60, 61, 62, 63, 63), strict=True):
        carrier = cells[("accounts_payable", key)]
        assert carrier.value == expected * B
        assert carrier.provenance == "reported"
        assert carrier.combined_with == ("accrued_liabilities",)
        covered = cells[("accrued_liabilities", key)]
        assert covered.value is None
        assert covered.included_in == "accounts_payable"
    assert warnings == []


def test_the_residual_still_foots_with_the_covered_line_as_zero() -> None:
    cells, _ = solve(
        balances(LiabilitiesCurrent=(100, 100, 100, 100), **{COMBINED: (60, 61, 62, 63)}),
        BS_ITEMS,
        BS_MAP,
    )

    assert cells[("other_current_liabilities", "FY2023")].value == 37 * B


def test_both_lines_reported_skip_the_combined_entry_with_a_warning() -> None:
    # The accrued line is tagged at the year end only: there the combined concept is a subtotal.
    cells, warnings = solve(
        balances(
            LiabilitiesCurrent=(100, 100, 100, 100),
            AccruedLiabilitiesCurrent=(None, None, None, 20),
            **{COMBINED: (60, 61, 62, 63)},
        ),
        BS_ITEMS,
        BS_MAP,
    )

    for key in ("FY2023", "FY2023Q4"):
        assert cells[("accounts_payable", key)].value is None
        assert cells[("accounts_payable", key)].combined_with is None
        assert cells[("accrued_liabilities", key)].value == 20 * B
        assert cells[("accrued_liabilities", key)].included_in is None
    assert cells[("accounts_payable", "FY2023Q2")].value == 61 * B  # the quarters still use it
    assert [(w.rule, w.code, w.period_key) for w in warnings] == [
        ("combined_overlap", "accounts_payable", "FY2023")
    ]
    assert "accrued_liabilities" in warnings[0].reason
    assert warnings[0].value == 63 * B


def test_a_plain_entry_wins_over_a_combined_one() -> None:
    cells, warnings = solve(
        balances(
            LiabilitiesCurrent=(100, 100, 100, 100),
            AccountsPayableCurrent=(40, 41, 42, 43),
            **{COMBINED: (60, 61, 62, 63)},
        ),
        BS_ITEMS,
        BS_MAP,
    )

    assert cells[("accounts_payable", "FY2023")].value == 43 * B
    assert cells[("accounts_payable", "FY2023")].combined_with is None
    assert cells[("accrued_liabilities", "FY2023")].included_in is None
    assert warnings == []


def test_no_rule_fills_a_covered_cell() -> None:
    items = [
        *BS_ITEMS[:3],
        item(
            "accrued_liabilities",
            "BS",
            kind="instant",
            parent="total_current_liabilities",
            derive="total_current_liabilities - accounts_payable",
            concepts=("AccruedLiabilitiesCurrent",),
        ),
    ]
    cells, _ = solve(
        balances(LiabilitiesCurrent=(100, 100, 100, 100), **{COMBINED: (60, 61, 62, 63)}),
        items,
        BS_MAP,
    )

    assert cells[("accrued_liabilities", "FY2023")].value is None
    assert cells[("accrued_liabilities", "FY2023")].included_in == "accounts_payable"


CASH_ITEMS = [
    item("revenue"),
    item("cash", "BS", kind="instant"),
    item("short_term_investments", "BS", kind="instant"),
    item("total_debt", "BS", kind="instant"),
    item("net_debt", "BS", kind="instant", derive="total_debt - cash - short_term_investments"),
    item("liquid", "BS", kind="instant", derive="short_term_investments + total_debt"),
]
CASH_MAP = mappings(
    ("revenue", "Revenues", 0),
    ("cash", "CashAndCashEquivalentsAtCarryingValue", 0),
    ("cash", "CashCashEquivalentsAndShortTermInvestments", 1, False, "short_term_investments"),
    ("short_term_investments", "ShortTermInvestments", 0),
    ("total_debt", "Debt", 0),
)


def test_a_formula_with_the_carrier_counts_the_covered_line_as_zero() -> None:
    cells, _ = solve(
        balances(
            Debt=(90, 90, 90, 90), CashCashEquivalentsAndShortTermInvestments=(30, 30, 30, 35)
        ),
        CASH_ITEMS,
        CASH_MAP,
    )

    assert cells[("net_debt", "FY2023")].value == 55 * B  # debt less cash and investments
    # without the carrier among its terms the formula has no value for the covered line
    assert cells[("liquid", "FY2023")].value is None


def test_a_combined_entry_covering_no_row_marks_the_carrier_only() -> None:
    items = [item("cfo", "CF"), item("change_payables", "CF", parent="cfo")]
    maps = mappings(
        ("change_payables", "IncreaseDecreaseInAccountsPayable", 0),
        ("change_payables", "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities", 1, False, ""),
    )
    rows = flow_facts(
        "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities", {2023: (1, 2, 3, 4)}
    )
    cells, warnings = solve(rows, items, maps)

    assert cells[("change_payables", "FY2023")].value == 10
    assert cells[("change_payables", "FY2023")].combined_with == ()
    assert warnings == []


CF_ITEMS = [item("change_payables", "CF"), item("cfo", "CF")]
CF_MAP = mappings(
    ("change_payables", "IncreaseDecreaseInAccountsPayable", 0),
    ("change_payables", "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities", 1, False, ""),
    ("cfo", "NetCashProvidedByUsedInOperatingActivities", 0),
)


def test_q4_and_ttm_carry_the_marker_when_any_quarter_does() -> None:
    # The plain tag in Q1 only; the combined one in the 10-K and the other 10-Qs.
    rows = [
        *flow_facts(
            "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
            {2023: (5, 6, 7, 8)},
            skip=frozenset({(2023, 1)}),
        ),
        *(
            r
            for r in flow_facts("IncreaseDecreaseInAccountsPayable", {2023: (5, 0, 0, 0)})
            if r["accession_no"] == "Q1-2023"
        ),
        *flow_facts("NetCashProvidedByUsedInOperatingActivities", {2023: (1, 1, 1, 1)}),
    ]
    canonical = map_facts(select_vintage(facts(rows)), CF_MAP, CF_ITEMS)
    cells = solve_cells(canonical, CF_ITEMS, fiscal_calendar(canonical)).cells

    assert cells[("change_payables", "FY2023Q1")].combined_with is None
    assert cells[("change_payables", "FY2023Q4")].value == 8
    assert cells[("change_payables", "FY2023Q4")].combined_with == ()

    ttm = build_statement(canonical, CF_ITEMS, "CF", "ttm")
    row = next(r for r in ttm.rows if r.code == "change_payables")
    at = [p.key for p in ttm.periods].index("TTM-FY2023Q4")
    assert row.combined_with[at] == ()
    assert len(row.combined_with) == len(row.included_in) == len(ttm.periods)


def test_the_statement_rows_carry_both_markers_aligned_with_the_periods() -> None:
    rows = balances(LiabilitiesCurrent=(100, 100, 100, 100), **{COMBINED: (60, 61, 62, 63)})
    canonical = map_facts(select_vintage(facts(rows)), BS_MAP, BS_ITEMS)
    table = build_statement(canonical, BS_ITEMS, "BS", "annual")
    by_code = {r.code: r for r in table.rows}
    at = [p.key for p in table.periods].index("FY2023")

    assert by_code["accounts_payable"].combined_with[at] == ("accrued_liabilities",)
    assert by_code["accounts_payable"].included_in[at] is None
    assert by_code["accrued_liabilities"].included_in[at] == "accounts_payable"
    assert by_code["accrued_liabilities"].combined_with[at] is None
    assert by_code["other_current_liabilities"].combined_with[at] is None


def test_a_carrier_value_survives_normalization_with_its_marker() -> None:
    rows = balances(LiabilitiesCurrent=(100, 100, 100, 100), **{COMBINED: (60, 61, 62, 63)})
    canonical = map_facts(select_vintage(facts(rows)), BS_MAP, BS_ITEMS)

    class Adj:
        id = 1
        canonical_code = "accounts_payable"
        fiscal_year = 2023
        fiscal_period = "FY"
        amount = Decimal(B)

    table = build_statement(canonical, BS_ITEMS, "BS", "annual", adjustments=[Adj()])  # type: ignore[list-item]
    row = next(r for r in table.rows if r.code == "accounts_payable")
    at = [p.key for p in table.periods].index("FY2023")
    assert row.values[at] == 64 * B
    assert row.provenance[at] == "normalized"
    assert row.combined_with[at] == ("accrued_liabilities",)


def test_a_ttm_window_is_included_in_only_when_every_empty_quarter_is() -> None:
    from bedrock.statements.build import _ttm_cell

    item_ = item("accrued")
    keys = ["Q1", "Q2", "Q3", "Q4"]
    inside = Cell(None, None, included_in="accounts_payable")
    cells = {("accrued", "Q1"): inside, ("accrued", "Q2"): Cell(None, None)}
    cells |= {("accrued", k): Cell(Decimal(1), "reported") for k in ("Q3", "Q4")}
    assert _ttm_cell(item_, keys, cells).included_in is None  # Q2 is empty for another reason

    cells[("accrued", "Q2")] = inside
    assert _ttm_cell(item_, keys, cells).included_in == "accounts_payable"


def test_a_drop_in_one_year_leaves_the_other_years_q4_as_built() -> None:
    # FY2023 both lines tagged (the combined value is dropped there); FY2024 the combined only
    rows = [
        *instant_facts(COMBINED, {2023: (60 * B, 61 * B, 62 * B, 63 * B), 2024: (70 * B,) * 4}),
        *instant_facts("AccruedLiabilitiesCurrent", {2023: (None, None, None, 20 * B)}),
        *instant_facts("LiabilitiesCurrent", {2023: (100 * B,) * 4, 2024: (100 * B,) * 4}),
        *flow_facts("Revenues", {2023: (1, 1, 1, 1), 2024: (1, 1, 1, 1)}),
    ]
    cells, warnings = solve(rows, BS_ITEMS, BS_MAP)

    assert cells[("accounts_payable", "FY2023Q4")].value is None
    assert cells[("accounts_payable", "FY2024Q4")].value == 70 * B
    assert cells[("accounts_payable", "FY2024Q4")].combined_with == ("accrued_liabilities",)
    assert cells[("accrued_liabilities", "FY2024Q4")].included_in == "accounts_payable"
    assert [w.period_key for w in warnings] == ["FY2023"]
