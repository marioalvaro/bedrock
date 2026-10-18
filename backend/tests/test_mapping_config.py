from pathlib import Path

import pytest

from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    CanonicalItemDef,
    MappingConfigError,
    formula_order,
    is_adjustable,
    load_canonical_items,
    load_excludes,
    load_overrides,
    parse_formula,
    propagation_targets,
    split_concept,
    split_group,
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


def test_split_group_lists_the_members_anchor_first() -> None:
    assert split_group("us-gaap:CommercialPaper + LongTermDebtCurrent") == [
        ("us-gaap", "CommercialPaper"),
        ("us-gaap", "LongTermDebtCurrent"),
    ]
    assert split_group("Revenues") == [("us-gaap", "Revenues")]
    assert split_group("A+B") == [("us-gaap", "A"), ("us-gaap", "B")]


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


def test_a_summed_concept_is_qualified_member_by_member(tmp_path: Path) -> None:
    text = VALID.replace(
        "concepts: [CostOfRevenue]",
        'concepts: [CostOfRevenue + OtherCost, "us-gaap:Foo +  Bar", CostOfRevenue]',
    )

    items = {i.code: i for i in load_canonical_items(write(tmp_path, text))}

    assert items["cost_of_revenue"].concepts == (
        "us-gaap:CostOfRevenue + us-gaap:OtherCost",
        "us-gaap:Foo + us-gaap:Bar",
        "us-gaap:CostOfRevenue",
    )  # a concept may recur as a member of another group, or alone as the fallback


@pytest.mark.parametrize(
    "entry",
    [
        "CostOfRevenue + CostOfRevenue",  # a member twice
        "CostOfRevenue + us-gaap:CostOfRevenue",
        "CostOfRevenue + ",  # empty member
        "+ CostOfRevenue",
        "CostOfRevenue + + OtherCost",
        "CostOfRevenue + aapl:OtherCost",  # the members of a sum share one taxonomy
    ],
)
def test_a_malformed_summed_concept_is_rejected(tmp_path: Path, entry: str) -> None:
    error = fail_with(tmp_path, VALID.replace("[CostOfRevenue]", f'["{entry}"]'))

    assert error.code == "cost_of_revenue"


def test_the_same_summed_concept_twice_is_rejected(tmp_path: Path) -> None:
    text = VALID.replace("[CostOfRevenue]", "[A + B, us-gaap:A + B]")

    assert fail_with(tmp_path, text).code == "cost_of_revenue"


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


def test_load_overrides_qualifies_summed_concepts(tmp_path: Path) -> None:
    (tmp_path / "AAPL.yaml").write_text(
        'short_term_debt: ["CommercialPaper + LongTermDebtCurrent", LongTermDebtCurrent]\n'
    )

    assert load_overrides(tmp_path, "aapl") == {
        "short_term_debt": [
            "us-gaap:CommercialPaper + us-gaap:LongTermDebtCurrent",
            "us-gaap:LongTermDebtCurrent",
        ]
    }


def test_load_overrides_rejects_a_malformed_sum(tmp_path: Path) -> None:
    (tmp_path / "X.yaml").write_text('revenue: ["A + A"]\n')

    with pytest.raises(MappingConfigError):
        load_overrides(tmp_path, "X")


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


def test_shipped_canonical_items_load_with_82_codes() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    assert len(items) == 82
    assert {i.statement for i in items} == {"IS", "BS", "CF"}
    by_code = {i.code: i for i in items}
    assert by_code["eps_diluted"].kind == "average"
    assert by_code["eps_diluted"].unit == "USD/shares"
    assert by_code["capex"].sign == -1
    assert by_code["other_current_assets"].residual is True
    assert by_code["cash"].parent == "total_current_assets"
    assert by_code["total_current_assets"].parent == "total_assets"
    assert by_code["rnd"].parent == "total_operating_costs"
    assert by_code["capex"].parent == "cfi"
    assert all(i.concepts == () for i in items if i.residual)  # residuals are always computed


def test_shipped_items_put_every_parent_before_its_children() -> None:
    """File order is display order: a subtotal is shown above its breakdown."""
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    position = {i.code: n for n, i in enumerate(items)}

    misplaced = [
        i.code for i in items if i.parent is not None and position[i.parent] > position[i.code]
    ]

    assert misplaced == []


def test_shipped_items_split_the_balance_sheet_into_current_and_noncurrent() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}

    assert by_code["total_noncurrent_assets"].parent == "total_assets"
    assert by_code["total_noncurrent_assets"].derive == "total_assets - total_current_assets"
    assert by_code["total_noncurrent_liabilities"].parent == "total_liabilities"
    assert (
        by_code["total_noncurrent_liabilities"].derive
        == "total_liabilities - total_current_liabilities"
    )
    for code in ("ppe_net", "goodwill", "other_noncurrent_assets"):
        assert by_code[code].parent == "total_noncurrent_assets"
    for code in ("long_term_debt", "other_noncurrent_liabilities"):
        assert by_code[code].parent == "total_noncurrent_liabilities"


def test_shipped_items_total_the_operating_costs_from_gross_profit() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}
    total = by_code["total_operating_costs"]

    assert total.statement == "IS"
    assert total.label == "Total operating costs"
    assert total.derive == "gross_profit - operating_income"
    assert total.parent is None
    assert total.concepts == ()
    assert {c for c, i in by_code.items() if i.parent == "total_operating_costs"} == {
        "rnd",
        "sga",
        "other_operating_expenses",
    }


def test_shipped_items_show_cost_of_revenue_as_its_own_row_above_gross_profit() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    position = {i.code: n for n, i in enumerate(items)}
    by_code = {i.code: i for i in items}

    assert by_code["cost_of_revenue"].parent is None
    assert by_code["gross_profit"].derive == "revenue - cost_of_revenue"
    assert position["revenue"] < position["cost_of_revenue"] < position["gross_profit"]
    assert not [i.code for i in items if i.parent == "gross_profit"]


def test_shipped_items_compute_free_cash_flow_from_operating_cash_and_capex() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}
    fcf = by_code["free_cash_flow"]

    assert fcf.statement == "CF"
    assert fcf.label == "Free cash flow"
    assert fcf.kind == "flow"
    assert fcf.derive == "cfo + capex"  # capex is displayed negative
    assert fcf.parent is None
    assert fcf.concepts == ()
    assert fcf.residual is False


def test_shipped_items_compute_total_debt_and_net_debt_on_the_balance_sheet() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}
    debt, net_debt = by_code["total_debt"], by_code["net_debt"]

    assert (debt.statement, debt.kind, debt.label) == ("BS", "instant", "Total debt")
    assert debt.derive == "short_term_debt + long_term_debt"
    assert (net_debt.statement, net_debt.kind, net_debt.label) == ("BS", "instant", "Net debt")
    assert net_debt.derive == "total_debt - cash - short_term_investments"
    for item in (debt, net_debt):
        assert item.parent is None
        assert item.concepts == ()
        assert item.residual is False


def test_shipped_items_add_the_four_m2_lines_where_the_erd_puts_them() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)
    codes = [i.code for i in items]
    by_code = {i.code: i for i in items}

    for code, statement, kind, unit in (
        ("dividends_per_share", "IS", "flow", "USD/shares"),
        ("goodwill_impairment", "IS", "flow", "USD"),
        ("temporary_equity", "BS", "instant", "USD"),
        ("shares_outstanding", "BS", "instant", "shares"),
    ):
        item = by_code[code]
        assert (item.statement, item.kind, item.unit) == (statement, kind, unit), code
        assert item.sign == 1 and item.parent is None, code
        assert item.concepts and not item.residual and item.derive is None, code
    assert codes.index("dividends_per_share") == codes.index("eps_diluted") + 1
    assert codes.index("goodwill_impairment") == codes.index("shares_diluted") + 1
    assert codes.index("temporary_equity") == codes.index("total_equity") - 1
    assert codes.index("shares_outstanding") == codes.index("net_debt") + 1
    assert by_code["dividends_per_share"].concepts == (
        "us-gaap:CommonStockDividendsPerShareDeclared",
        "us-gaap:CommonStockDividendsPerShareCashPaid",
    )


# Overrides can switch defaults off with the mapping form `code: {concepts: [...], exclude: ...}`.


def test_the_mapping_form_adds_concepts_and_excludes_defaults(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text(
        "revenue: {concepts: [Custom], exclude: [SalesRevenueNet]}\n"
        "gross_profit: {exclude: [us-gaap:GrossProfit]}\n"
        "cost_of_revenue: [OtherCost]\n"
    )

    assert load_overrides(tmp_path, "X", items) == {
        "revenue": ["us-gaap:Custom"],
        "cost_of_revenue": ["us-gaap:OtherCost"],
    }
    assert load_excludes(tmp_path, "X", items) == {
        "revenue": ["us-gaap:SalesRevenueNet"],
        "gross_profit": ["us-gaap:GrossProfit"],
    }


def test_exclude_all_drops_every_default_of_the_item(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text("revenue: {concepts: [], exclude: all}\n")

    assert load_excludes(tmp_path, "X", items) == {
        "revenue": ["us-gaap:Revenues", "us-gaap:SalesRevenueNet", "ifrs-full:Revenue"]
    }
    assert load_overrides(tmp_path, "X", items) == {}


def test_the_plain_list_form_excludes_nothing(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text("revenue: [Custom]\n")

    assert load_excludes(tmp_path, "X", items) == {}
    assert load_excludes(tmp_path / "missing", "X", items) == {}


def test_excluding_a_summed_default_matches_the_whole_entry(tmp_path: Path) -> None:
    summed = VALID.replace(
        "concepts: [CostOfRevenue]", 'concepts: ["CostOfRevenue + OtherCost", CostOfRevenue]'
    )
    items = load_canonical_items(write(tmp_path, summed))
    (tmp_path / "X.yaml").write_text('cost_of_revenue: {exclude: ["CostOfRevenue + OtherCost"]}\n')

    assert load_excludes(tmp_path, "X", items) == {
        "cost_of_revenue": ["us-gaap:CostOfRevenue + us-gaap:OtherCost"]
    }


@pytest.mark.parametrize(
    "text",
    [
        "revenue: {exclude: [Ghost]}\n",  # not a default of the item: a stale exclude
        "revenue: {exclude: [Revenues, us-gaap:Revenues]}\n",  # duplicate
        "revenue: {exclude: Revenues}\n",  # a string other than `all`
        "revenue: {exclude: [1]}\n",  # not a string
        "revenue: {exclude: []}\n",  # nothing to do
        "revenue: {concepts: [Revenues], exclude: [Revenues]}\n",  # added and excluded
        "revenue: {concept: [A]}\n",  # unknown key
        "revenue: {concepts: A}\n",  # concepts not a list
        "revenue: {}\n",  # empty mapping
        "revenue: 5\n",
        "ghost: {exclude: all}\n",  # unknown code
    ],
)
def test_malformed_or_stale_excludes_are_rejected(tmp_path: Path, text: str) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text(text)

    with pytest.raises(MappingConfigError):
        load_excludes(tmp_path, "X", items)


def test_residual_codes_cannot_be_excluded(tmp_path: Path) -> None:
    residual = VALID + (
        "- code: other_costs\n  statement: IS\n  label: Other\n  kind: flow\n  unit: USD\n"
        "  sign: 1\n  parent: null\n  derive: revenue - cost_of_revenue\n  residual: true\n"
    )
    items = load_canonical_items(write(tmp_path, residual))
    (tmp_path / "X.yaml").write_text("other_costs: {exclude: all}\n")

    with pytest.raises(MappingConfigError):
        load_excludes(tmp_path, "X", items)


def test_exclude_all_needs_a_default_to_drop(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID.replace("  concepts: [GrossProfit]\n", "")))
    (tmp_path / "X.yaml").write_text("gross_profit: {exclude: all}\n")

    with pytest.raises(MappingConfigError):
        load_excludes(tmp_path, "X", items)


# --- rolls_into: where a normalization adjustment propagates (M2) --------------------------------

ROLLS = """
- {code: revenue, statement: IS, label: Revenue, kind: flow, unit: USD, sign: 1,
   rolls_into: [gross_profit]}
- {code: cost_of_revenue, statement: IS, label: Cost, kind: flow, unit: USD, sign: 1,
   rolls_into: ["-gross_profit"]}
- {code: gross_profit, statement: IS, label: Gross, kind: flow, unit: USD, sign: 1}
- {code: eps, statement: IS, label: EPS, kind: average, unit: USD/shares, sign: 1}
- {code: cash, statement: BS, label: Cash, kind: instant, unit: USD, sign: 1, parent: current}
- {code: current, statement: BS, label: Current, kind: instant, unit: USD, sign: 1, parent: assets}
- {code: assets, statement: BS, label: Assets, kind: instant, unit: USD, sign: 1}
"""


def test_rolls_into_reads_signed_codes(tmp_path: Path) -> None:
    items = {i.code: i for i in load_canonical_items(write(tmp_path, ROLLS))}

    assert items["revenue"].rolls_into == (("gross_profit", 1),)
    assert items["cost_of_revenue"].rolls_into == (("gross_profit", -1),)
    assert items["gross_profit"].rolls_into == ()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("rolls_into: [gross_profit]}\n- {code: cost", "rolls_into: [nowhere]}\n- {code: cost"),
        ("rolls_into: [gross_profit]}\n- {code: cost", "rolls_into: [cash]}\n- {code: cost"),
        ("rolls_into: [gross_profit]}\n- {code: cost", "rolls_into: [eps]}\n- {code: cost"),
        ("rolls_into: [gross_profit]}\n- {code: cost", "rolls_into: [revenue]}\n- {code: cost"),
        (
            "rolls_into: [gross_profit]}\n- {code: cost",
            "rolls_into: [gross_profit, gross_profit]}\n- {code: cost",
        ),
        ("rolls_into: [gross_profit]}\n- {code: cost", "rolls_into: gross_profit}\n- {code: cost"),
        (
            "rolls_into: [gross_profit]}\n- {code: cost",
            "rolls_into: ['+gross_profit']}\n- {code: cost",
        ),
    ],
    ids=["unknown", "other-statement", "average-target", "self", "duplicate", "not-a-list", "plus"],
)
def test_rolls_into_rejects_invalid_targets(tmp_path: Path, old: str, new: str) -> None:
    error = fail_with(tmp_path, ROLLS.replace(old, new))

    assert error.code == "revenue"


def test_rolls_into_rejects_a_cycle(tmp_path: Path) -> None:
    error = fail_with(
        tmp_path,
        ROLLS.replace("sign: 1}\n- {code: eps", "sign: 1, rolls_into: [revenue]}\n- {code: eps"),
    )

    assert "cycle" in str(error)


def test_rolls_into_cycle_through_a_parent_is_rejected(tmp_path: Path) -> None:
    # assets -> cash, while cash propagates to its parent current -> assets
    error = fail_with(
        tmp_path,
        ROLLS.replace(
            "kind: instant, unit: USD, sign: 1}",
            "kind: instant, unit: USD, sign: 1, rolls_into: [cash]}",
        ),
    )

    assert "cycle" in str(error)


def test_propagation_targets_are_transitive_and_multiply_signs(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, ROLLS))

    assert propagation_targets(items, "revenue") == {"gross_profit": 1}
    assert propagation_targets(items, "cost_of_revenue") == {"gross_profit": -1}
    assert propagation_targets(items, "gross_profit") == {}


def test_balance_sheet_lines_fall_back_to_their_parent_chain(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, ROLLS))

    assert propagation_targets(items, "cash") == {"current": 1, "assets": 1}
    assert propagation_targets(items, "assets") == {}


def test_shipped_income_statement_propagates_down_the_waterfall() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    assert propagation_targets(items, "sga") == {
        "operating_income": -1,
        "pretax_income": -1,
        "net_income": -1,
        "net_income_common": -1,
    }
    assert propagation_targets(items, "revenue") == {
        "gross_profit": 1,
        "operating_income": 1,
        "pretax_income": 1,
        "net_income": 1,
        "net_income_common": 1,
    }
    assert propagation_targets(items, "cost_of_revenue")["operating_income"] == -1
    assert propagation_targets(items, "interest_expense") == {
        "pretax_income": -1,
        "net_income": -1,
        "net_income_common": -1,
    }
    assert propagation_targets(items, "income_tax") == {"net_income": -1, "net_income_common": -1}
    assert propagation_targets(items, "net_income_nci") == {"net_income_common": -1}
    assert propagation_targets(items, "net_income_common") == {}


def test_shipped_balance_sheet_and_cash_flow_propagate_through_their_parents() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    assert propagation_targets(items, "cash") == {
        "total_current_assets": 1,
        "total_assets": 1,
    }
    assert propagation_targets(items, "long_term_debt") == {
        "total_noncurrent_liabilities": 1,
        "total_liabilities": 1,
        "total_liabilities_and_equity": 1,
    }
    assert propagation_targets(items, "retained_earnings") == {
        "equity_parent": 1,
        "total_equity": 1,
        "total_liabilities_and_equity": 1,
    }
    assert propagation_targets(items, "temporary_equity") == {"total_liabilities_and_equity": 1}
    assert propagation_targets(items, "capex") == {"cfi": 1, "net_change_in_cash": 1}
    assert propagation_targets(items, "d_and_a") == {"cfo": 1, "net_change_in_cash": 1}
    assert propagation_targets(items, "fx_effect") == {"net_change_in_cash": 1}


def test_is_adjustable_follows_the_erd_rules() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}

    adjustable = {c for c, i in by_code.items() if is_adjustable(i)}

    for code in (
        "revenue",
        "sga",
        "other_operating_expenses",
        "cash",
        "other_current_assets",
        "capex",
        "cfo",
        "total_assets",
    ):
        assert code in adjustable, code
    for code in (  # computed-only, memo, per-share and share lines
        "total_operating_costs", "total_noncurrent_assets", "total_noncurrent_liabilities",
        "total_debt", "net_debt", "free_cash_flow", "goodwill_impairment",
        "eps_basic", "eps_diluted", "dividends_per_share", "shares_basic", "shares_diluted",
        "shares_outstanding",
    ):  # fmt: skip
        assert code not in adjustable, code
