"""The counting behind `scripts/projection_report.py` (M7d S1, docs/erd/face-tree.md "Report"),
on the hand-built filings of `test_projection.py`."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from bedrock.statements.cell_types import Cell, FactRef
from bedrock.statements.periods import Period
from bedrock.statements.projection import project, project_all
from bedrock.statements.projection_stats import face_disagreements, form_group, tally
from tests.test_projection import (
    BS_FACTS,
    BS_LINES,
    IS_LINES,
    ITEMS,
    K1,
    Y23,
    face,
    income_facts,
    line,
)

FY2023 = Period("FY2023", "FY23", 2023, "FY", date(2023, 1, 1), Y23)


def test_forms_group_with_their_amendments() -> None:
    assert [form_group(f) for f in ("10-K", "10-K/A", "10-Q", "10-Q/A", "8-K")] == [
        "10-K",
        "10-K",
        "10-Q",
        "10-Q",
        None,
    ]


def test_nothing_projected_counts_nothing() -> None:
    assert tally([]) == {}


def test_lines_are_counted_by_kind_tree_and_block() -> None:
    projected = project(face(), ITEMS, K1, "BS")
    assert projected is not None

    stats = tally([projected])[("10-K", "BS")]

    assert (stats.statements, stats.lines) == (1, 11)
    assert dict(stats.kinds) == {"mapped": 6, "other": 3, "open": 2}
    assert stats.in_tree == 10  # all but the memo line
    assert (stats.open_lines, stats.open_with_block) == (2, 1)  # widgets has one, the memo not


def test_parent_checks_are_read_in_the_newest_face_period() -> None:
    projected = project(face(), ITEMS, K1, "BS")
    assert projected is not None

    stats = tally([projected])[("10-K", "BS")]

    # 2023: current assets foot, assets foot (18 + 12), liabilities and equity do not (and miss
    # the accrued line); 2022's missing widgets does not count
    assert (stats.foot, stats.foot_missing_child, stats.not_foot) == (2, 0, 1)
    assert (stats.with_checks, stats.all_foot) == (1, 0)


def test_a_total_that_foots_with_a_child_missing_in_the_newest_period_is_counted_apart() -> None:
    facts = [f for f in BS_FACTS if not (f["concept"] == "Widgets")]
    facts = [replace_value(f, "AssetsCurrent", Y23, 13) for f in facts]  # 10 + 3
    facts = [replace_value(f, "LiabilitiesAndStockholdersEquity", Y23, 28) for f in facts]
    facts = [replace_value(f, "Assets", Y23, 25) for f in facts]
    projected = project(face(fact_rows=facts), ITEMS, K1, "BS")
    assert projected is not None

    stats = tally([projected])[("10-K", "BS")]

    assert (stats.foot, stats.foot_missing_child, stats.not_foot) == (1, 2, 0)
    assert (stats.with_checks, stats.all_foot) == (1, 1)


def replace_value(row: dict[str, object], concept: str, end: date, value: int) -> dict[str, object]:
    if row["concept"] == concept and row["period_end"] == end:
        return {**row, "value": Decimal(value)}
    return row


def test_statements_are_grouped_by_form_and_statement() -> None:
    rows = [
        *BS_LINES,
        *IS_LINES,
        line("Assets", accession="Q-2023", form="10-Q", filed=date(2023, 11, 1)),
    ]
    projected = project_all(face(rows=rows, fact_rows=[*BS_FACTS, *income_facts()]), ITEMS)

    stats = tally(projected)

    assert set(stats) == {("10-K", "BS"), ("10-K", "IS"), ("10-Q", "BS")}
    assert stats[("10-Q", "BS")].with_checks == 0  # no tree, no check
    assert stats[("10-K", "IS")].all_foot == 1


# --- face disagreements -------------------------------------------------------------------------


def ref(concept: str, accession: str = K1, taxonomy: str = "us-gaap") -> FactRef:
    return FactRef(taxonomy, concept, "USD", None, Y23, accession, "10-K", date(2024, 2, 1))


def cells(cash_source: FactRef | None, provenance: str = "reported") -> dict[tuple[str, str], Cell]:
    return {
        ("total_assets", "FY2023"): Cell(Decimal(30), "reported", ref("Assets")),
        ("cash", "FY2023"): Cell(Decimal(10), provenance, cash_source),  # type: ignore[arg-type]
    }


def test_a_value_from_a_concept_off_the_face_while_a_mapped_one_is_on_it_disagrees() -> None:
    found = face_disagreements(
        cells(ref("CashAndCashEquivalentsAtCarryingValue")), [FY2023], face(), ITEMS
    )

    assert dict(found) == {"cash": 1}


def test_a_value_from_the_face_line_agrees() -> None:
    assert face_disagreements(cells(ref("CashAndCashEquivalents")), [FY2023], face(), ITEMS) == {}


def test_only_reported_year_cells_of_a_parsed_anchor_filing_are_read() -> None:
    off_face = ref("CashAndCashEquivalentsAtCarryingValue")
    quarter = replace(FY2023, key="FY2023Q3", fiscal_period="Q3")
    unparsed = {
        **cells(off_face),
        ("total_assets", "FY2023"): Cell(Decimal(30), "reported", ref("Assets", "K-other")),
    }

    assert face_disagreements(cells(off_face, "derived"), [FY2023], face(), ITEMS) == {}
    assert face_disagreements(cells(None), [FY2023], face(), ITEMS) == {}
    assert face_disagreements(cells(off_face), [quarter], face(), ITEMS) == {}
    assert face_disagreements(unparsed, [FY2023], face(), ITEMS) == {}


def test_no_other_concept_of_the_item_on_the_face_is_no_disagreement() -> None:
    rows = [ln for ln in BS_LINES if ln["concept"] != "CashAndCashEquivalents"]

    found = face_disagreements(
        cells(ref("CashAndCashEquivalentsAtCarryingValue")), [FY2023], face(rows=rows), ITEMS
    )

    assert found == {}
