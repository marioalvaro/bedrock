from pathlib import Path

import pytest

from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    CanonicalItemDef,
    MappingConfigError,
    formula_order,
    load_canonical_items,
    load_overrides,
    parse_formula,
    split_concept,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "items.yaml"
    path.write_text(text)
    return path


VALID = """
- code: revenue
  statement: IS
  label: Revenue
  kind: flow
  unit: USD
  sign: 1
  parent: null
  concepts: [Revenues, us-gaap:SalesRevenueNet, ifrs-full:Revenue]
- code: cost_of_revenue
  statement: IS
  label: Cost of revenue
  kind: flow
  unit: USD
  sign: 1
  parent: gross_profit
  concepts: [CostOfRevenue]
- code: gross_profit
  statement: IS
  label: Gross profit
  kind: flow
  unit: USD
  sign: 1
  parent: null
  concepts: [GrossProfit]
  derive: revenue - cost_of_revenue
"""


def test_parse_formula_returns_signed_codes() -> None:
    assert parse_formula("a - b + c_2") == [(1, "a"), (-1, "b"), (1, "c_2")]


def test_parse_formula_single_code() -> None:
    assert parse_formula("total_assets") == [(1, "total_assets")]


@pytest.mark.parametrize("text", ["", "a -", "a b", "+ + a", "A - b", "a - 1b"])
def test_parse_formula_rejects_malformed_text(text: str) -> None:
    with pytest.raises(MappingConfigError):
        parse_formula(text)


def test_split_concept_defaults_to_us_gaap() -> None:
    assert split_concept("Revenues") == ("us-gaap", "Revenues")
    assert split_concept("ifrs-full:Revenue") == ("ifrs-full", "Revenue")


def test_load_canonical_items_reads_every_field(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))

    assert [i.code for i in items] == ["revenue", "cost_of_revenue", "gross_profit"]
    revenue, _, gross_profit = items
    assert revenue == CanonicalItemDef(
        code="revenue",
        statement="IS",
        label="Revenue",
        kind="flow",
        unit="USD",
        sign=1,
        parent=None,
        concepts=("us-gaap:Revenues", "us-gaap:SalesRevenueNet", "ifrs-full:Revenue"),
        derive=None,
        residual=False,
    )
    assert gross_profit.derive == "revenue - cost_of_revenue"


def test_optional_fields_default(tmp_path: Path) -> None:
    text = """
- code: cash
  statement: BS
  label: Cash
  kind: instant
  unit: USD
  sign: 1
"""
    (item,) = load_canonical_items(write(tmp_path, text))

    assert item.parent is None
    assert item.concepts == ()
    assert item.derive is None
    assert item.residual is False


def fail_with(tmp_path: Path, text: str) -> MappingConfigError:
    with pytest.raises(MappingConfigError) as info:
        load_canonical_items(write(tmp_path, text))
    return info.value


def test_unknown_parent_names_the_code(tmp_path: Path) -> None:
    error = fail_with(tmp_path, VALID.replace("parent: gross_profit", "parent: nowhere"))

    assert error.code == "cost_of_revenue"
    assert "cost_of_revenue" in str(error)


def test_parent_on_another_statement_is_rejected(tmp_path: Path) -> None:
    text = (
        VALID
        + """
- code: cash
  statement: BS
  label: Cash
  kind: instant
  unit: USD
  sign: 1
  parent: revenue
"""
    )
    assert fail_with(tmp_path, text).code == "cash"


def test_parent_cycle_is_rejected(tmp_path: Path) -> None:
    text = VALID.replace(
        "parent: null\n  concepts: [GrossProfit]",
        "parent: cost_of_revenue\n  concepts: [GrossProfit]",
    )
    assert fail_with(tmp_path, text).code in {"cost_of_revenue", "gross_profit"}


def test_unknown_formula_code_is_rejected(tmp_path: Path) -> None:
    error = fail_with(tmp_path, VALID.replace("revenue - cost_of_revenue", "revenue - ghost"))

    assert error.code == "gross_profit"
    assert "ghost" in str(error)


def test_formula_cycle_is_rejected(tmp_path: Path) -> None:
    text = VALID.replace(
        "concepts: [Revenues, us-gaap:SalesRevenueNet, ifrs-full:Revenue]",
        "concepts: []\n  derive: gross_profit",
    )
    assert fail_with(tmp_path, text).code in {"revenue", "gross_profit"}


def test_formula_across_statements_is_rejected(tmp_path: Path) -> None:
    text = (
        VALID
        + """
- code: cash
  statement: BS
  label: Cash
  kind: instant
  unit: USD
  sign: 1
  derive: revenue
"""
    )
    assert fail_with(tmp_path, text).code == "cash"


def test_duplicate_code_is_rejected(tmp_path: Path) -> None:
    assert fail_with(tmp_path, VALID + VALID).code == "revenue"


def test_duplicate_concept_within_a_code_is_rejected(tmp_path: Path) -> None:
    error = fail_with(
        tmp_path, VALID.replace("[CostOfRevenue]", "[CostOfRevenue, us-gaap:CostOfRevenue]")
    )

    assert error.code == "cost_of_revenue"


@pytest.mark.parametrize(
    "old, new",
    [
        ("statement: IS\n  label: Revenue", "statement: XX\n  label: Revenue"),
        (
            "kind: flow\n  unit: USD\n  sign: 1\n  parent: null",
            "kind: stock\n  unit: USD\n  sign: 1\n  parent: null",
        ),
        ("unit: USD\n  sign: 1\n  parent: null", "unit: EUR\n  sign: 1\n  parent: null"),
        ("sign: 1\n  parent: null", "sign: 2\n  parent: null"),
    ],
)
def test_bad_enum_value_is_rejected(tmp_path: Path, old: str, new: str) -> None:
    assert old in VALID
    assert fail_with(tmp_path, VALID.replace(old, new, 1)).code == "revenue"


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    assert fail_with(tmp_path, VALID.replace("  label: Revenue\n", "")).code == "revenue"


def test_residual_needs_derive_and_no_concepts(tmp_path: Path) -> None:
    residual = """
- code: other_current_assets
  statement: BS
  label: Other
  kind: instant
  unit: USD
  sign: 1
  residual: true
  derive: total_current_assets - cash
- code: cash
  statement: BS
  label: Cash
  kind: instant
  unit: USD
  sign: 1
- code: total_current_assets
  statement: BS
  label: TCA
  kind: instant
  unit: USD
  sign: 1
"""
    assert len(load_canonical_items(write(tmp_path, residual))) == 3
    no_derive = residual.replace("  derive: total_current_assets - cash\n", "")
    assert fail_with(tmp_path, no_derive).code == "other_current_assets"
    with_concepts = residual.replace(
        "residual: true", "residual: true\n  concepts: [OtherAssetsCurrent]"
    )
    assert fail_with(tmp_path, with_concepts).code == "other_current_assets"


def test_formula_order_puts_operands_first(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))

    assert [i.code for i in formula_order(items)] == ["gross_profit"]


def test_formula_order_handles_chains() -> None:
    def item(code: str, derive: str | None) -> CanonicalItemDef:
        return CanonicalItemDef(code, "BS", code, "instant", "USD", 1, None, (), derive, False)

    ordered = formula_order([item("c", "b + a"), item("b", "a"), item("a", None)])

    assert [i.code for i in ordered] == ["b", "c"]


def test_load_overrides_qualifies_concepts(tmp_path: Path) -> None:
    (tmp_path / "AAPL.yaml").write_text("revenue: [RevenueFromContractWithCustomer, custom:Rev]\n")

    assert load_overrides(tmp_path, "aapl") == {
        "revenue": ["us-gaap:RevenueFromContractWithCustomer", "custom:Rev"]
    }


def test_load_overrides_without_a_file_is_empty(tmp_path: Path) -> None:
    assert load_overrides(tmp_path, "MSFT") == {}
    assert load_overrides(tmp_path / "missing", "MSFT") == {}


def test_load_overrides_rejects_unknown_codes_and_duplicates(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text("ghost: [A]\n")
    with pytest.raises(MappingConfigError):
        load_overrides(tmp_path, "X", items)
    (tmp_path / "Y.yaml").write_text("revenue: [A, us-gaap:A]\n")
    with pytest.raises(MappingConfigError):
        load_overrides(tmp_path, "Y", items)


def test_shipped_canonical_items_load_with_72_codes() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    assert len(items) == 72
    assert {i.statement for i in items} == {"IS", "BS", "CF"}
    by_code = {i.code: i for i in items}
    assert by_code["eps_diluted"].kind == "average"
    assert by_code["eps_diluted"].unit == "USD/shares"
    assert by_code["capex"].sign == -1
    assert by_code["other_current_assets"].residual is True
    assert by_code["cash"].parent == "total_current_assets"
    assert by_code["total_current_assets"].parent == "total_assets"
    assert by_code["rnd"].parent == "operating_income"
    assert by_code["capex"].parent == "cfi"
    assert all(i.concepts == () for i in items)  # S3 fills them
