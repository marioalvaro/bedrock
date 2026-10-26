"""The `identities:` section of canonical_items.yaml (docs/erd/data.md "R1: identities")."""

from decimal import Decimal
from pathlib import Path

import pytest

from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    IdentityDef,
    MappingConfigError,
    SolveRule,
    load_canonical_items,
    load_identities,
)

COMMON = "kind: flow, unit: USD, sign: 1"
ITEMS = f"""
items:
  - {{code: revenue, statement: IS, label: Revenue, {COMMON}, concepts: [Revenues]}}
  - {{code: cost_of_revenue, statement: IS, label: Cost, {COMMON}, concepts: [Cost]}}
  - {{code: gross_profit, statement: IS, label: Gross, {COMMON}, concepts: [GrossProfit]}}
  - {{code: other, statement: IS, label: Other, {COMMON}, derive: "gross_profit - revenue",
     residual: true}}
  - {{code: total_assets, statement: BS, label: Assets, kind: instant, unit: USD, sign: 1,
     concepts: [Assets]}}
"""

GROSS_PROFIT = """
identities:
  - id: gross_profit
    equation: gross_profit = revenue - cost_of_revenue
    solve: {cost_of_revenue: {mode: exact}}
"""


def write(tmp_path: Path, identities: str, items: str = ITEMS) -> Path:
    path = tmp_path / "items.yaml"
    path.write_text(items + identities)
    return path


def load(tmp_path: Path, identities: str) -> list[IdentityDef]:
    path = write(tmp_path, identities)
    return load_identities(path, load_canonical_items(path))


def test_an_identity_loads_with_its_terms_and_solve_rules(tmp_path: Path) -> None:
    [identity] = load(tmp_path, GROSS_PROFIT)

    assert identity.id == "gross_profit"
    assert identity.equation == "gross_profit = revenue - cost_of_revenue"
    # moved to one side: sum(coefficient * value) = 0
    assert identity.terms == ((1, "gross_profit"), (-1, "revenue"), (1, "cost_of_revenue"))
    assert identity.solve == {"cost_of_revenue": SolveRule("exact", None)}


def test_a_bounded_rule_keeps_its_max_ratio_as_a_decimal(tmp_path: Path) -> None:
    [identity] = load(
        tmp_path,
        """
identities:
  - id: gp
    equation: gross_profit = revenue - cost_of_revenue
    solve: {cost_of_revenue: {mode: bounded, max_ratio: 0.05}}
""",
    )

    assert identity.solve["cost_of_revenue"] == SolveRule("bounded", Decimal("0.05"))


def test_the_items_file_may_stay_a_plain_list_without_identities(tmp_path: Path) -> None:
    path = tmp_path / "items.yaml"
    path.write_text("- {code: revenue, statement: IS, label: R, kind: flow, unit: USD, sign: 1}\n")

    assert [i.code for i in load_canonical_items(path)] == ["revenue"]
    assert load_identities(path, load_canonical_items(path)) == []


def test_the_mapping_form_loads_its_items(tmp_path: Path) -> None:
    path = write(tmp_path, GROSS_PROFIT)

    assert [i.code for i in load_canonical_items(path)][:2] == ["revenue", "cost_of_revenue"]


@pytest.mark.parametrize(
    ("identities", "message"),
    [
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - nope
    solve: {revenue: {mode: exact}}
""",
            "unknown code 'nope'",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - total_assets
    solve: {revenue: {mode: exact}}
""",
            "another statement",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit revenue
    solve: {revenue: {mode: exact}}
""",
            "malformed equation",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue = cost_of_revenue
    solve: {revenue: {mode: exact}}
""",
            "malformed equation",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - -cost_of_revenue
    solve: {revenue: {mode: exact}}
""",
            "malformed equation",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = gross_profit - cost_of_revenue
    solve: {revenue: {mode: exact}}
""",
            "repeated term",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {total_assets: {mode: exact}}
""",
            "not a term",
        ),
        (
            """
identities:
  - id: x
    equation: other = gross_profit - revenue
    solve: {other: {mode: exact}}
""",
            "residual",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {revenue: {mode: guess}}
""",
            "unknown mode 'guess'",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {revenue: {mode: bounded}}
""",
            "max_ratio",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {revenue: {mode: bounded, max_ratio: 0}}
""",
            "max_ratio",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {revenue: {mode: exact, speed: 3}}
""",
            "unknown key",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {}
""",
            "solve",
        ),
        (
            """
identities:
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {revenue: {mode: exact}}
  - id: x
    equation: gross_profit = revenue - cost_of_revenue
    solve: {revenue: {mode: exact}}
""",
            "duplicate identity id",
        ),
        (
            """
identities:
  - equation: gross_profit = revenue - cost_of_revenue
    solve: {revenue: {mode: exact}}
""",
            "id",
        ),
        (
            """
identities:
  - id: x
    solve: {revenue: {mode: exact}}
""",
            "equation",
        ),
    ],
)
def test_a_bad_identity_is_a_load_error(tmp_path: Path, identities: str, message: str) -> None:
    path = write(tmp_path, identities)
    items = load_canonical_items(path)

    with pytest.raises(MappingConfigError, match=message):
        load_identities(path, items)


def test_the_shipped_file_loads_the_seven_identities_of_the_erd() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    identities = load_identities(DEFAULT_ITEMS_PATH, items)

    assert [i.id for i in identities] == [
        "cash_rollforward",
        "gross_profit",
        "equity_split",
        "net_income_split",
        "balance_sheet",
        "total_assets_equals_le",
        "shares_outstanding_count",
    ]
    by_id = {i.id: i for i in identities}
    assert by_id["cash_rollforward"].solve == {"fx_effect": SolveRule("bounded", Decimal("0.05"))}
    assert by_id["equity_split"].solve == {
        "nci": SolveRule("zero_only", None),
        "equity_parent": SolveRule("exact", None),
    }
    assert by_id["balance_sheet"].solve == {"temporary_equity": SolveRule("zero_only", None)}
    assert by_id["shares_outstanding_count"].terms == (
        (1, "shares_outstanding"),
        (-1, "shares_issued"),
        (1, "treasury_shares"),
    )
    assert by_id["shares_outstanding_count"].solve == {
        "shares_outstanding": SolveRule("exact", None)
    }
