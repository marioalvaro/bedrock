import json
from pathlib import Path

import pytest

from bedrock.mapping.candidates import (
    DEFAULT_CROSSWALK_PATH,
    DEFAULT_VENDOR_PATH,
    candidate_codes,
    load_candidate_index,
)
from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    MappingConfigError,
    load_canonical_items,
)
from tests.engine_data import item

ITEMS = [
    item("revenue"),
    item("short_term_debt", "BS", kind="instant"),
    item("sga"),
    item("net_income"),
    item("other_operating_expenses", residual=True, derive="revenue - sga"),
]

VENDOR = {
    "_metadata": {"version": "3.0.0"},
    "Revenues": {"standard_tags": ["Revenue"], "confidence": 0.9},
    "SalesRevenueNet": {"standard_tags": ["Revenue"]},
    "ShortTermBorrowings": {"standard_tags": ["ShortTermDebt"]},
    "SellingAndMarketingExpense": {"standard_tags": ["SellingGeneralAndAdminExpenses"]},
    "ProfitLoss": {"standard_tags": ["ProfitLoss"]},
    "OtherNonoperatingIncome": {"standard_tags": ["NonoperatingIncomeExpense"]},
    "ifrs-full_Revenue": {"standard_tags": ["Revenue"]},
    "ifrs:ProfitLoss": {"standard_tags": ["ProfitLoss"]},
    "CombinedLine": {"standard_tags": ["Revenue", "ShortTermDebt", "ProfitLoss"]},
}

CROSSWALK = """
codes:
  Revenue: revenue
  ShortTermDebt: short_term_debt
  SellingGeneralAndAdminExpenses: sga
  ProfitLoss: [net_income, revenue]
unmapped:
  NonoperatingIncomeExpense: "other_nonoperating_income is a residual"
"""


def write(tmp_path: Path, vendor: object = VENDOR, crosswalk: str = CROSSWALK) -> tuple[Path, Path]:
    vendor_path = tmp_path / "vendor.json"
    vendor_path.write_text(json.dumps(vendor))
    crosswalk_path = tmp_path / "crosswalk.yaml"
    crosswalk_path.write_text(crosswalk)
    return vendor_path, crosswalk_path


def test_a_concept_gets_the_codes_of_its_standard_tags(tmp_path: Path) -> None:
    index = load_candidate_index(*write(tmp_path), ITEMS)

    assert candidate_codes(index, "us-gaap", "Revenues") == ["revenue"]
    assert candidate_codes(index, "us-gaap", "ShortTermBorrowings") == ["short_term_debt"]
    assert candidate_codes(index, "us-gaap", "SellingAndMarketingExpense") == ["sga"]


def test_a_tag_can_list_several_codes_and_a_concept_several_tags(tmp_path: Path) -> None:
    index = load_candidate_index(*write(tmp_path), ITEMS)

    assert candidate_codes(index, "us-gaap", "ProfitLoss") == ["net_income", "revenue"]
    # tag order, no duplicates: Revenue -> revenue, ShortTermDebt -> short_term_debt, ProfitLoss
    assert candidate_codes(index, "us-gaap", "CombinedLine") == [
        "revenue",
        "short_term_debt",
        "net_income",
    ]


def test_a_concept_whose_tags_are_all_unmapped_has_no_candidates(tmp_path: Path) -> None:
    index = load_candidate_index(*write(tmp_path), ITEMS)

    assert candidate_codes(index, "us-gaap", "OtherNonoperatingIncome") == []
    assert candidate_codes(index, "us-gaap", "NotInTheTable") == []


def test_bare_names_are_us_gaap_and_ifrs_spellings_are_normalized(tmp_path: Path) -> None:
    index = load_candidate_index(*write(tmp_path), ITEMS)

    assert candidate_codes(index, "ifrs-full", "Revenue") == ["revenue"]
    assert candidate_codes(index, "ifrs-full", "ProfitLoss") == ["net_income", "revenue"]
    assert candidate_codes(index, "us-gaap", "Revenue") == []  # the ifrs concept is not us-gaap


def test_comment_and_metadata_keys_are_skipped(tmp_path: Path) -> None:
    vendor = {**VENDOR, "_comment_notes": "free text", "_metadata": {"version": "3"}}

    index = load_candidate_index(*write(tmp_path, vendor), ITEMS)

    assert candidate_codes(index, "us-gaap", "_comment_notes") == []
    assert all(not concept.startswith("_") for _, concept in index)


def test_a_standard_concept_missing_from_the_crosswalk_is_an_error(tmp_path: Path) -> None:
    vendor = {**VENDOR, "NewConcept": {"standard_tags": ["BrandNewTag"]}}

    with pytest.raises(MappingConfigError, match="BrandNewTag"):
        load_candidate_index(*write(tmp_path, vendor), ITEMS)


def test_a_crosswalk_concept_the_table_no_longer_has_is_an_error(tmp_path: Path) -> None:
    crosswalk = CROSSWALK + '  GoneTag: "was dropped upstream"\n'

    with pytest.raises(MappingConfigError, match="GoneTag"):
        load_candidate_index(*write(tmp_path, crosswalk=crosswalk), ITEMS)


def test_a_concept_listed_as_mapped_and_unmapped_is_an_error(tmp_path: Path) -> None:
    crosswalk = CROSSWALK + '  Revenue: "also listed here"\n'

    with pytest.raises(MappingConfigError, match="Revenue"):
        load_candidate_index(*write(tmp_path, crosswalk=crosswalk), ITEMS)


def test_an_unknown_code_is_an_error(tmp_path: Path) -> None:
    crosswalk = CROSSWALK.replace("ShortTermDebt: short_term_debt", "ShortTermDebt: no_such_code")

    with pytest.raises(MappingConfigError, match="no_such_code"):
        load_candidate_index(*write(tmp_path, crosswalk=crosswalk), ITEMS)


def test_a_residual_code_is_an_error(tmp_path: Path) -> None:
    crosswalk = CROSSWALK.replace(
        "ShortTermDebt: short_term_debt", "ShortTermDebt: other_operating_expenses"
    )

    with pytest.raises(MappingConfigError, match="residual"):
        load_candidate_index(*write(tmp_path, crosswalk=crosswalk), ITEMS)


def test_an_unmapped_concept_needs_a_reason(tmp_path: Path) -> None:
    crosswalk = CROSSWALK.replace(
        'NonoperatingIncomeExpense: "other_nonoperating_income is a residual"',
        "NonoperatingIncomeExpense: null",
    )

    with pytest.raises(MappingConfigError, match="NonoperatingIncomeExpense"):
        load_candidate_index(*write(tmp_path, crosswalk=crosswalk), ITEMS)


def test_a_malformed_crosswalk_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="codes"):
        load_candidate_index(*write(tmp_path, crosswalk="- just\n- a list\n"), ITEMS)


# --- The shipped table and crosswalk -------------------------------------------------------


def test_the_shipped_crosswalk_covers_every_concept_of_the_vendored_table() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    index = load_candidate_index(DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, items)  # validates

    assert len(index) > 1_000


@pytest.mark.parametrize(
    ("taxonomy", "concept", "expected"),
    [
        ("us-gaap", "CommercialPaper", ["short_term_debt"]),
        ("us-gaap", "ShortTermBorrowings", ["short_term_debt"]),
        ("us-gaap", "SellingAndMarketingExpense", ["sga"]),
        ("us-gaap", "GeneralAndAdministrativeExpense", ["sga"]),
        (
            "us-gaap",
            "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
            ["sales_maturities_of_investments"],
        ),
        ("ifrs-full", "Assets", ["total_assets"]),
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", []),  # cash + investments bucket
    ],
)
def test_shipped_candidates_for_known_concepts(
    taxonomy: str, concept: str, expected: list[str]
) -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    index = load_candidate_index(DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, items)

    assert candidate_codes(index, taxonomy, concept) == expected
