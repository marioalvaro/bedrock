"""The projection of a filing's face lines on the canonical rows (M7d S1, docs/erd/face-tree.md
"Projection"), on hand-built `FaceLines`: a fictional calendar-year company."""

import random
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.projection import FacePeriod, PlacedLine, project, project_all
from bedrock.statements.structure import LINE_COLUMNS, FaceLines
from tests.engine_data import Row, fact, facts, item, mappings

K1 = "K-2023"
K0 = "K-2022"
Y23 = date(2023, 12, 31)
Y22 = date(2022, 12, 31)


def bs(code: str, parent: str | None = None, **kw: object) -> CanonicalItemDef:
    return item(code, "BS", kind="instant", parent=parent, **kw)  # type: ignore[arg-type]


ITEMS: list[CanonicalItemDef] = [
    bs("cash", "total_current_assets"),
    bs("other_current_assets", "total_current_assets", residual=True),
    bs("total_current_assets", "total_assets"),
    replace(bs("intangibles", "total_assets"), face_members=("us-gaap:Goodwill",)),
    bs("total_assets"),
    bs("accounts_payable", "total_le"),
    bs("accrued_liabilities", "total_le", concepts=("us-gaap:AccruedLiabilitiesCurrent",)),
    bs("total_le"),
]
MAPS = mappings(
    ("cash", "CashAndCashEquivalents", 0),
    ("total_current_assets", "AssetsCurrent", 0),
    ("total_assets", "Assets", 0),
    ("accounts_payable", "AccountsPayableCurrent", 0),
    ("total_le", "LiabilitiesAndStockholdersEquity", 0),
)
VERDICTS = {("us-gaap", "OtherAssetsCurrent"): ("other_current_assets",)}
OTHER_LINES = frozenset({("ext", "Gizmo")})


def line(
    concept: str,
    parent: str | None = None,
    *,
    weight: int = 1,
    statement: str = "BS",
    accession: str = K1,
    form: str = "10-K",
    filed: date = date(2024, 2, 1),
) -> Row:
    taxonomy, _, name = concept.rpartition(":")
    parent_taxonomy, _, parent_name = (parent or "").rpartition(":")
    return {
        "accession_no": accession,
        "form": form,
        "filed_at": filed,
        "statement": statement,
        "position": 0,
        "taxonomy": taxonomy or "us-gaap",
        "concept": name,
        "label": f"Label of {name}",
        "calc_parent_taxonomy": (parent_taxonomy or "us-gaap") if parent else None,
        "calc_parent_concept": parent_name if parent else None,
        "calc_weight": Decimal(weight) if parent else None,
    }


def lines_frame(rows: list[Row]) -> pd.DataFrame:
    out = []
    positions: dict[tuple[object, object], int] = {}
    for row in rows:
        key = (row["accession_no"], row["statement"])
        positions[key] = positions.get(key, 0) + 1
        out.append({**row, "position": positions[key]})
    return pd.DataFrame(out, columns=LINE_COLUMNS).astype({"calc_weight": "object"})


def at(concept: str, end: date, value: int, *, start: date | None = None, **kw: object) -> Row:
    taxonomy, _, name = concept.rpartition(":")
    return fact(
        name,
        start,
        end,
        value,
        accession=str(kw.pop("accession", K1)),
        taxonomy=taxonomy or "us-gaap",
        filed=date(2024, 2, 1),
        **kw,  # type: ignore[arg-type]
    )


BS_LINES = [
    line("CashAndCashEquivalents", "AssetsCurrent"),
    line("ext:Widgets", "AssetsCurrent"),
    line("OtherAssetsCurrent", "AssetsCurrent"),
    line("AssetsCurrent", "Assets"),
    line("Goodwill", "Assets"),
    line("Assets"),
    line("AccountsPayableCurrent", "LiabilitiesAndStockholdersEquity"),
    line("ext:Gizmo", "LiabilitiesAndStockholdersEquity"),
    line("AccruedLiabilitiesCurrent", "LiabilitiesAndStockholdersEquity"),
    line("LiabilitiesAndStockholdersEquity"),
    line("ext:Memo"),
]
BS_FACTS = [
    at("CashAndCashEquivalents", Y23, 10),
    at("CashAndCashEquivalents", Y22, 8),
    at("CashAndCashEquivalents", Y23, 999, accession=K0),  # another filing's fact
    at("ext:Widgets", Y23, 5),  # none in 2022: a missing child there
    at("OtherAssetsCurrent", Y23, 3),
    at("OtherAssetsCurrent", Y22, 2),
    at("AssetsCurrent", Y23, 18),
    at("AssetsCurrent", Y22, 10),
    at("Goodwill", Y23, 12),
    at("Goodwill", Y22, 10),
    at("Assets", Y23, 30),
    at("Assets", Y22, 20),
    at("AccountsPayableCurrent", Y23, 20),
    at("AccountsPayableCurrent", Y22, 15),
    at("ext:Gizmo", Y23, 8),
    at("ext:Gizmo", Y22, 5),
    at("LiabilitiesAndStockholdersEquity", Y23, 30),  # 20 + 8 = 28: does not foot
    at("LiabilitiesAndStockholdersEquity", Y22, 20),
    at("ext:Memo", date(2023, 12, 30), 4, unit="shares"),  # a day off: no face-period value
]


def face(
    rows: list[Row] = BS_LINES,
    fact_rows: list[Row] = BS_FACTS,
    maps: pd.DataFrame = MAPS,
) -> FaceLines:
    return FaceLines(lines_frame(rows), facts(fact_rows), maps, VERDICTS, OTHER_LINES)


def placed(concept: str, statement_lines: tuple[PlacedLine, ...]) -> PlacedLine:
    return next(ln for ln in statement_lines if ln.concept == concept)


def balance_sheet() -> tuple[PlacedLine, ...]:
    projected = project(face(), ITEMS, K1, "BS")
    assert projected is not None
    return projected.lines


# --- placement ----------------------------------------------------------------------------------


def test_every_line_is_placed_once_in_presentation_order() -> None:
    lines = balance_sheet()

    assert [ln.position for ln in lines] == list(range(1, 12))
    assert [ln.concept for ln in lines][:3] == [
        "CashAndCashEquivalents",
        "Widgets",
        "OtherAssetsCurrent",
    ]
    assert placed("Widgets", lines).label == "Label of Widgets"
    assert placed("Widgets", lines).taxonomy == "ext"


def test_a_mapped_line_names_its_rows() -> None:
    lines = balance_sheet()

    assert (
        placed("CashAndCashEquivalents", lines).kind,
        placed("CashAndCashEquivalents", lines).codes,
    ) == ("mapped", ("cash",))
    assert (placed("Assets", lines).kind, placed("Assets", lines).codes) == (
        "mapped",
        ("total_assets",),
    )


def test_a_face_member_is_mapped_to_its_item() -> None:
    goodwill = placed("Goodwill", balance_sheet())

    assert (goodwill.kind, goodwill.codes) == ("mapped", ("intangibles",))


def test_the_codes_of_a_line_mapped_twice_follow_the_canonical_file() -> None:
    # total_assets comes first in the frame, after total_current_assets in the file
    maps = pd.concat([mappings(("total_assets", "AssetsCurrent", 1)), MAPS], ignore_index=True)
    projected = project(face(maps=maps), ITEMS, K1, "BS")
    assert projected is not None

    assert placed("AssetsCurrent", projected.lines).codes == (
        "total_current_assets",
        "total_assets",
    )


def test_a_verdict_an_other_line_and_an_excluded_default_are_other() -> None:
    lines = balance_sheet()

    other = placed("OtherAssetsCurrent", lines)
    assert (other.kind, other.codes) == ("other", ("other_current_assets",))
    gizmo = placed("Gizmo", lines)
    assert (gizmo.kind, gizmo.codes) == ("other", ())
    excluded = placed("AccruedLiabilitiesCurrent", lines)  # a default the company does not map
    assert (excluded.kind, excluded.codes) == ("other", ())


def test_a_line_nothing_classifies_is_open() -> None:
    lines = balance_sheet()

    assert (placed("Widgets", lines).kind, placed("Widgets", lines).codes) == ("open", ())
    assert placed("Memo", lines).kind == "open"


def test_depth_parent_weight_and_totals_come_from_the_calculation_tree() -> None:
    lines = balance_sheet()

    cash = placed("CashAndCashEquivalents", lines)
    assert (cash.depth, cash.parent, cash.weight) == (2, ("us-gaap", "AssetsCurrent"), Decimal(1))
    assert (cash.in_tree, cash.is_total) == (True, False)
    current = placed("AssetsCurrent", lines)
    assert (current.depth, current.in_tree, current.is_total) == (1, True, True)
    assets = placed("Assets", lines)
    assert (assets.depth, assets.parent, assets.weight, assets.is_total) == (0, None, None, True)
    memo = placed("Memo", lines)
    assert (memo.depth, memo.in_tree, memo.is_total) == (0, False, False)


def test_a_parent_off_the_face_counts_as_one_ancestor() -> None:
    rows = [line("CashAndCashEquivalents", "AssetsCurrent"), line("Goodwill")]
    projected = project(face(rows=rows), ITEMS, K1, "BS")
    assert projected is not None

    cash = placed("CashAndCashEquivalents", projected.lines)
    assert (cash.depth, cash.in_tree, cash.block_code) == (1, True, "total_current_assets")


def test_the_block_is_the_first_code_of_the_nearest_mapped_ancestor() -> None:
    lines = balance_sheet()

    assert placed("Widgets", lines).block_code == "total_current_assets"
    assert placed("CashAndCashEquivalents", lines).block_code == "total_current_assets"
    assert placed("AssetsCurrent", lines).block_code == "total_assets"
    assert placed("Gizmo", lines).block_code == "total_le"
    assert placed("Assets", lines).block_code is None
    assert placed("Memo", lines).block_code is None


def test_an_unmapped_ancestor_is_skipped_for_the_block() -> None:
    rows = [
        line("ext:Widgets", "ext:Subtotal"),
        line("ext:Subtotal", "AssetsCurrent"),
        line("AssetsCurrent"),
    ]
    projected = project(face(rows=rows), ITEMS, K1, "BS")
    assert projected is not None

    widgets = placed("Widgets", projected.lines)
    assert (widgets.depth, widgets.block_code) == (2, "total_current_assets")


def test_the_unit_is_that_of_the_lines_facts_in_the_filing() -> None:
    lines = balance_sheet()

    assert placed("Assets", lines).unit == "USD"
    assert placed("Memo", lines).unit == "shares"
    assert placed("AccruedLiabilitiesCurrent", lines).unit is None  # no fact at all


# --- face periods and values --------------------------------------------------------------------


def test_face_periods_are_those_most_lines_have_newest_first() -> None:
    projected = project(face(), ITEMS, K1, "BS")
    assert projected is not None

    assert projected.periods == (FacePeriod(None, Y23), FacePeriod(None, Y22))
    assert (projected.accession_no, projected.form, projected.filed_at) == (
        K1,
        "10-K",
        date(2024, 2, 1),
    )
    assert projected.statement == "BS"


def test_values_are_the_filings_own_facts_for_exactly_the_period() -> None:
    lines = balance_sheet()

    assert placed("CashAndCashEquivalents", lines).values == (Decimal(10), Decimal(8))
    assert placed("Widgets", lines).values == (Decimal(5), None)
    assert placed("Memo", lines).values == (None, None)  # its fact is a day off


IS_LINES = [
    line("Revenues", "GrossProfit", statement="IS"),
    line("CostOfRevenue", "GrossProfit", weight=-1, statement="IS"),
    line("GrossProfit", statement="IS"),
    line("ext:Rare", statement="IS"),
]
FY23 = (date(2023, 1, 1), Y23)
Q423 = (date(2023, 10, 1), Y23)
FY22 = (date(2022, 1, 1), Y22)


def income_facts(*, gross23: int = 40) -> list[Row]:
    rows: list[Row] = []
    for (start, end), scale in ((FY22, 1), (Q423, 1), (FY23, 1)):
        rows += [
            at("Revenues", end, 100 * scale, start=start),
            at("CostOfRevenue", end, 60 * scale, start=start),
            at("GrossProfit", end, gross23 if (start, end) == FY23 else 40, start=start),
        ]
    rows.append(
        at("ext:Rare", Y23, 1, start=date(2023, 7, 1))
    )  # one line of four: not a face period
    rows.append(at("Revenues", Y23, 5, start=date(2023, 4, 1)))  # two of four: not more than half
    rows.append(at("CostOfRevenue", Y23, 5, start=date(2023, 4, 1)))
    return rows


def test_durations_are_ordered_newest_end_then_longest_first() -> None:
    projected = project(face(rows=IS_LINES, fact_rows=income_facts()), ITEMS, K1, "IS")
    assert projected is not None

    assert projected.periods == (
        FacePeriod(*FY23),
        FacePeriod(*Q423),
        FacePeriod(*FY22),
    )


def test_a_period_needs_more_than_half_of_the_lines_with_facts() -> None:
    projected = project(face(rows=IS_LINES, fact_rows=income_facts()), ITEMS, K1, "IS")
    assert projected is not None

    starts = {p.start for p in projected.periods}
    assert date(2023, 7, 1) not in starts
    assert date(2023, 4, 1) not in starts


# --- footing ------------------------------------------------------------------------------------


def test_a_total_foots_with_its_weighted_children() -> None:
    projected = project(face(rows=IS_LINES, fact_rows=income_facts()), ITEMS, K1, "IS")
    assert projected is not None

    gross = placed("GrossProfit", projected.lines)
    assert gross.foots == (True, True, True)
    assert placed("Revenues", projected.lines).foots == (None, None, None)
    assert projected.foots is True


def test_a_total_within_the_tolerance_foots_and_beyond_it_does_not() -> None:
    within = project(face(rows=IS_LINES, fact_rows=income_facts(gross23=41)), ITEMS, K1, "IS")
    beyond = project(face(rows=IS_LINES, fact_rows=income_facts(gross23=42)), ITEMS, K1, "IS")
    assert within is not None and beyond is not None

    assert placed("GrossProfit", within.lines).foots[0] is True  # |40 - 41| <= 1
    assert placed("GrossProfit", beyond.lines).foots[0] is False
    assert beyond.foots is False


def test_a_child_with_no_value_counts_zero_and_is_noted_missing() -> None:
    lines = balance_sheet()

    current = placed("AssetsCurrent", lines)
    assert current.foots == (True, True)  # 2022: 8 + (no widgets) + 2 = 10
    assert current.missing_children == ()  # widgets has a 2023 value
    total = placed("LiabilitiesAndStockholdersEquity", lines)
    assert total.foots == (False, True)  # 2023: 20 + 8 + nothing = 28, not 30
    assert total.missing_children == ("us-gaap:AccruedLiabilitiesCurrent",)


def test_a_statement_with_a_total_that_does_not_foot_does_not_foot() -> None:
    projected = project(face(), ITEMS, K1, "BS")
    assert projected is not None

    assert projected.foots is False


def test_a_total_without_a_value_is_not_checked() -> None:
    rows = [
        r
        for r in income_facts()
        if r["period_start"] in (FY23[0], Q423[0], FY22[0])
        and not (r["concept"] == "GrossProfit" and r["period_start"] == FY22[0])
    ]
    # three lines (no ext:Rare): two of three still give FY2022 a face period
    projected = project(face(rows=IS_LINES[:3], fact_rows=rows), ITEMS, K1, "IS")
    assert projected is not None

    assert placed("GrossProfit", projected.lines).foots == (True, True, None)


def test_a_statement_with_no_tree_has_no_check() -> None:
    rows = [line("Revenues", statement="IS"), line("CostOfRevenue", statement="IS")]
    projected = project(face(rows=rows, fact_rows=income_facts()), ITEMS, K1, "IS")
    assert projected is not None

    assert all(not ln.in_tree for ln in projected.lines)
    assert all(f is None for ln in projected.lines for f in ln.foots)
    assert projected.foots is None


def test_a_total_equal_to_its_weighted_children_always_foots() -> None:
    """A seeded property (hypothesis is not installed): random children, weights and values."""
    rng = random.Random(11)
    for _ in range(200):
        children = [
            (rng.randint(-(10**12), 10**12), rng.choice([1, -1])) for _ in range(rng.randint(1, 8))
        ]
        rows = [line(f"ext:Child{n}", "ext:Total", weight=w) for n, (_, w) in enumerate(children)]
        rows.append(line("ext:Total"))
        fact_rows = [at(f"ext:Child{n}", Y23, v) for n, (v, _) in enumerate(children)]
        fact_rows.append(at("ext:Total", Y23, sum(v * w for v, w in children)))

        projected = project(face(rows=rows, fact_rows=fact_rows), ITEMS, K1, "BS")

        assert projected is not None
        assert projected.foots is True, children


# --- statements and filings ---------------------------------------------------------------------


def test_a_filing_without_lines_for_the_statement_projects_to_none() -> None:
    assert project(face(), ITEMS, K1, "CF") is None
    assert project(face(), ITEMS, "K-1999", "BS") is None


def test_every_statement_of_every_filing_is_projected_oldest_filing_first() -> None:
    rows = [
        *BS_LINES,
        *IS_LINES,
        line("Assets", accession=K0, filed=date(2023, 2, 1)),
    ]
    projected = project_all(face(rows=rows, fact_rows=[*BS_FACTS, *income_facts()]), ITEMS)

    assert [(p.accession_no, p.statement) for p in projected] == [
        (K0, "BS"),
        (K1, "IS"),
        (K1, "BS"),
    ]


def test_no_face_lines_project_to_nothing() -> None:
    empty = FaceLines(lines_frame([]), facts([]), MAPS)

    assert project_all(empty, ITEMS) == []
    assert project(empty, ITEMS, K1, "BS") is None
