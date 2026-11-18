"""The structure rules R8 (face sum) and R9 (face zero) of docs/erd/data-coverage.md "Structure
rules", on synthetic frames: a fictional June-year company, its 10-K and 10-Q face lines."""

import random
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import build_statement
from bedrock.statements.cells import Cell, solve_cells
from bedrock.statements.explain import explain_cell
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.rules import Rules
from bedrock.statements.structure import LINE_COLUMNS, FaceLines
from tests.engine_data import Row, facts, flow_facts, instant_facts, item, mappings

B = 1_000_000_000
FY = 2023


def bs(code: str, parent: str | None = None, **kw: object) -> CanonicalItemDef:
    return item(code, "BS", kind="instant", parent=parent, **kw)  # type: ignore[arg-type]


ITEMS: list[CanonicalItemDef] = [
    item("revenue"),
    item("net_income"),
    item("rnd", parent="net_income"),
    bs("total_assets"),
    bs("total_current_liabilities"),
    bs("accounts_payable", "total_current_liabilities"),
    replace(
        bs("short_term_debt", "total_current_liabilities"),
        face_members=(
            "us-gaap:CommercialPaper",
            "us-gaap:LongTermDebtCurrent",
            "us-gaap:ShortTermBorrowings",
        ),
    ),
    bs("accrued_liabilities", "total_current_liabilities"),
    bs(
        "other_current_liabilities",
        "total_current_liabilities",
        residual=True,
        derive="total_current_liabilities - accounts_payable - short_term_debt - "
        "accrued_liabilities",
    ),
    item("cfo", "CF"),
    item("dividends_paid", "CF", parent="cfo", sign=-1),
    item("dividends_per_share", unit="USD/shares"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("net_income", "NetIncomeLoss", 0),
    ("rnd", "ResearchAndDevelopmentExpense", 0),
    ("total_assets", "Assets", 0),
    ("total_current_liabilities", "LiabilitiesCurrent", 0),
    ("accounts_payable", "AccountsPayableCurrent", 0),
    ("short_term_debt", "DebtCurrent", 0),
    ("accrued_liabilities", "AccruedLiabilitiesCurrent", 0),
    ("cfo", "NetCashProvidedByUsedInOperatingActivities", 0),
    ("dividends_paid", "PaymentsOfDividends", 0),
    ("dividends_per_share", "CommonStockDividendsPerShareDeclared", 0),
)


def line(
    accession: str,
    statement: str,
    concept: str,
    parent: str | None = None,
    *,
    form: str = "10-K",
) -> Row:
    taxonomy, _, name = concept.rpartition(":")
    parent_taxonomy, _, parent_name = (parent or "").rpartition(":")
    return {
        "accession_no": accession,
        "form": form,
        "filed_at": date(2023, 8, 30),
        "statement": statement,
        "position": 0,
        "taxonomy": taxonomy or "us-gaap",
        "concept": name,
        "label": name,
        "calc_parent_taxonomy": (parent_taxonomy or "us-gaap") if parent else None,
        "calc_parent_concept": parent_name if parent else None,
        "calc_weight": Decimal(1) if parent else None,
    }


def lines_frame(rows: Iterable[Row]) -> pd.DataFrame:
    out = []
    for at, row in enumerate(rows, start=1):
        out.append({**row, "position": at})
    return pd.DataFrame(out, columns=LINE_COLUMNS).astype({"calc_weight": "object"})


def balance_sheet_lines(accession: str = f"K-{FY}", form: str = "10-K", *extra: Row) -> list[Row]:
    """A face with assets, current liabilities and their parts (no accrued-liabilities line)."""
    return [
        line(accession, "BS", "Assets", form=form),
        line(accession, "BS", "AccountsPayableCurrent", "LiabilitiesCurrent", form=form),
        line(accession, "BS", "CommercialPaper", "LiabilitiesCurrent", form=form),
        line(accession, "BS", "LongTermDebtCurrent", "LiabilitiesCurrent", form=form),
        line(accession, "BS", "LiabilitiesCurrent", "LiabilitiesAndStockholdersEquity", form=form),
        *extra,
    ]


def base_facts() -> list[Row]:
    return [
        *flow_facts("Revenues", {FY: (B, B, B, B)}),
        *flow_facts("NetIncomeLoss", {FY: (B, B, B, B)}),
        *flow_facts("NetCashProvidedByUsedInOperatingActivities", {FY: (B, B, B, B)}),
        *instant_facts("Assets", {FY: (90 * B, 90 * B, 90 * B, 100 * B)}),
        *instant_facts("LiabilitiesCurrent", {FY: (40 * B, 40 * B, 40 * B, 50 * B)}),
        *instant_facts("AccountsPayableCurrent", {FY: (10 * B, 10 * B, 10 * B, 20 * B)}),
    ]


def debt_facts(**values: int) -> list[Row]:
    """Year-end balances of debt lines, all from the 10-K."""
    out: list[Row] = []
    for concept, value in values.items():
        out += [r for r in instant_facts(concept, {FY: (1, 1, 1, value)}) if r["form"] == "10-K"]
    return out


def solve(
    raw: Sequence[Row],
    lines: Sequence[Row] | None,
    *,
    items: Sequence[CanonicalItemDef] = ITEMS,
    maps: pd.DataFrame = MAPS,
    line_facts: Sequence[Row] | None = None,
    verdicts: dict[tuple[str, str], tuple[str, ...]] | None = None,
    other_lines: frozenset[tuple[str, str]] = frozenset(),
    classified: dict[tuple[str, str], tuple[str, ...]] | None = None,
) -> dict[tuple[str, str], Cell]:
    frame = facts(raw)
    canonical = map_facts(select_vintage(frame), maps, list(items))
    face = (
        None
        if lines is None
        else FaceLines(
            lines_frame(lines),
            facts(raw if line_facts is None else line_facts),
            maps,
            verdicts or {},
            other_lines,
            classified or {},
        )
    )
    rules = Rules(filing_lines=face)
    return solve_cells(canonical, list(items), fiscal_calendar(canonical), rules).cells


# --- R8: face sum -------------------------------------------------------------------------


def test_a_face_sum_of_two_members_fills_the_empty_line() -> None:
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]

    cell = solve(raw, balance_sheet_lines())[("short_term_debt", f"FY{FY}")]

    assert cell.value == 5 * B
    assert cell.provenance == "derived"
    assert cell.derivation is not None
    assert cell.derivation.formula == (
        f"face lines of 10-K K-{FY}: us-gaap:CommercialPaper + us-gaap:LongTermDebtCurrent"
    )
    assert [i.value for i in cell.derivation.inputs] == [3 * B, 2 * B]


def test_the_sum_takes_the_item_sign() -> None:
    items = [replace(i, sign=-1) if i.code == "short_term_debt" else i for i in ITEMS]
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]

    cells = solve(raw, balance_sheet_lines(), items=items)

    assert cells[("short_term_debt", f"FY{FY}")].value == -5 * B


def test_a_member_whose_calculation_ancestor_is_a_member_too_is_dropped() -> None:
    lines = [
        line(f"K-{FY}", "BS", "Assets"),
        line(f"K-{FY}", "BS", "CommercialPaper", "ShortTermBorrowings"),
        line(f"K-{FY}", "BS", "ShortTermBorrowings", "LiabilitiesCurrent"),
        line(f"K-{FY}", "BS", "LiabilitiesCurrent"),
    ]
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, ShortTermBorrowings=4 * B)]

    cell = solve(raw, lines)[("short_term_debt", f"FY{FY}")]

    assert cell.value == 4 * B  # the commercial paper is inside the borrowings line


def test_a_member_without_a_fact_for_the_period_blocks_the_sum() -> None:
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B)]  # no current portion fact

    cell = solve(raw, balance_sheet_lines())[("short_term_debt", f"FY{FY}")]

    assert cell.value is None


def test_a_fact_of_another_filing_does_not_count_for_the_face_sum() -> None:
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]
    later = [
        {**r, "accession_no": "K-2024"} if r["concept"] == "CommercialPaper" else r for r in raw
    ]

    cell = solve(raw, balance_sheet_lines(), line_facts=later)[("short_term_debt", f"FY{FY}")]

    assert cell.value is None


def test_no_face_sum_without_a_member_on_the_face() -> None:
    lines = [line(f"K-{FY}", "BS", "Assets"), line(f"K-{FY}", "BS", "LiabilitiesCurrent")]

    cell = solve(base_facts(), lines)[("short_term_debt", f"FY{FY}")]

    assert cell.provenance == "zero_inferred"  # no member: R9's zero, not a sum


def test_a_mapped_value_is_never_replaced_by_the_face_sum() -> None:
    raw = [
        *base_facts(),
        *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B, DebtCurrent=7 * B),
    ]

    cell = solve(raw, balance_sheet_lines())[("short_term_debt", f"FY{FY}")]

    assert (cell.value, cell.provenance) == (7 * B, "reported")


def test_an_override_mapped_extension_line_is_a_member() -> None:
    maps = pd.concat([MAPS, mappings(("short_term_debt", "x:ShortDebt", 0, True))])
    lines = balance_sheet_lines(f"K-{FY}", "10-K")
    lines[2] = line(f"K-{FY}", "BS", "x:ShortDebt", "LiabilitiesCurrent")
    raw = [*base_facts(), *debt_facts(LongTermDebtCurrent=2 * B)]
    line_facts = [
        *raw,
        *[{**r, "taxonomy": "x"} for r in debt_facts(ShortDebt=3 * B)],
    ]  # the extension fact is a face fact only: the mapped value does not exist

    cell = solve(raw, lines, maps=maps, line_facts=line_facts)[("short_term_debt", f"FY{FY}")]

    assert cell.value == 5 * B


# --- unclassified lines --------------------------------------------------------------------


def test_an_unclassified_line_in_the_block_blocks_the_sum_and_the_zero() -> None:
    weird = line(f"K-{FY}", "BS", "x:Weird", "LiabilitiesCurrent")
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]
    with_weird = [*raw, *[{**r, "taxonomy": "x"} for r in debt_facts(Weird=B)]]

    cells = solve(raw, balance_sheet_lines(f"K-{FY}", "10-K", weird), line_facts=with_weird)

    debt = cells[("short_term_debt", f"FY{FY}")]
    accrued = cells[("accrued_liabilities", f"FY{FY}")]
    assert (debt.value, accrued.value) == (None, None)
    assert debt.unclassified == ("x:Weird",)
    assert accrued.unclassified == ("x:Weird",)


def test_an_unclassified_line_without_an_amount_blocks_nothing() -> None:
    weird = line(f"K-{FY}", "BS", "x:Weird", "LiabilitiesCurrent")  # no fact (a nil line)
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]

    cells = solve(raw, balance_sheet_lines(f"K-{FY}", "10-K", weird))

    assert cells[("short_term_debt", f"FY{FY}")].value == 5 * B
    assert cells[("accrued_liabilities", f"FY{FY}")].value == 0


def test_an_unclassified_line_in_another_block_blocks_nothing() -> None:
    weird = line(f"K-{FY}", "BS", "x:Weird", "AssetsCurrent")
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]
    with_weird = [*raw, *[{**r, "taxonomy": "x"} for r in debt_facts(Weird=B)]]

    cells = solve(raw, balance_sheet_lines(f"K-{FY}", "10-K", weird), line_facts=with_weird)

    assert cells[("short_term_debt", f"FY{FY}")].value == 5 * B
    assert cells[("accrued_liabilities", f"FY{FY}")].value == 0


def test_without_the_parent_line_the_block_is_the_whole_statement() -> None:
    lines = [
        line(f"K-{FY}", "BS", "Assets"),
        line(f"K-{FY}", "BS", "x:Weird", "Assets"),
        line(f"K-{FY}", "BS", "CommercialPaper"),
        line(f"K-{FY}", "BS", "LongTermDebtCurrent"),
    ]  # an unclassified sheet: no current-liabilities total on the face
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]
    with_weird = [*raw, *[{**r, "taxonomy": "x"} for r in debt_facts(Weird=B)]]

    cell = solve(raw, lines, line_facts=with_weird)[("short_term_debt", f"FY{FY}")]

    assert cell.value is None
    assert cell.unclassified == ("x:Weird",)


def test_other_lines_and_triage_verdicts_classify_a_line() -> None:
    weird = line(f"K-{FY}", "BS", "x:Weird", "LiabilitiesCurrent")
    odd = line(f"K-{FY}", "BS", "OtherLiabilitiesCurrent", "LiabilitiesCurrent")
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]
    extra = [
        *[{**r, "taxonomy": "x"} for r in debt_facts(Weird=B)],
        *debt_facts(OtherLiabilitiesCurrent=B),
    ]

    cells = solve(
        raw,
        balance_sheet_lines(f"K-{FY}", "10-K", weird, odd),
        line_facts=[*raw, *extra],
        verdicts={("us-gaap", "OtherLiabilitiesCurrent"): ("other_current_liabilities",)},
        other_lines=frozenset({("x", "Weird")}),
    )

    assert cells[("short_term_debt", f"FY{FY}")].value == 5 * B
    assert cells[("accrued_liabilities", f"FY{FY}")].value == 0


# --- R9: face zero --------------------------------------------------------------------------


def test_a_line_absent_from_the_10k_face_is_an_inferred_zero() -> None:
    cell = solve(base_facts(), balance_sheet_lines())[("accrued_liabilities", f"FY{FY}")]

    assert (cell.value, cell.provenance) == (Decimal(0), "zero_inferred")
    assert cell.derivation is not None
    assert cell.derivation.formula == (
        f"no Accrued liabilities line on the balance sheet of 10-K K-{FY}"
    )
    assert cell.derivation.inputs == ()


def test_a_verdict_or_a_combined_line_naming_the_item_blocks_its_zero() -> None:
    odd = line(f"K-{FY}", "BS", "EmployeeRelatedLiabilitiesCurrent", "LiabilitiesCurrent")
    raw = [*base_facts(), *debt_facts(EmployeeRelatedLiabilitiesCurrent=B)]
    by_verdict = solve(
        raw,
        balance_sheet_lines(f"K-{FY}", "10-K", odd),
        verdicts={("us-gaap", "EmployeeRelatedLiabilitiesCurrent"): ("accrued_liabilities",)},
    )
    combined = pd.concat(
        [
            MAPS,
            mappings(
                (
                    "accounts_payable",
                    "AccountsPayableAndAccruedLiabilitiesCurrent",
                    1,
                    False,
                    "accrued_liabilities",
                )
            ),
        ]
    )
    carrier = line(
        f"K-{FY}", "BS", "AccountsPayableAndAccruedLiabilitiesCurrent", "LiabilitiesCurrent"
    )
    by_cover = solve(base_facts(), balance_sheet_lines(f"K-{FY}", "10-K", carrier), maps=combined)

    assert by_verdict[("accrued_liabilities", f"FY{FY}")].value is None
    assert by_cover[("accrued_liabilities", f"FY{FY}")].value is None


def test_zero_when_absent_false_opts_the_item_out() -> None:
    items = [
        replace(i, zero_when_absent=False) if i.code == "accrued_liabilities" else i for i in ITEMS
    ]

    cells = solve(base_facts(), balance_sheet_lines(), items=items)

    assert cells[("accrued_liabilities", f"FY{FY}")].value is None


def test_a_line_without_a_parent_or_a_subtotal_is_never_inferred_zero() -> None:
    cells = solve(base_facts(), balance_sheet_lines())

    assert cells[("total_current_liabilities", f"FY{FY}")].value == 50 * B  # reported
    assert cells[("revenue", f"FY{FY}Q1")].provenance == "reported"
    lines = [line(f"K-{FY}", "IS", "NetIncomeLoss")]
    no_revenue = [r for r in base_facts() if r["concept"] != "Revenues"]
    assert solve(no_revenue, lines)[("revenue", f"FY{FY}")].value is None  # no parent: not eligible


def test_the_anchor_filing_not_parsed_means_no_rule() -> None:
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]

    cells = solve(raw, balance_sheet_lines("K-2099"))  # lines of another filing only

    assert cells[("short_term_debt", f"FY{FY}")].value is None
    assert cells[("accrued_liabilities", f"FY{FY}")].value is None
    assert cells[("short_term_debt", f"FY{FY}")].unclassified is None


def test_without_filing_lines_no_structure_rule_runs() -> None:
    cells = solve(base_facts(), None)

    assert cells[("accrued_liabilities", f"FY{FY}")].value is None


def is_lines(accession: str, form: str, *, rnd: bool) -> list[Row]:
    out = [line(accession, "IS", "Revenues", "NetIncomeLoss", form=form)]
    if rnd:
        out.append(
            line(accession, "IS", "ResearchAndDevelopmentExpense", "NetIncomeLoss", form=form)
        )
    return [*out, line(accession, "IS", "NetIncomeLoss", form=form)]


def test_a_quarter_is_zero_only_when_its_10q_lacks_the_line_and_the_year_is_zero() -> None:
    year_lacks = [*is_lines(f"K-{FY}", "10-K", rnd=False), *is_lines(f"Q1-{FY}", "10-Q", rnd=False)]
    year_has = [*is_lines(f"K-{FY}", "10-K", rnd=True), *is_lines(f"Q1-{FY}", "10-Q", rnd=False)]
    rnd_in_year = [
        r
        for r in flow_facts("ResearchAndDevelopmentExpense", {FY: (0, 0, 0, B)})
        if r["form"] == "10-K"
    ]

    zero = solve(base_facts(), year_lacks)
    kept = solve([*base_facts(), *rnd_in_year], year_has)

    assert zero[("rnd", f"FY{FY}Q1")].provenance == "zero_inferred"
    assert zero[("rnd", f"FY{FY}Q2")].value is None  # its 10-Q is not parsed
    assert kept[("rnd", f"FY{FY}")].value == B
    assert kept[("rnd", f"FY{FY}Q1")].value is None


def test_q4_of_a_zero_year_and_quarters_is_an_inferred_zero() -> None:
    lines = [*is_lines(f"K-{FY}", "10-K", rnd=False)] + [
        r for n in (1, 2, 3) for r in is_lines(f"Q{n}-{FY}", "10-Q", rnd=False)
    ]

    cells = solve(base_facts(), lines)

    q4 = cells[("rnd", f"FY{FY}Q4")]
    assert (q4.value, q4.provenance) == (Decimal(0), "zero_inferred")


def test_an_instant_quarter_needs_both_year_ends_around_it_to_be_zero() -> None:
    prior = [
        *instant_facts("Assets", {FY - 1: (1, 1, 1, 80 * B)}),
        *instant_facts("LiabilitiesCurrent", {FY - 1: (1, 1, 1, 30 * B)}),
    ]
    prior += flow_facts("Revenues", {FY - 1: (B, B, B, B)})
    prior += flow_facts("NetIncomeLoss", {FY - 1: (B, B, B, B)})
    raw = [*base_facts(), *[r for r in prior if r["form"] == "10-K"]]
    both_lack = [
        *balance_sheet_lines(f"K-{FY - 1}"),
        *balance_sheet_lines(f"K-{FY}"),
        *balance_sheet_lines(f"Q2-{FY}", "10-Q"),
    ]
    prior_has = [
        *balance_sheet_lines(
            f"K-{FY - 1}",
            "10-K",
            line(f"K-{FY - 1}", "BS", "AccruedLiabilitiesCurrent", "LiabilitiesCurrent"),
        ),
        *balance_sheet_lines(f"K-{FY}"),
        *balance_sheet_lines(f"Q2-{FY}", "10-Q"),
    ]
    accrued_prior = [
        r
        for r in instant_facts("AccruedLiabilitiesCurrent", {FY - 1: (1, 1, 1, B)})
        if r["form"] == "10-K"
    ]

    zero = solve(raw, both_lack)
    kept = solve([*raw, *accrued_prior], prior_has)

    assert zero[("accrued_liabilities", f"FY{FY}Q2")].provenance == "zero_inferred"
    assert kept[("accrued_liabilities", f"FY{FY}")].provenance == "zero_inferred"
    assert kept[("accrued_liabilities", f"FY{FY - 1}")].value == B
    assert kept[("accrued_liabilities", f"FY{FY}Q2")].value is None  # the year began with some


def test_dividends_per_share_is_zero_when_dividends_paid_is() -> None:
    lines = [
        line(f"K-{FY}", "CF", "NetIncomeLoss", "NetCashProvidedByUsedInOperatingActivities"),
        line(f"K-{FY}", "CF", "NetCashProvidedByUsedInOperatingActivities"),
    ]

    cells = solve(base_facts(), lines)

    assert cells[("dividends_paid", f"FY{FY}")].provenance == "zero_inferred"
    dps = cells[("dividends_per_share", f"FY{FY}")]
    assert (dps.value, dps.provenance) == (Decimal(0), "zero_inferred")
    assert dps.derivation is not None
    assert dps.derivation.formula == "dividends paid is 0 in the period"


def test_the_residual_still_foots_with_a_face_sum_and_a_zero() -> None:
    raw = [*base_facts(), *debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)]

    cells = solve(raw, balance_sheet_lines())

    other = cells[("other_current_liabilities", f"FY{FY}")].value
    assert other == 50 * B - 20 * B - 5 * B - 0


def test_a_face_sum_equals_the_sum_of_its_members() -> None:
    """A seeded property (hypothesis is not installed): random members and values."""
    rng = random.Random(7)
    names = ["CommercialPaper", "LongTermDebtCurrent", "ShortTermBorrowings"]
    for _ in range(25):
        concepts = rng.sample(names, rng.randint(1, 3))
        values = [rng.randint(-(10**12), 10**12) for _ in concepts]
        lines = [
            line(f"K-{FY}", "BS", "Assets"),
            *[line(f"K-{FY}", "BS", c, "LiabilitiesCurrent") for c in concepts],
            line(f"K-{FY}", "BS", "LiabilitiesCurrent"),
        ]
        raw = [*base_facts(), *debt_facts(**dict(zip(concepts, values, strict=True)))]

        cells = solve(raw, lines)

        assert cells[("short_term_debt", f"FY{FY}")].value == sum(values)
        other = cells[("other_current_liabilities", f"FY{FY}")].value
        assert other == 50 * B - 20 * B - sum(values) - 0  # components + residual = subtotal


def test_a_default_concepts_amount_in_the_filing_blocks_the_zero() -> None:
    """The filing tags the item's own concept with a value, off the face (in a note, or a default
    the company excludes as a different measure): the line is not provably 0."""
    items = [
        replace(i, concepts=("us-gaap:AccruedLiabilitiesCurrent",))
        if i.code == "accrued_liabilities"
        else i
        for i in ITEMS
    ]
    maps = MAPS[MAPS["canonical_code"] != "accrued_liabilities"]  # excluded by the company
    note = [
        r
        for r in instant_facts("AccruedLiabilitiesCurrent", {FY: (1, 1, 1, B)})
        if r["form"] == "10-K"
    ]

    cells = solve(
        base_facts(),
        balance_sheet_lines(),
        items=items,
        maps=maps,
        line_facts=[*base_facts(), *note],
    )

    assert cells[("accrued_liabilities", f"FY{FY}")].value is None


def test_a_combined_line_that_covers_no_row_blocks_the_zero_of_its_siblings() -> None:
    maps = pd.concat(
        [
            MAPS,
            mappings(
                ("accounts_payable", "AccountsPayableAndOtherLiabilitiesCurrent", 1, False, "")
            ),
        ]
    )
    carrier = line(
        f"K-{FY}", "BS", "AccountsPayableAndOtherLiabilitiesCurrent", "LiabilitiesCurrent"
    )
    raw = [*base_facts(), *debt_facts(AccountsPayableAndOtherLiabilitiesCurrent=B)]

    cells = solve(raw, balance_sheet_lines(f"K-{FY}", "10-K", carrier), maps=maps)

    assert cells[("accrued_liabilities", f"FY{FY}")].value is None


def test_an_item_whose_default_the_company_excludes_is_never_inferred_zero() -> None:
    """An exclude says the company's tag is a different measure (docs/erd/data.md "Canonical
    mapping file"): the line stays empty, as the override decided, rather than 0."""
    items = [
        replace(i, concepts=("us-gaap:AccruedLiabilitiesCurrent",))
        if i.code == "accrued_liabilities"
        else i
        for i in ITEMS
    ]
    maps = MAPS[MAPS["canonical_code"] != "accrued_liabilities"]  # the default is excluded

    cells = solve(base_facts(), balance_sheet_lines(), items=items, maps=maps)

    assert cells[("accrued_liabilities", f"FY{FY}")].value is None


# --- classified lines (M7d S4, docs/erd/face-tree.md "What a classification does") ----------

WEIRD = ("x", "Weird")


def weird_case(*extra: Row, debt: bool = True) -> tuple[list[Row], list[Row], list[Row]]:
    """The 10-K balance sheet with the unclassified `x:Weird` (1 B) under current liabilities;
    with `debt`, its commercial paper (3 B) and current portion of long-term debt (2 B)."""
    weird = line(f"K-{FY}", "BS", "x:Weird", "LiabilitiesCurrent")
    raw = [*base_facts()]
    if debt:
        raw += debt_facts(CommercialPaper=3 * B, LongTermDebtCurrent=2 * B)
    lines = balance_sheet_lines(f"K-{FY}", "10-K", weird, *extra)
    if not debt:
        lines = [
            ln for ln in lines if ln["concept"] not in ("CommercialPaper", "LongTermDebtCurrent")
        ]
    line_facts = [*raw, *[{**r, "taxonomy": "x"} for r in debt_facts(Weird=B)]]
    return raw, lines, line_facts


def test_a_line_classified_with_one_code_fills_the_empty_cell_by_r8_and_marks_it() -> None:
    raw, lines, line_facts = weird_case()

    cells = solve(raw, lines, line_facts=line_facts, classified={WEIRD: ("accrued_liabilities",)})

    accrued = cells[("accrued_liabilities", f"FY{FY}")]
    assert (accrued.value, accrued.provenance) == (B, "derived")  # the sum, not R9's zero
    assert accrued.classified_by == ("x:Weird",)
    assert accrued.unclassified is None
    debt = cells[("short_term_debt", f"FY{FY}")]
    assert (debt.value, debt.classified_by) == (5 * B, None)  # members by definition: no mark


def test_a_classified_member_beside_defined_members_marks_only_itself() -> None:
    raw, lines, line_facts = weird_case()

    cell = solve(raw, lines, line_facts=line_facts, classified={WEIRD: ("short_term_debt",)})[
        ("short_term_debt", f"FY{FY}")
    ]

    assert cell.value == 6 * B
    assert cell.classified_by == ("x:Weird",)


def test_a_line_classified_with_one_code_but_no_fact_blocks_the_zero_and_fills_nothing() -> None:
    raw, lines, _ = weird_case()
    # the line is on the face with an amount only for another period: no fact for the year-end
    other_year = [
        {**r, "taxonomy": "x", "period_end": date(FY - 1, 6, 30)} for r in debt_facts(Weird=B)
    ]

    cells = solve(
        raw,
        lines,
        line_facts=[*raw, *other_year],
        classified={WEIRD: ("accrued_liabilities",)},
    )

    assert cells[("accrued_liabilities", f"FY{FY}")].value is None


def test_a_line_classified_with_two_codes_blocks_the_zero_of_each_and_fills_nothing() -> None:
    raw, lines, line_facts = weird_case(debt=False)
    two = {WEIRD: ("accrued_liabilities", "short_term_debt")}

    cells = solve(raw, lines, line_facts=line_facts, classified=two)
    unclassified = solve(raw, lines, line_facts=line_facts)

    for code in ("accrued_liabilities", "short_term_debt"):
        cell = cells[(code, f"FY{FY}")]
        assert (cell.value, cell.unclassified, cell.classified_by) == (None, None, None)
        assert unclassified[(code, f"FY{FY}")].unclassified == ("x:Weird",)
    # the amount stays in the residual
    assert cells[("other_current_liabilities", f"FY{FY}")].value == 50 * B - 20 * B


def test_a_line_classified_with_no_code_only_unblocks_its_block() -> None:
    raw, lines, line_facts = weird_case()

    cells = solve(raw, lines, line_facts=line_facts, classified={WEIRD: ()})

    debt = cells[("short_term_debt", f"FY{FY}")]
    accrued = cells[("accrued_liabilities", f"FY{FY}")]
    assert (debt.value, debt.classified_by) == (5 * B, None)
    assert (accrued.value, accrued.provenance) == (Decimal(0), "zero_inferred")
    assert cells[("other_current_liabilities", f"FY{FY}")].value == 50 * B - 20 * B - 5 * B


def test_a_code_that_is_not_an_item_is_ignored() -> None:
    raw, lines, line_facts = weird_case()

    only_unknown = solve(raw, lines, line_facts=line_facts, classified={WEIRD: ("no_such_row",)})
    with_one = solve(
        raw,
        lines,
        line_facts=line_facts,
        classified={WEIRD: ("no_such_row", "accrued_liabilities")},
    )

    zero = only_unknown[("accrued_liabilities", f"FY{FY}")]
    assert (zero.value, zero.provenance) == (Decimal(0), "zero_inferred")  # as with no code
    assert with_one[("accrued_liabilities", f"FY{FY}")].value == B  # as with the one code


def test_a_classified_line_still_blocked_by_another_open_line_fills_nothing() -> None:
    other = line(f"K-{FY}", "BS", "x:Other", "LiabilitiesCurrent")
    raw, lines, line_facts = weird_case(other)
    line_facts += [{**r, "taxonomy": "x"} for r in debt_facts(Other=B)]

    cells = solve(raw, lines, line_facts=line_facts, classified={WEIRD: ("accrued_liabilities",)})

    accrued = cells[("accrued_liabilities", f"FY{FY}")]
    assert (accrued.value, accrued.classified_by) == (None, None)
    assert accrued.unclassified == ("x:Other",)


def test_a_classified_cell_lowers_the_residual_by_its_own_amount() -> None:
    raw, lines, line_facts = weird_case()

    before = solve(raw, lines, line_facts=line_facts, classified={WEIRD: ()})
    after = solve(raw, lines, line_facts=line_facts, classified={WEIRD: ("accrued_liabilities",)})

    key = ("other_current_liabilities", f"FY{FY}")
    total = ("total_current_liabilities", f"FY{FY}")
    assert before[key].value is not None and after[key].value is not None
    assert before[key].value - after[key].value == B
    assert before[total].value == after[total].value


def test_the_classified_mark_reaches_the_row_and_the_cell_explanation() -> None:
    raw, lines, line_facts = weird_case()
    canonical = map_facts(select_vintage(facts(raw)), MAPS, list(ITEMS))
    face = FaceLines(
        lines_frame(lines),
        facts(line_facts),
        MAPS,
        classified={WEIRD: ("accrued_liabilities",)},
    )
    rules = Rules(filing_lines=face)

    table = build_statement(canonical, ITEMS, "BS", "annual", rules=rules)
    explained = explain_cell(
        canonical, facts(raw), ITEMS, "accrued_liabilities", FY, "FY", rules=rules
    )

    row = next(r for r in table.rows if r.code == "accrued_liabilities")
    at = [p.key for p in table.periods].index(f"FY{FY}")
    assert row.classified_by[at] == ("x:Weird",)
    debt = next(r for r in table.rows if r.code == "short_term_debt")
    assert debt.classified_by[at] is None
    assert explained.classified_by == ("x:Weird",)


def test_a_classification_of_a_line_something_else_classifies_is_ignored() -> None:
    """A stored answer can go stale (the line was mapped or given a verdict since): the mapping
    wins, so the amount is never counted twice."""
    raw, lines, line_facts = weird_case()
    stale = {
        ("us-gaap", "AccountsPayableCurrent"): ("accrued_liabilities",),  # mapped
        ("us-gaap", "CommercialPaper"): ("accrued_liabilities",),  # a face member
        WEIRD: ("accrued_liabilities", "short_term_debt"),  # under `other_lines`
    }

    cells = solve(
        raw, lines, line_facts=line_facts, other_lines=frozenset({WEIRD}), classified=stale
    )
    plain = solve(raw, lines, line_facts=line_facts, other_lines=frozenset({WEIRD}))

    assert cells == plain
    accrued = cells[("accrued_liabilities", f"FY{FY}")]
    assert (accrued.value, accrued.provenance) == (Decimal(0), "zero_inferred")
