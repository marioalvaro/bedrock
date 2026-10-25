"""The NCI zero rule R1b (docs/erd/data.md "R1b: NCI zero rule"), on synthetic frames."""

from collections.abc import Iterable
from decimal import Decimal

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import build_statement
from bedrock.statements.cells import Cell, solve_cells
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.rules import Rules
from tests.engine_data import Row, facts, flow_facts, instant_facts, item, mappings

B = 1_000_000_000

ITEMS: list[CanonicalItemDef] = [
    item("revenue"),
    item("net_income"),
    item("net_income_common", derive="net_income - net_income_nci"),
    item("net_income_nci"),
    item("total_equity", "BS", kind="instant", derive="equity_parent + nci"),
    item("equity_parent", "BS", kind="instant"),
    item("nci", "BS", kind="instant"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("net_income", "ProfitLoss", 0),
    ("net_income_nci", "NetIncomeNci", 0),
    ("equity_parent", "StockholdersEquity", 0),
    ("nci", "MinorityInterest", 0),
)


def rows(*, with_nci: bool = False) -> list[Row]:
    out: list[Row] = [
        *flow_facts("Revenues", {2023: (B,) * 4}),
        *flow_facts("ProfitLoss", {2023: (10 * B, 11 * B, 12 * B, 13 * B)}),
        *instant_facts("StockholdersEquity", {2023: (50 * B, 60 * B, 70 * B, 80 * B)}),
    ]
    if with_nci:
        out += flow_facts("NetIncomeNci", {2023: (B, B, B, B)})
        out += instant_facts("MinorityInterest", {2023: (B, B, B, B)})
    return out


def run(raw: Iterable[Row], nci_filings: frozenset[str] | None) -> dict[tuple[str, str], Cell]:
    canonical = map_facts(select_vintage(facts(raw)), MAPS, ITEMS)  # type: ignore[arg-type]
    return solve_cells(canonical, ITEMS, fiscal_calendar(canonical), Rules((), nci_filings)).cells


def test_a_filing_that_tags_no_nci_gives_an_inferred_zero_in_the_year_and_quarters() -> None:
    cells = run(rows(), frozenset())

    for period in ("FY2023", "FY2023Q1", "FY2023Q2", "FY2023Q3"):
        cell = cells[("net_income_nci", period)]
        assert cell.value == Decimal(0)
        assert cell.provenance == "zero_inferred"
        assert cell.source is None


def test_the_derivation_names_the_filing_that_carries_the_statement() -> None:
    cells = run(rows(), frozenset())

    year = cells[("net_income_nci", "FY2023")].derivation
    quarter = cells[("net_income_nci", "FY2023Q2")].derivation
    assert year is not None and quarter is not None
    assert year.formula == "no NCI-inclusive total or NCI concept tagged in 10-K K-2023"
    assert quarter.formula == "no NCI-inclusive total or NCI concept tagged in 10-Q Q2-2023"
    assert year.inputs == ()


def test_q4_of_the_flow_follows_the_year_and_is_an_inferred_zero() -> None:
    cells = run(rows(), frozenset())

    q4 = cells[("net_income_nci", "FY2023Q4")]
    assert q4.value == Decimal(0)
    assert q4.provenance == "zero_inferred"


def test_a_balance_sheet_gets_an_inferred_zero_nci_in_every_period_q4_copying_the_year() -> None:
    cells = run(rows(), frozenset())

    for period in ("FY2023", "FY2023Q1", "FY2023Q3", "FY2023Q4"):
        cell = cells[("nci", period)]
        assert (cell.value, cell.provenance) == (Decimal(0), "zero_inferred")
    assert cells[("nci", "FY2023Q4")] == cells[("nci", "FY2023")]
    assert cells[("nci", "FY2023")].derivation is not None
    assert "10-K K-2023" in cells[("nci", "FY2023")].derivation.formula  # type: ignore[union-attr]


def test_a_tagged_filing_switches_the_rule_off_for_its_periods_only() -> None:
    cells = run(rows(), frozenset({"K-2023"}))

    assert cells[("net_income_nci", "FY2023")].value is None
    assert cells[("nci", "FY2023")].value is None
    # the 10-Qs of the year tag nothing, so their quarters still infer a zero
    assert cells[("net_income_nci", "FY2023Q1")].provenance == "zero_inferred"
    # Q4 follows the year, which is empty
    assert cells[("net_income_nci", "FY2023Q4")].value is None


def test_the_rule_is_off_without_a_filing_list() -> None:
    cells = run(rows(), None)

    assert cells[("net_income_nci", "FY2023")].value is None
    assert cells[("nci", "FY2023")].value is None


def test_a_reported_nci_is_never_replaced() -> None:
    cells = run(rows(with_nci=True), frozenset())

    assert cells[("net_income_nci", "FY2023")].value == 4 * B
    assert cells[("net_income_nci", "FY2023")].provenance == "reported"
    assert cells[("nci", "FY2023")].provenance == "reported"


def test_the_inferred_zero_completes_the_formulas_that_were_waiting_for_it() -> None:
    cells = run(rows(), frozenset())

    common = cells[("net_income_common", "FY2023")]
    assert common.value == 46 * B
    assert common.provenance == "derived"
    equity = cells[("total_equity", "FY2023")]
    assert equity.value == 80 * B
    assert equity.provenance == "derived"
    assert cells[("net_income_common", "FY2023Q4")].value == 13 * B


def test_a_period_whose_statement_has_no_source_is_left_alone() -> None:
    # the Q2 10-Q reports nothing, so no filing carries the statement for that quarter
    cells = run(
        [
            *flow_facts("Revenues", {2023: (B,) * 4}),
            *flow_facts("ProfitLoss", {2023: (B,) * 4}, skip=frozenset({(2023, 2)})),
        ],
        frozenset(),
    )

    assert cells[("net_income_nci", "FY2023Q2")].value is None
    assert cells[("net_income_nci", "FY2023Q1")].provenance == "zero_inferred"


def test_a_ttm_of_four_inferred_zeros_is_an_inferred_zero_and_any_other_mix_is_derived() -> None:
    raw = [
        *flow_facts("Revenues", {2022: (B,) * 4, 2023: (B,) * 4}),
        *flow_facts("ProfitLoss", {2022: (B,) * 4, 2023: (B,) * 4}),
        *flow_facts("NetIncomeNci", {2023: (B, B, B, B)}),  # reported in FY2023 only
    ]
    canonical = map_facts(select_vintage(facts(raw)), MAPS, ITEMS)  # type: ignore[arg-type]

    table = build_statement(canonical, ITEMS, "IS", "ttm", rules=Rules((), frozenset()))

    (row,) = [r for r in table.rows if r.code == "net_income_nci"]
    by_period = dict(
        zip(
            [p.key for p in table.periods],
            zip(row.values, row.provenance, strict=True),
            strict=True,
        )
    )
    assert by_period["TTM-FY2022Q4"] == (0, "zero_inferred")
    assert by_period["TTM-FY2023Q1"] == (B, "derived")  # three inferred zeros and a reported B
    assert by_period["TTM-FY2023Q4"] == (4 * B, "derived")
