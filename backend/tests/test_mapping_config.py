from pathlib import Path

import pytest

from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    MEMO_CODES,
    CanonicalItemDef,
    MappingConfigError,
    formula_order,
    is_adjustable,
    load_canonical_items,
    load_excludes,
    load_other_lines,
    load_overrides,
    parse_formula,
    propagation_targets,
    signed_members,
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


# M7b S3: signed members (docs/erd/data-coverage.md "Signed members")
@pytest.mark.parametrize(
    ("entry", "members"),
    [
        ("A - B", [(1, "us-gaap", "A"), (-1, "us-gaap", "B")]),
        ("-A", [(-1, "us-gaap", "A")]),
        ("- A", [(-1, "us-gaap", "A")]),
        ("A + B - C", [(1, "us-gaap", "A"), (1, "us-gaap", "B"), (-1, "us-gaap", "C")]),
        ("-us-gaap:A + B", [(-1, "us-gaap", "A"), (1, "us-gaap", "B")]),
        ("ifrs-full:A - ifrs-full:B", [(1, "ifrs-full", "A"), (-1, "ifrs-full", "B")]),
        ("A+B", [(1, "us-gaap", "A"), (1, "us-gaap", "B")]),
    ],
)
def test_signed_members_give_each_member_its_weight_anchor_first(
    entry: str, members: list[tuple[int, str, str]]
) -> None:
    assert signed_members(entry) == members
    assert split_group(entry) == [(t, c) for _, t, c in members]


def test_signed_entries_are_qualified_with_their_signs(tmp_path: Path) -> None:
    text = VALID.replace(
        "concepts: [CostOfRevenue]",
        'concepts: ["CostOfRevenue - OtherCost", "-Foo", "A + B - C", "- Bar + Baz"]',
    )

    items = {i.code: i for i in load_canonical_items(write(tmp_path, text))}

    assert items["cost_of_revenue"].concepts == (
        "us-gaap:CostOfRevenue - us-gaap:OtherCost",
        "-us-gaap:Foo",
        "us-gaap:A + us-gaap:B - us-gaap:C",
        "-us-gaap:Bar + us-gaap:Baz",
    )
    assert all(
        signed_members(entry) == signed_members(original)
        for entry, original in zip(
            items["cost_of_revenue"].concepts,
            ["CostOfRevenue - OtherCost", "-Foo", "A + B - C", "- Bar + Baz"],
            strict=True,
        )
    )  # the qualified text parses back to the same members


@pytest.mark.parametrize(
    "entry",
    [
        "A - A",  # a member twice, whatever its sign
        "A + B - A",
        "A - ",  # empty member
        "A - - B",
        "-",
        "A -B",  # a sign needs a space on both sides, or it is part of a name
        "A - aapl:B",  # mixed taxonomies
        "A  B",  # whitespace inside a name
        "A + -B",  # a sign inside a member: `-B` would be a name and never match a fact
        "A+-B",
        "A - +B",
        "us-gaap:-A",
    ],
)
def test_a_malformed_signed_entry_is_rejected(tmp_path: Path, entry: str) -> None:
    error = fail_with(tmp_path, VALID.replace("[CostOfRevenue]", f'["{entry}"]'))

    assert error.code == "cost_of_revenue"


def test_a_signed_override_is_qualified_like_a_default(tmp_path: Path) -> None:
    (tmp_path / "ACME.yaml").write_text('cost_of_revenue: ["CostOfRevenue - Rebates"]\n')

    assert load_overrides(tmp_path, "ACME") == {
        "cost_of_revenue": ["us-gaap:CostOfRevenue - us-gaap:Rebates"]
    }


def test_a_signed_default_can_be_excluded_by_its_text(tmp_path: Path) -> None:
    items = load_canonical_items(
        write(tmp_path, VALID.replace("[CostOfRevenue]", '["CostOfRevenue - Rebates", Other]'))
    )
    (tmp_path / "ACME.yaml").write_text(
        'cost_of_revenue: {exclude: ["CostOfRevenue - us-gaap:Rebates"]}\n'
    )

    assert load_excludes(tmp_path, "ACME", items) == {
        "cost_of_revenue": ["us-gaap:CostOfRevenue - us-gaap:Rebates"]
    }


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


def test_shipped_canonical_items_load_with_95_codes() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    assert len(items) == 95  # M7b S4 adds the four scope totals, S5 the seven new rows
    assert {i.statement for i in items} == {"IS", "BS", "CF"}
    by_code = {i.code: i for i in items}
    assert by_code["eps_diluted"].kind == "average"
    assert by_code["eps_diluted"].unit == "USD/shares"
    assert by_code["capex"].sign == -1
    assert by_code["other_current_assets"].residual is True
    assert by_code["cash"].parent == "total_current_assets"
    for code, concepts in (
        ("shares_issued", ["us-gaap:CommonStockSharesIssued"]),
        (
            "treasury_shares",
            ["us-gaap:TreasuryStockCommonShares", "us-gaap:TreasuryStockShares"],
        ),
    ):
        assert (by_code[code].statement, by_code[code].kind, by_code[code].unit) == (
            "BS",
            "instant",
            "shares",
        )
        assert list(by_code[code].concepts) == concepts
        assert by_code[code].parent is None
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


# --- M7b S2: lines a standard introduced (docs/erd/data-coverage.md, "Coverage semantics") ----


def test_starts_with_standard_defaults_to_false_and_reads_true(tmp_path: Path) -> None:
    text = VALID.replace(
        "concepts: [CostOfRevenue]", "concepts: [CostOfRevenue]\n  starts_with_standard: true"
    )

    items = {i.code: i for i in load_canonical_items(write(tmp_path, text))}

    assert items["cost_of_revenue"].starts_with_standard is True
    assert items["revenue"].starts_with_standard is False


@pytest.mark.parametrize("value", ['"yes"', "1", "null"])
def test_starts_with_standard_must_be_a_bool(tmp_path: Path, value: str) -> None:
    text = VALID.replace(
        "concepts: [CostOfRevenue]", f"concepts: [CostOfRevenue]\n  starts_with_standard: {value}"
    )

    error = fail_with(tmp_path, text)

    assert error.code == "cost_of_revenue"
    assert "starts_with_standard" in str(error)


def test_starts_with_standard_is_rejected_on_a_computed_item(tmp_path: Path) -> None:
    text = VALID.replace(
        "derive: revenue - cost_of_revenue",
        "derive: revenue - cost_of_revenue\n  starts_with_standard: true",
    )

    assert fail_with(tmp_path, text).code == "gross_profit"


def test_starts_with_standard_is_rejected_on_a_residual(tmp_path: Path) -> None:
    text = """
- code: other_current_assets
  statement: BS
  label: Other
  kind: instant
  unit: USD
  sign: 1
  residual: true
  derive: total_current_assets - cash
  starts_with_standard: true
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
    assert fail_with(tmp_path, text).code == "other_current_assets"


def test_shipped_items_mark_the_two_lease_lines_as_starting_with_a_standard() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    assert {i.code for i in items if i.starts_with_standard} == {
        "operating_lease_rou",
        "operating_lease_liabilities_noncurrent",
    }


# --- M7b S4: combined lines ------------------------------------------------------------------

COMBINED = """
- code: total_current_liabilities
  statement: BS
  label: Total current liabilities
  kind: instant
  unit: USD
  sign: 1
  parent: null
  concepts: [LiabilitiesCurrent]
- code: accounts_payable
  statement: BS
  label: Accounts payable
  kind: instant
  unit: USD
  sign: 1
  parent: total_current_liabilities
  concepts:
    - AccountsPayableCurrent
    - {concept: AccountsPayableAndAccruedLiabilitiesCurrent, covers: [accrued_liabilities]}
- code: accrued_liabilities
  statement: BS
  label: Accrued liabilities
  kind: instant
  unit: USD
  sign: 1
  parent: total_current_liabilities
  concepts: [AccruedLiabilitiesCurrent]
- code: other_current_liabilities
  statement: BS
  label: Other current liabilities
  kind: instant
  unit: USD
  sign: 1
  parent: total_current_liabilities
  concepts: []
  derive: total_current_liabilities - accounts_payable - accrued_liabilities
  residual: true
- code: revenue
  statement: IS
  label: Revenue
  kind: flow
  unit: USD
  sign: 1
  parent: null
  concepts: [Revenues]
- code: change_payables
  statement: CF
  label: Change in payables
  kind: flow
  unit: USD
  sign: 1
  parent: null
  concepts: [IncreaseDecreaseInAccountsPayable]
"""

AP_COMBINED = (
    "    - {concept: AccountsPayableAndAccruedLiabilitiesCurrent, covers: [accrued_liabilities]}"
)


def test_a_combined_entry_is_a_concept_with_the_codes_it_covers(tmp_path: Path) -> None:
    items = {i.code: i for i in load_canonical_items(write(tmp_path, COMBINED))}
    payable = items["accounts_payable"]
    assert payable.concepts == (
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccountsPayableAndAccruedLiabilitiesCurrent",
    )
    assert payable.covers == (
        ("us-gaap:AccountsPayableAndAccruedLiabilitiesCurrent", ("accrued_liabilities",)),
    )
    assert items["accrued_liabilities"].covers == ()


def test_a_combined_entry_may_cover_no_row(tmp_path: Path) -> None:
    text = COMBINED.replace(
        "  concepts: [IncreaseDecreaseInAccountsPayable]",
        "  concepts:\n    - IncreaseDecreaseInAccountsPayable\n"
        "    - {concept: IncreaseDecreaseInAccountsPayableAndAccruedLiabilities, covers: []}",
    )
    items = {i.code: i for i in load_canonical_items(write(tmp_path, text))}
    assert items["change_payables"].covers == (
        ("us-gaap:IncreaseDecreaseInAccountsPayableAndAccruedLiabilities", ()),
    )


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        # a plain entry after a combined one
        (f"{AP_COMBINED}\n    - AccountsPayableTradeCurrent", "after every plain entry"),
        # a sum cannot be combined
        (
            "    - {concept: 'AccountsPayableCurrent + OtherLiabilitiesCurrent', "
            "covers: [accrued_liabilities]}",
            "single concept",
        ),
        ("    - {concept: X, covers: [accounts_payable]}", "itself"),
        ("    - {concept: X, covers: [other_current_liabilities]}", "residual"),
        ("    - {concept: X, covers: [revenue]}", "same statement"),
        ("    - {concept: X, covers: [unknown_code]}", "unknown"),
        ("    - {concept: X, covers: [accrued_liabilities, accrued_liabilities]}", "twice"),
        ("    - {concept: X}", "covers"),
        ("    - {concept: X, covers: accrued_liabilities}", "list"),
        ("    - {concept: X, covers: [], extra: 1}", "covers"),
        ("    - {covers: []}", "concept"),
        ("    - 7", "concept"),
    ],
)
def test_a_malformed_combined_entry_is_rejected(tmp_path: Path, entry: str, message: str) -> None:
    text = COMBINED.replace(AP_COMBINED, entry)
    with pytest.raises(MappingConfigError, match=message):
        load_canonical_items(write(tmp_path, text))


def test_a_covered_code_has_the_carriers_kind(tmp_path: Path) -> None:
    text = COMBINED.replace(
        "  concepts: [Revenues]",
        "  concepts: [Revenues]\n- code: change_accrued\n"
        "  statement: BS\n  label: x\n  kind: flow\n  unit: USD\n  sign: 1\n  parent: null\n"
        "  concepts: [Y]",
    ).replace("covers: [accrued_liabilities]}", "covers: [change_accrued]}")
    with pytest.raises(MappingConfigError, match="kind"):
        load_canonical_items(write(tmp_path, text))


def test_an_override_cannot_hold_a_combined_entry(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, COMBINED))
    (tmp_path / "ACME.yaml").write_text(
        "accounts_payable:\n  - {concept: X, covers: [accrued_liabilities]}\n"
    )
    with pytest.raises(MappingConfigError, match="override"):
        load_overrides(tmp_path, "ACME", items)


def test_a_combined_default_can_be_excluded_by_its_concept(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, COMBINED))
    (tmp_path / "ACME.yaml").write_text(
        "accounts_payable:\n  exclude: [AccountsPayableAndAccruedLiabilitiesCurrent]\n"
    )
    assert load_excludes(tmp_path, "ACME", items) == {
        "accounts_payable": ["us-gaap:AccountsPayableAndAccruedLiabilitiesCurrent"]
    }


# --- M7b S5: new rows folded back into their residual for the forecast (docs/erd/data-coverage.md,
# "New canonical rows") ---------------------------------------------------------------------------

FOLD = """
- code: total_current_assets
  statement: BS
  label: Total current assets
  kind: instant
  unit: USD
  sign: 1
  concepts: [AssetsCurrent]
- code: cash
  statement: BS
  label: Cash
  kind: instant
  unit: USD
  sign: 1
  parent: total_current_assets
  concepts: [Cash]
- code: prepaid
  statement: BS
  label: Prepaid
  kind: instant
  unit: USD
  sign: 1
  parent: total_current_assets
  concepts: [PrepaidExpenseCurrent]
  forecast_fold: other_current_assets
- code: other_current_assets
  statement: BS
  label: Other current assets
  kind: instant
  unit: USD
  sign: 1
  parent: total_current_assets
  residual: true
  derive: total_current_assets - cash - prepaid
- code: revenue
  statement: IS
  label: Revenue
  kind: flow
  unit: USD
  sign: 1
  concepts: [Revenues]
- code: other_income
  statement: IS
  label: Other
  kind: flow
  unit: USD
  sign: 1
  residual: true
  derive: revenue
"""


def test_forecast_fold_names_the_residual_a_new_row_folds_into(tmp_path: Path) -> None:
    items = {i.code: i for i in load_canonical_items(write(tmp_path, FOLD))}

    assert items["prepaid"].forecast_fold == "other_current_assets"
    assert items["cash"].forecast_fold is None


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        # not a code
        ("forecast_fold: other_current_assets", "forecast_fold: [other_current_assets]", "prepaid"),
        # an unknown code
        ("forecast_fold: other_current_assets", "forecast_fold: nowhere", "prepaid"),
        # not a residual
        ("forecast_fold: other_current_assets", "forecast_fold: cash", "prepaid"),
        # a residual on another statement
        ("forecast_fold: other_current_assets", "forecast_fold: other_income", "prepaid"),
        # a residual whose formula does not hold the row
        (
            "derive: total_current_assets - cash - prepaid",
            "derive: total_current_assets - cash",
            "prepaid",
        ),
        # a row with no parent (a memo row)
        (
            "parent: total_current_assets\n  concepts: [PrepaidExpenseCurrent]",
            "concepts: [PrepaidExpenseCurrent]",
            "prepaid",
        ),
        # a computed row
        ("concepts: [PrepaidExpenseCurrent]", "derive: cash", "prepaid"),
    ],
)  # fmt: skip
def test_a_misplaced_forecast_fold_is_rejected(
    tmp_path: Path, old: str, new: str, code: str
) -> None:
    assert old in FOLD
    error = fail_with(tmp_path, FOLD.replace(old, new))

    assert error.code == code
    assert "forecast_fold" in str(error)


def test_forecast_fold_is_rejected_on_a_residual(tmp_path: Path) -> None:
    text = FOLD.replace(
        "derive: total_current_assets - cash - prepaid",
        "derive: total_current_assets - cash - prepaid\n  forecast_fold: other_current_assets",
    )

    error = fail_with(tmp_path, text)

    assert error.code == "other_current_assets"
    assert "forecast_fold" in str(error)


S5_ROWS = {  # code: (statement, parent, forecast_fold)
    "interest_income": ("IS", "pretax_income", "other_nonoperating_income"),
    "deferred_tax_assets": ("BS", "total_noncurrent_assets", "other_noncurrent_assets"),
    "deferred_revenue_noncurrent": (
        "BS",
        "total_noncurrent_liabilities",
        "other_noncurrent_liabilities",
    ),
    "deferred_tax_liabilities": (
        "BS",
        "total_noncurrent_liabilities",
        "other_noncurrent_liabilities",
    ),
    "pension_liabilities": ("BS", "total_noncurrent_liabilities", "other_noncurrent_liabilities"),
    "cash_taxes_paid": ("CF", None, None),
    "cash_interest_paid": ("CF", None, None),
}


def test_shipped_items_add_the_s5_rows_under_their_parents_folded_for_the_forecast() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}

    for code, (statement, parent, fold) in S5_ROWS.items():
        assert (by_code[code].statement, by_code[code].parent) == (statement, parent), code
        assert by_code[code].forecast_fold == fold, code
        assert by_code[code].unit == "USD" and by_code[code].concepts, code
    # only the S5 rows fold: the forecast models every other row
    assert {c for c, i in by_code.items() if i.forecast_fold} == {
        c for c, (_, _, fold) in S5_ROWS.items() if fold
    }


def test_the_s5_memo_rows_are_memo_codes_and_never_adjustable() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}

    assert {"cash_taxes_paid", "cash_interest_paid"} <= MEMO_CODES
    assert not is_adjustable(by_code["cash_taxes_paid"])
    assert not is_adjustable(by_code["cash_interest_paid"])
    assert by_code["cash_taxes_paid"].kind == by_code["cash_interest_paid"].kind == "flow"


def test_the_residuals_take_the_s5_rows_out() -> None:
    by_code = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}

    assert by_code["other_nonoperating_income"].derive == (
        "pretax_income - operating_income + interest_expense - interest_income"
    )
    assert by_code["other_noncurrent_assets"].derive == (
        "total_noncurrent_assets - ppe_net - operating_lease_rou - goodwill - intangibles"
        " - long_term_investments - deferred_tax_assets"
    )
    assert by_code["other_noncurrent_liabilities"].derive == (
        "total_noncurrent_liabilities - long_term_debt - operating_lease_liabilities_noncurrent"
        " - deferred_revenue_noncurrent - deferred_tax_liabilities - pension_liabilities"
    )
    assert by_code["interest_income"].rolls_into == (("pretax_income", 1),)


# --- M7b S5 (user, 2026-11-14): `required`, a line every company has: a gap even if never reported


def test_required_defaults_to_false_and_reads_true(tmp_path: Path) -> None:
    text = VALID.replace("concepts: [CostOfRevenue]", "concepts: [CostOfRevenue]\n  required: true")

    items = {i.code: i for i in load_canonical_items(write(tmp_path, text))}

    assert items["cost_of_revenue"].required is True
    assert items["revenue"].required is False


@pytest.mark.parametrize("value", ["maybe", "1", "[true]"])  # YAML reads `yes` as true
def test_required_must_be_a_bool(tmp_path: Path, value: str) -> None:
    text = VALID.replace(
        "concepts: [CostOfRevenue]", f"concepts: [CostOfRevenue]\n  required: {value}"
    )

    error = fail_with(tmp_path, text)

    assert error.code == "cost_of_revenue" and "required" in str(error)


def test_required_is_rejected_on_a_residual(tmp_path: Path) -> None:
    text = FOLD.replace(
        "derive: total_current_assets - cash - prepaid",
        "derive: total_current_assets - cash - prepaid\n  required: true",
    )

    error = fail_with(tmp_path, text)

    assert error.code == "other_current_assets" and "required" in str(error)


REQUIRED = {
    "revenue", "cost_of_revenue", "gross_profit", "operating_income", "interest_expense",
    "pretax_income", "income_tax", "net_income", "eps_diluted", "shares_diluted",
    "cash", "total_assets", "short_term_debt", "long_term_debt", "total_debt",
    "total_liabilities", "total_equity",
    "cfo", "capex", "cfi", "cff", "free_cash_flow",
}  # fmt: skip


def test_the_shipped_required_lines_are_the_basic_ones() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    assert {i.code for i in items if i.required} == REQUIRED


# M7b S7: structure-rule fields (docs/erd/data-coverage.md "Structure rules")
STRUCTURE = (
    VALID
    + """
- code: opex
  statement: IS
  label: Opex
  kind: flow
  unit: USD
  sign: 1
  parent: gross_profit
  concepts: [OperatingExpenses]
  face_members: [SellingExpense, "us-gaap:MarketingExpense"]
  zero_when_absent: false
"""
)


def test_face_members_and_zero_when_absent_are_read(tmp_path: Path) -> None:
    items = {i.code: i for i in load_canonical_items(write(tmp_path, STRUCTURE))}

    assert items["opex"].face_members == ("us-gaap:SellingExpense", "us-gaap:MarketingExpense")
    assert items["opex"].zero_when_absent is False
    assert items["revenue"].face_members == ()
    assert items["revenue"].zero_when_absent is True


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # a face member that is a default concept of another item
        ("face_members: [SellingExpense", "face_members: [CostOfRevenue"),
        # a sum is not a face member: each member is one line
        ("face_members: [SellingExpense", 'face_members: ["SellingExpense + Foo"'),
        ('"us-gaap:MarketingExpense"]', '"us-gaap:SellingExpense"]'),  # twice
        (
            'face_members: [SellingExpense, "us-gaap:MarketingExpense"]',
            "face_members: Foo",
        ),  # not a list
        ("zero_when_absent: false", "zero_when_absent: no-thanks"),
        ("zero_when_absent: false", "zero_when_absnt: false"),  # an unknown key
    ],
)
def test_malformed_structure_fields_are_rejected(tmp_path: Path, old: str, new: str) -> None:
    error = fail_with(tmp_path, STRUCTURE.replace(old, new))

    assert error.code == "opex"


def test_face_members_on_a_computed_or_residual_item_are_rejected(tmp_path: Path) -> None:
    computed = VALID.replace(
        "  derive: revenue - cost_of_revenue",
        "  derive: revenue - cost_of_revenue\n  face_members: [Foo]",
    )
    assert fail_with(tmp_path, computed).code == "gross_profit"
    residual = (
        VALID
        + """
- code: other_cost
  statement: IS
  label: Other
  kind: flow
  unit: USD
  sign: 1
  parent: gross_profit
  residual: true
  derive: gross_profit - revenue
  face_members: [Foo]
"""
    )
    assert fail_with(tmp_path, residual).code == "other_cost"


def test_the_shipped_items_have_face_members_for_the_eight_first_items() -> None:
    items = {i.code: i for i in load_canonical_items(DEFAULT_ITEMS_PATH)}

    with_members = {code for code, item in items.items() if item.face_members}
    assert with_members == {
        "short_term_debt",
        "long_term_debt",
        "sga",
        "debt_issued",
        "debt_repaid",
        "sales_maturities_of_investments",
        "purchases_of_investments",
        "d_and_a",
    }


def test_other_lines_are_read_from_the_override_file(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text("revenue: [x:Rev]\nother_lines: [x:Gain, 'x:OtherCharge']\n")

    assert load_other_lines(tmp_path, "x") == (("x", "Gain"), ("x", "OtherCharge"))
    assert load_overrides(tmp_path, "X", items) == {"revenue": ["x:Rev"]}  # not a code
    assert load_other_lines(tmp_path, "NOFILE") == ()


@pytest.mark.parametrize(
    "text",
    [
        "other_lines: x:Gain\n",  # not a list
        "other_lines: ['x:A + x:B']\n",  # a sum
        "other_lines: [x:Gain, x:Gain]\n",  # twice
        "other_lines: [OtherNonoperatingIncome]\n",  # a us-gaap line has a triage verdict instead
    ],
)
def test_malformed_other_lines_are_rejected(tmp_path: Path, text: str) -> None:
    (tmp_path / "X.yaml").write_text(text)

    with pytest.raises(MappingConfigError):
        load_other_lines(tmp_path, "X")


def test_an_override_sum_may_join_us_gaap_and_the_company_extension(tmp_path: Path) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text('revenue: ["x:Sales + us-gaap:OtherRevenue"]\n')

    assert load_overrides(tmp_path, "X", items) == {"revenue": ["x:Sales + us-gaap:OtherRevenue"]}


@pytest.mark.parametrize("entry", ["x:A + y:B", "x:A + y:B + us-gaap:C", "x:A + dei:B"])
def test_an_override_sum_of_two_extensions_is_rejected(tmp_path: Path, entry: str) -> None:
    items = load_canonical_items(write(tmp_path, VALID))
    (tmp_path / "X.yaml").write_text(f'revenue: ["{entry}"]\n')

    with pytest.raises(MappingConfigError):
        load_overrides(tmp_path, "X", items)


def test_a_face_member_may_be_the_concept_of_a_support_line(tmp_path: Path) -> None:
    support = (
        STRUCTURE
        + """
- code: long_term_debt_current
  statement: IS
  label: Support
  kind: flow
  unit: USD
  sign: 1
  parent: null
  concepts: [SellingExpense]
"""
    )  # a support line only feeds an identity: it is no line on the face

    items = {i.code: i for i in load_canonical_items(write(tmp_path, support))}

    assert "us-gaap:SellingExpense" in items["opex"].face_members
