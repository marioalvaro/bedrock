"""The open lines of a company and the question for each (M7d S2, docs/erd/face-tree.md "Open
lines and questions"), on hand-built `FaceLines`: a fictional calendar-year company."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from bedrock.classify import questions
from bedrock.classify.types import Candidate, LineQuestion
from bedrock.mapping.config import SUPPORT_CODES, CanonicalItemDef
from bedrock.statements.structure import FaceLines
from tests.engine_data import Row, facts, item, mappings
from tests.test_projection import K0, Y22, Y23, at, line, lines_frame

FILED_K0 = date(2023, 2, 1)
SUPPORT = sorted(SUPPORT_CODES)[0]


def bs(code: str, parent: str | None = None, **kw: object) -> CanonicalItemDef:
    return item(code, "BS", kind="instant", parent=parent, **kw)  # type: ignore[arg-type]


ITEMS: list[CanonicalItemDef] = [
    item("revenue"),
    item("cogs"),
    bs("cash", "total_current_assets"),
    bs("inventory", "total_current_assets"),
    bs("receivables", "total_current_assets"),
    replace(bs("custom:trade", "receivables"), custom=True),
    bs("other_current_assets", "total_current_assets", residual=True),
    bs("total_current_assets", "total_assets"),
    bs("ppe", "total_assets"),
    bs("total_assets"),
    bs(SUPPORT),
]
MAPS = mappings(
    ("cash", "CashAndCashEquivalents", 0),
    ("total_current_assets", "AssetsCurrent", 0),
    ("ppe", "PropertyPlantAndEquipmentNet", 0),
    ("total_assets", "Assets", 0),
    ("revenue", "Revenues", 0),
)
WHOLE_BS = (Candidate("cash", "Cash"), Candidate("inventory", "Inventory"), Candidate("ppe", "Ppe"))


def old(concept: str, parent: str | None = None, **kw: object) -> Row:
    return line(concept, parent, accession=K0, filed=FILED_K0, **kw)  # type: ignore[arg-type]


LINES = [
    line("Revenues", statement="IS"),
    line("ext:Fees", statement="IS"),
    line("CashAndCashEquivalents", "AssetsCurrent"),
    line("ext:Widgets", "AssetsCurrent"),
    line("AssetsCurrent", "Assets"),
    line("ext:Tools", "PropertyPlantAndEquipmentNet"),
    line("PropertyPlantAndEquipmentNet", "Assets"),
    line("Assets"),
    line("ext:Memo"),
    line("ext:Zero", "AssetsCurrent"),
    line("ext:Fees", "Assets"),
    {**old("ext:Widgets", "AssetsCurrent"), "label": "Old widgets"},
    old("ext:Gone", "AssetsCurrent"),
    old("AssetsCurrent", "Assets"),
    old("Assets"),
]
FACTS = [
    at("Revenues", Y23, 100, start=date(2023, 1, 1)),
    at("ext:Fees", Y23, 7, start=date(2023, 1, 1)),
    at("CashAndCashEquivalents", Y23, 10),
    at("ext:Widgets", Y23, 5),
    at("ext:Widgets", Y22, 4),
    at("AssetsCurrent", Y23, 18),
    at("AssetsCurrent", Y22, 12),
    at("ext:Tools", Y23, 3),
    at("PropertyPlantAndEquipmentNet", Y23, 3),
    at("Assets", Y23, 21),
    at("ext:Memo", Y22, 9),
    at("ext:Zero", Y23, 0),
    at("ext:Widgets", Y22, 44, accession=K0),
    at("ext:Gone", Y22, 2, accession=K0),
    at("AssetsCurrent", Y22, 12, accession=K0),
    at("Assets", Y22, 12, accession=K0),
]


def face(rows: list[Row] = LINES, fact_rows: list[Row] = FACTS) -> FaceLines:
    return FaceLines(lines_frame(rows), facts(fact_rows), MAPS)


def built(rows: list[Row] = LINES, fact_rows: list[Row] = FACTS) -> dict[str, LineQuestion]:
    return {q.key: q for q in questions.build(face(rows, fact_rows), ITEMS)}


def test_questions_are_the_open_lines_in_statement_then_presentation_order() -> None:
    keys = [q.key for q in questions.build(face(), ITEMS)]

    assert keys == [
        "IS|ext|Fees",
        "BS|ext|Widgets",
        "BS|ext|Tools",
        "BS|ext|Memo",
        "BS|ext|Fees",
        "BS|ext|Gone",  # only an older filing presents it: after the newest filing's lines
    ]


def test_a_line_is_asked_once_per_statement_however_many_filings_present_it() -> None:
    keys = [q.key for q in questions.build(face(), ITEMS)]

    assert keys.count("BS|ext|Widgets") == 1
    assert {"IS|ext|Fees", "BS|ext|Fees"} <= set(keys)


def test_a_mapped_line_a_known_line_and_a_line_with_no_amount_are_not_asked() -> None:
    known = FaceLines(
        lines_frame(LINES), facts(FACTS), MAPS, {("ext", "Memo"): ()}, frozenset({("ext", "Tools")})
    )

    keys = [q.key for q in questions.build(known, ITEMS)]

    assert "BS|ext|Zero" not in built()
    assert "BS|us-gaap|CashAndCashEquivalents" not in built()
    assert "BS|ext|Memo" not in keys and "BS|ext|Tools" not in keys
    assert "BS|ext|Widgets" in keys


def test_the_newest_filing_that_presents_the_line_gives_the_context() -> None:
    widgets = built()["BS|ext|Widgets"]

    assert widgets == LineQuestion(
        key="BS|ext|Widgets",
        statement="BS",
        taxonomy="ext",
        concept="Widgets",
        label="Label of Widgets",
        form="10-K",
        period_end=Y23,
        value=Decimal(5),
        parent_label="Label of AssetsCurrent",
        parent_value=Decimal(18),
        sibling_labels=("Label of CashAndCashEquivalents", "Label of Zero"),
        block_label="Total current assets",
        candidates=(Candidate("cash", "Cash"), Candidate("inventory", "Inventory")),
    )


def test_a_line_only_an_older_filing_presents_takes_that_filing() -> None:
    gone = built()["BS|ext|Gone"]

    assert (gone.period_end, gone.value, gone.parent_value) == (Y22, Decimal(2), Decimal(12))
    assert gone.sibling_labels == ("Old widgets",)


def test_the_value_is_the_newest_and_then_the_longest_period() -> None:
    quarter = at("ext:Fees", Y23, 2, start=date(2023, 10, 1))
    older = at("ext:Fees", Y22, 99, start=date(2022, 1, 1))

    fees = built(fact_rows=[*FACTS, quarter, older])["IS|ext|Fees"]

    assert (fees.period_end, fees.value) == (Y23, Decimal(7))


def test_a_line_without_a_parent_has_no_parent_block_or_neighbours() -> None:
    memo = built()["BS|ext|Memo"]

    assert (memo.parent_label, memo.parent_value, memo.block_label) == (None, None, None)
    assert memo.sibling_labels == ()
    assert (memo.period_end, memo.value) == (Y22, Decimal(9))


def test_a_parent_with_no_fact_for_the_period_has_no_value() -> None:
    fees = built()["BS|ext|Fees"]  # its only fact is a duration; the parent's are instants

    assert fees.parent_label == "Label of Assets"
    assert fees.parent_value is None


def test_a_parent_that_is_not_a_line_of_the_statement_has_no_label() -> None:
    rows = [*LINES, line("ext:Orphan", "ext:Elsewhere")]
    orphan = built(rows, [*FACTS, at("ext:Orphan", Y23, 1)])["BS|ext|Orphan"]

    assert (orphan.parent_label, orphan.parent_value, orphan.sibling_labels) == (None, None, ())


def test_at_most_twelve_neighbours_in_presentation_order() -> None:
    extra = [line(f"ext:N{n:02}", "AssetsCurrent") for n in range(14)]

    widgets = built([*LINES[:4], *extra, *LINES[4:]])["BS|ext|Widgets"]

    assert widgets.sibling_labels == (
        "Label of CashAndCashEquivalents",
        *(f"Label of N{n:02}" for n in range(11)),
    )


def test_candidates_are_the_rows_under_the_block_in_file_order() -> None:
    assert questions.candidates(ITEMS, "BS", "total_current_assets") == (
        Candidate("cash", "Cash"),
        Candidate("inventory", "Inventory"),
    )
    assert questions.candidates(ITEMS, "BS", "total_assets") == WHOLE_BS


def test_candidates_without_a_block_are_the_whole_statement() -> None:
    assert questions.candidates(ITEMS, "BS", None) == WHOLE_BS
    assert built()["BS|ext|Memo"].candidates == WHOLE_BS
    assert questions.candidates(ITEMS, "IS", None) == (
        Candidate("revenue", "Revenue"),
        Candidate("cogs", "Cogs"),
    )


def test_a_block_with_no_candidate_row_falls_back_to_the_whole_statement() -> None:
    assert built()["BS|ext|Tools"].block_label == "Ppe"
    assert built()["BS|ext|Tools"].candidates == WHOLE_BS
    assert questions.candidates(ITEMS, "BS", "no_such_row") == WHOLE_BS


def test_no_residual_support_custom_or_parent_row_is_a_candidate() -> None:
    codes = {c.code for q in questions.build(face(), ITEMS) for c in q.candidates}

    assert codes == {"revenue", "cogs", "cash", "inventory", "ppe"}
    assert not codes & {
        "other_current_assets",  # residual
        SUPPORT,
        "custom:trade",
        "receivables",  # has a child
        "total_current_assets",
        "total_assets",
    }


def test_no_filing_gives_no_question() -> None:
    assert questions.build(face([], []), ITEMS) == []


def test_open_lines_carry_the_placed_line_with_its_block() -> None:
    by_key = {o.question.key: o for o in questions.open_lines(face(), ITEMS)}

    assert by_key["BS|ext|Widgets"].line.block_code == "total_current_assets"
    assert by_key["BS|ext|Widgets"].line.kind == "open"
    assert by_key["BS|ext|Memo"].line.block_code is None
    assert [o.question for o in by_key.values()] == questions.build(face(), ITEMS)
