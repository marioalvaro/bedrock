"""Imported values in the cell engine: they fill only the cells SEC leaves empty (erd/data.md,
"Precedence (fill gaps only)")."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import IdentityDef, SolveRule, parse_formula
from bedrock.mapping.mapper import CANONICAL_COLUMNS, map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import build_statement
from bedrock.statements.cell_types import IMPORT_PREFIX
from bedrock.statements.cells import SolvedCells, solve_cells
from bedrock.statements.explain import explain_cell
from bedrock.statements.imports import StoredValue, company_calendar, imported_frames
from bedrock.statements.rules import Rules
from tests.engine_data import facts, flow_facts, fy_dates, instant_facts, item, mappings
from tests.statements_pipeline import solve_with_imports

AT = datetime(2026, 10, 26, 9, 0)
B = 1_000_000_000

# --- FictCo: SEC revenue and cash give the calendar; the imports bring the rest ----------------

ITEMS = [
    item("revenue", concepts=["us-gaap:Revenues"]),
    item("cost_of_revenue", concepts=["us-gaap:CostOfRevenue"]),
    item(
        "gross_profit",
        derive="revenue - cost_of_revenue",
        concepts=["us-gaap:GrossProfit"],
    ),
    item("cash", "BS", kind="instant", concepts=["us-gaap:Cash"]),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("cost_of_revenue", "CostOfRevenue", 0),
    ("gross_profit", "GrossProfit", 0),
    ("cash", "Cash", 0),
)


def quarter(fy: int, n: int) -> tuple[date, date]:
    start, end, q_ends = fy_dates(fy)
    ends = [*q_ends, end]
    return (start if n == 1 else ends[n - 2] + timedelta(days=1), ends[n - 1])


def stored(
    code: str, fy: int, period: str, value: int, *, import_id: int = 1, at: datetime = AT
) -> StoredValue:
    instant = ITEMS_BY_CODE[code].kind == "instant"
    if period == "FY":
        start, end, _ = fy_dates(fy)
    else:
        start, end = quarter(fy, int(period[1]))
    return StoredValue(
        import_id, f"import{import_id}.xlsx", at, code, fy, period, None if instant else start, end,
        Decimal(value) * B,
    )  # fmt: skip


ITEMS_BY_CODE = {i.code: i for i in ITEMS}


def sec_rows(revenue: dict[int, tuple[int, ...]] | None = None, cash: bool = True):  # type: ignore[no-untyped-def]
    years = revenue or {2023: (10, 10, 10, 10), 2024: (10, 10, 10, 10)}
    rows = flow_facts("Revenues", {fy: tuple(v * B for v in q) for fy, q in years.items()})
    if cash:
        rows += instant_facts("Cash", {fy: (1 * B,) * 4 for fy in years})
    return rows


def run(
    rows,  # type: ignore[no-untyped-def]
    values: list[StoredValue],
    identities: tuple[IdentityDef, ...] = (),
) -> tuple[SolvedCells, list]:  # type: ignore[type-arg]
    canonical = map_facts(select_vintage(facts(rows)), MAPS, ITEMS)
    frames = imported_frames(values, ITEMS)
    rules = Rules(identities, imported=frames.newest, imported_vintages=frames.vintages)
    calendar = company_calendar(canonical, rules.imported)
    return solve_cells(canonical, ITEMS, calendar, rules), list(calendar.years)


def test_an_imported_value_fills_an_empty_cell_and_says_where_it_came_from() -> None:
    solved, _ = run(sec_rows(), [stored("cost_of_revenue", 2024, "FY", 4)])

    cell = solved.cells[("cost_of_revenue", "FY2024")]
    assert (cell.value, cell.provenance) == (Decimal(4 * B), "imported")
    assert cell.source is not None
    assert (cell.source.accession_no, cell.source.form) == (f"{IMPORT_PREFIX}1", "import")
    assert cell.source.filed_at == AT.date()


def test_an_imported_value_never_replaces_a_sec_value() -> None:
    solved, _ = run(sec_rows(), [stored("revenue", 2024, "FY", 999)])

    cell = solved.cells[("revenue", "FY2024")]
    assert (cell.value, cell.provenance) == (Decimal(40 * B), "reported")


def test_a_later_sec_value_takes_over_the_cell() -> None:
    values = [stored("cost_of_revenue", 2024, "FY", 4)]
    without, _ = run(sec_rows(), values)
    with_sec, _ = run(sec_rows() + flow_facts("CostOfRevenue", {2024: (B, B, B, B)}), values)

    assert without.cells[("cost_of_revenue", "FY2024")].provenance == "imported"
    assert with_sec.cells[("cost_of_revenue", "FY2024")].provenance == "reported"
    assert with_sec.cells[("cost_of_revenue", "FY2024")].value == Decimal(4 * B)


def test_the_newest_import_wins_per_cell_and_both_stay_as_vintages() -> None:
    old = stored("cost_of_revenue", 2024, "FY", 4, import_id=1)
    new = stored("cost_of_revenue", 2024, "FY", 5, import_id=2, at=datetime(2026, 10, 27))

    solved, _ = run(sec_rows(), [old, new])
    frames = imported_frames([old, new], ITEMS)

    assert solved.cells[("cost_of_revenue", "FY2024")].value == Decimal(5 * B)
    assert list(frames.vintages["accession_no"]) == ["import:1", "import:2"]


def test_imported_fy_and_q1_to_q3_give_q4_as_the_remainder() -> None:
    values = [
        stored("cost_of_revenue", 2024, "FY", 40),
        stored("cost_of_revenue", 2024, "Q1", 9),
        stored("cost_of_revenue", 2024, "Q2", 10),
        stored("cost_of_revenue", 2024, "Q3", 11),
    ]

    solved, _ = run(sec_rows(), values)

    q4 = solved.cells[("cost_of_revenue", "FY2024Q4")]
    assert (q4.value, q4.provenance) == (Decimal(10 * B), "derived")
    assert q4.derivation is not None and q4.derivation.formula == "FY - Q1 - Q2 - Q3"


def test_imported_quarters_without_a_year_give_the_year_as_their_sum() -> None:
    values = [stored("cost_of_revenue", 2024, f"Q{n}", 10 + n) for n in (1, 2, 3, 4)]

    solved, _ = run(sec_rows(), values)

    fy = solved.cells[("cost_of_revenue", "FY2024")]
    assert (fy.value, fy.provenance) == (Decimal((11 + 12 + 13 + 14) * B), "derived")
    assert fy.derivation is not None and fy.derivation.formula == "Q1 + Q2 + Q3 + Q4"
    assert solved.cells[("cost_of_revenue", "FY2024Q4")].value == Decimal(14 * B)


def test_an_imported_q4_that_disagrees_with_the_year_is_ignored_with_a_warning() -> None:
    values = [
        stored("cost_of_revenue", 2024, "FY", 40),
        stored("cost_of_revenue", 2024, "Q1", 9),
        stored("cost_of_revenue", 2024, "Q2", 10),
        stored("cost_of_revenue", 2024, "Q3", 11),
        stored("cost_of_revenue", 2024, "Q4", 15),
    ]

    solved, _ = run(sec_rows(), values)

    assert solved.cells[("cost_of_revenue", "FY2024Q4")].value == Decimal(10 * B)
    (warning,) = [w for w in solved.warnings if w.rule == "import_q4"]
    assert (warning.code, warning.period_key, warning.value) == (
        "cost_of_revenue",
        "FY2024Q4",
        Decimal(15 * B),
    )


def test_an_imported_instant_fills_a_quarter_and_q4_follows_the_year_end() -> None:
    values = [stored("cash", 2022, "FY", 3), stored("cash", 2024, "Q2", 7)]
    rows = sec_rows(cash=False)

    solved, _ = run(rows, values)

    assert solved.cells[("cash", "FY2024Q2")].value == Decimal(7 * B)
    assert solved.cells[("cash", "FY2024Q4")].value is None  # nothing at the 2024 year end


def test_an_imported_year_end_balance_is_also_the_fourth_quarter() -> None:
    solved, _ = run(sec_rows(cash=False), [stored("cash", 2024, "FY", 3)])

    assert solved.cells[("cash", "FY2024Q4")].value == Decimal(3 * B)
    assert solved.cells[("cash", "FY2024Q4")].provenance == "imported"


def test_a_line_with_a_formula_takes_the_import_only_when_the_formula_cannot_run() -> None:
    values = [
        stored("gross_profit", 2024, "FY", 99),  # revenue - cost_of_revenue is computable: ignored
        stored("cost_of_revenue", 2024, "FY", 4),
        stored("gross_profit", 2023, "FY", 7),  # no cost of revenue in 2023: the import is used
    ]

    solved, _ = run(sec_rows(), values)

    derived = solved.cells[("gross_profit", "FY2024")]
    assert (derived.value, derived.provenance) == (Decimal(36 * B), "derived")
    typed = solved.cells[("gross_profit", "FY2023")]
    assert (typed.value, typed.provenance) == (Decimal(7 * B), "imported")


def test_a_pre_sec_year_joins_the_calendar_with_the_files_dates() -> None:
    values = [stored("cost_of_revenue", 2022, "FY", 4)]

    solved, years = run(sec_rows(), values)

    assert [y.fiscal_year for y in years] == [2022, 2023, 2024]
    assert solved.cells[("cost_of_revenue", "FY2022")].provenance == "imported"


def test_without_sec_data_the_calendar_comes_from_the_imports_alone() -> None:
    values = [stored("cost_of_revenue", 2024, "FY", 4), stored("cost_of_revenue", 2024, "Q1", 1)]

    canonical = pd.DataFrame(columns=CANONICAL_COLUMNS)
    frames = imported_frames(values, ITEMS)
    calendar = company_calendar(canonical, frames.newest)

    assert [y.fiscal_year for y in calendar.years] == [2024]
    assert calendar.years[0].start == date(2023, 7, 1)


def test_an_import_inside_the_sec_years_adds_no_calendar_year() -> None:
    odd = StoredValue(
        1,
        "a.xlsx",
        AT,
        "cost_of_revenue",
        2023,
        "FY",
        date(2022, 7, 3),
        date(2023, 7, 2),
        Decimal(1),
    )

    _, years = run(sec_rows(), [odd])

    assert [y.fiscal_year for y in years] == [2023, 2024]


GP = IdentityDef(
    "gp",
    "gross_profit = revenue - cost_of_revenue",
    (
        *parse_formula("gross_profit"),
        *((-s, c) for s, c in parse_formula("revenue - cost_of_revenue")),
    ),
    {"cost_of_revenue": SolveRule("exact", None)},
)


def test_sec_and_imported_operands_never_solve_an_identity_together() -> None:
    rows = sec_rows() + flow_facts("GrossProfit", {2024: (B, B, B, B)})
    solved, _ = run(rows, [], (GP,))
    assert solved.cells[("cost_of_revenue", "FY2024")].value == Decimal(36 * B)  # all SEC: solved

    canonical_rows = sec_rows()  # revenue is SEC, gross profit only imported
    solved, _ = run(canonical_rows, [stored("gross_profit", 2023, "FY", 7)], (GP,))

    assert solved.cells[("cost_of_revenue", "FY2023")].value is None
    assert any("import:1" in w.reason for w in solved.warnings if w.rule == "gp")


# --- AAPL: the real pipeline ---------------------------------------------------------------


def aapl(code: str, fy: int, value: int, end: date, start: date | None, period: str = "FY"):  # type: ignore[no-untyped-def]
    return StoredValue(1, "aapl.xlsx", AT, code, fy, period, start, end, Decimal(value))


FY2008 = (date(2007, 9, 30), date(2008, 9, 27))
FY2006 = (date(2005, 9, 25), date(2006, 9, 30))


def test_aapl_interest_expense_fy2008_is_filled_and_the_rest_is_untouched() -> None:
    plain = solve_with_imports("AAPL", [])[0]
    solved, _ = solve_with_imports(
        "AAPL", [aapl("interest_expense", 2008, 0, FY2008[1], FY2008[0])]
    )

    assert plain.cells[("interest_expense", "FY2008")].value is None
    assert solved.cells[("interest_expense", "FY2008")].provenance == "imported"
    changed = {key for key, cell in solved.cells.items() if plain.cells[key].value != cell.value}
    assert ("interest_expense", "FY2008") in changed
    assert all(plain.cells[key].value is None for key in changed)  # only gaps fill


def test_aapl_revenue_that_sec_has_is_ignored() -> None:
    plain = solve_with_imports("AAPL", [])[0]
    solved, _ = solve_with_imports("AAPL", [aapl("revenue", 2008, 1, FY2008[1], FY2008[0])])

    assert solved.cells[("revenue", "FY2008")] == plain.cells[("revenue", "FY2008")]


def test_aapl_pre_sec_year_joins_the_calendar_and_gets_no_nci_zero() -> None:
    solved, calendar = solve_with_imports(
        "AAPL",
        [aapl("net_income", 2006, 2_000, FY2006[1], FY2006[0])],
    )

    assert 2006 in [y.fiscal_year for y in calendar.years]
    assert solved.cells[("net_income", "FY2006")].provenance == "imported"
    assert solved.cells[("net_income_nci", "FY2006")].value is None  # R1b needs filing tags
    assert solved.cells[("net_income_nci", "FY2008")].provenance == "zero_inferred"  # SEC year


def test_aapl_mixed_imported_and_sec_operands_do_not_solve_the_cash_rollforward() -> None:
    end = date(2012, 9, 29)
    cfo = solve_with_imports("AAPL", [])[0].cells[("cfo", "FY2012")].value
    assert cfo is not None
    solved, _ = solve_with_imports(
        "AAPL",
        [aapl("cfo", 2012, int(cfo), end, date(2011, 9, 25))],
        drop=frozenset({("cfo", end.isoformat())}),
    )

    assert solved.cells[("cfo", "FY2012")].provenance == "imported"
    assert solved.cells[("fx_effect", "FY2012")].value is None
    assert any(
        w.rule == "cash_rollforward" and w.value is None and "import:1" in w.reason
        for w in solved.warnings
    )


def test_cell_details_list_every_import_vintage_of_an_imported_cell() -> None:
    old = stored("cost_of_revenue", 2024, "FY", 4, import_id=1)
    new = stored("cost_of_revenue", 2024, "FY", 5, import_id=2, at=datetime(2026, 10, 27))
    canonical = map_facts(select_vintage(facts(sec_rows())), MAPS, ITEMS)
    frames = imported_frames([old, new], ITEMS)
    rules = Rules(imported=frames.newest, imported_vintages=frames.vintages)

    detail = explain_cell(
        canonical, facts(sec_rows()), ITEMS, "cost_of_revenue", 2024, "FY", (), rules
    )

    assert (detail.value, detail.provenance) == (Decimal(5 * B), "imported")
    assert detail.source is not None and detail.source.taxonomy == "import"
    assert detail.filing is not None and detail.filing.accession_no == "import:2"
    assert [(v.accession_no, v.value) for v in detail.vintages] == [
        ("import:1", Decimal(4 * B)),
        ("import:2", Decimal(5 * B)),
    ]


def test_cell_details_of_a_pre_sec_period_exist() -> None:
    canonical = map_facts(select_vintage(facts(sec_rows())), MAPS, ITEMS)
    frames = imported_frames([stored("cost_of_revenue", 2022, "FY", 4)], ITEMS)
    rules = Rules(imported=frames.newest, imported_vintages=frames.vintages)

    detail = explain_cell(
        canonical, facts(sec_rows()), ITEMS, "cost_of_revenue", 2022, "FY", (), rules
    )

    assert detail.value == Decimal(4 * B)


def test_a_statement_table_shows_the_imported_year_and_its_provenance() -> None:
    canonical = map_facts(select_vintage(facts(sec_rows())), MAPS, ITEMS)
    frames = imported_frames([stored("cost_of_revenue", 2022, "FY", 4)], ITEMS)
    rules = Rules(imported=frames.newest, imported_vintages=frames.vintages)

    table = build_statement(canonical, ITEMS, "IS", "annual", rules=rules)

    assert [p.key for p in table.periods] == ["FY2022", "FY2023", "FY2024"]
    row = next(r for r in table.rows if r.code == "cost_of_revenue")
    assert (row.values[0], row.provenance[0]) == (Decimal(4 * B), "imported")


def test_imported_discrete_quarters_give_the_quarters_of_a_pre_sec_year() -> None:
    values = [stored("cost_of_revenue", 2022, "FY", 40)] + [
        stored("cost_of_revenue", 2022, f"Q{n}", 10) for n in (1, 2, 3)
    ]

    solved, years = run(sec_rows(), values)

    first = years[0]
    assert (first.fiscal_year, len(first.quarter_ends)) == (2022, 3)
    assert solved.cells[("cost_of_revenue", "FY2022Q2")].value == Decimal(10 * B)
    assert solved.cells[("cost_of_revenue", "FY2022Q4")].value == Decimal(10 * B)


def test_a_pre_sec_year_given_only_as_four_quarters_gets_its_year() -> None:
    values = [stored("cost_of_revenue", 2022, f"Q{n}", 10) for n in (1, 2, 3, 4)]

    solved, years = run(sec_rows(), values)

    assert years[0].fiscal_year == 2022
    assert solved.cells[("cost_of_revenue", "FY2022")].value == Decimal(40 * B)
