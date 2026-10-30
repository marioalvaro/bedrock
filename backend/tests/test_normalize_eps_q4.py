"""Normalized Q4 and TTM EPS (docs/erd/data.md "R2"): Q4 EPS is rebuilt from Q4 net income and
Q4 shares, so an adjustment moves it like any other quarter; TTM sums the normalized quarters."""

from dataclasses import dataclass
from decimal import Decimal

from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.build import StatementTable, build_statement
from tests.average_data import ITEMS, JUNE, MAPS, M, eps, income, shares
from tests.engine_data import facts


@dataclass(frozen=True)
class Adj:
    id: int
    canonical_code: str
    fiscal_year: int
    fiscal_period: str
    amount: Decimal


FRAME = map_facts(
    select_vintage(
        facts(
            income(JUNE)
            + shares("shares_diluted", JUNE, 100 * M, (100 * M, 100 * M, 100 * M))
            + eps("eps_diluted", JUNE, "4.00", ("1.00", "1.00", "1.00"))
        )
    ),
    MAPS,
    ITEMS,
)  # type: ignore[arg-type]


def table(freq: str, *adjustments: Adj) -> StatementTable:
    return build_statement(FRAME, ITEMS, "IS", freq, adjustments=adjustments)  # type: ignore[arg-type]


def series(t: StatementTable, code: str) -> dict[str, Decimal | None]:
    row = next(r for r in t.rows if r.code == code)
    return {p.key: v for p, v in zip(t.periods, row.values, strict=True)}


def provenance(t: StatementTable, code: str) -> dict[str, str | None]:
    row = next(r for r in t.rows if r.code == code)
    return {p.key: v for p, v in zip(t.periods, row.provenance, strict=True)}


# +50 M to Q4 net income common, over the 100 M shares of Q4
Q4_ADJUSTMENT = Adj(1, "net_income_common", 2023, "Q4", Decimal(50 * M))


def test_q4_eps_moves_by_the_change_in_q4_net_income_over_q4_shares() -> None:
    quarterly = table("quarterly", Q4_ADJUSTMENT)

    assert series(quarterly, "eps_diluted")["FY2023Q4"] == Decimal("1.5")  # 1.00 + 50 M / 100 M
    assert provenance(quarterly, "eps_diluted")["FY2023Q4"] == "normalized"
    assert provenance(quarterly, "eps_diluted")["FY2023Q3"] == "reported"


def test_normalized_q4_eps_is_unchanged_by_an_adjustment_to_another_quarter() -> None:
    quarterly = table("quarterly", Adj(1, "net_income_common", 2023, "Q1", Decimal(50 * M)))

    assert series(quarterly, "eps_diluted")["FY2023Q4"] == Decimal(1)
    assert provenance(quarterly, "eps_diluted")["FY2023Q4"] == "approximated"


def test_ttm_eps_sums_the_normalized_quarters() -> None:
    ttm = table("ttm", Q4_ADJUSTMENT)

    assert series(ttm, "eps_diluted") == {"TTM-FY2023Q4": Decimal("4.5")}
    assert provenance(ttm, "eps_diluted") == {"TTM-FY2023Q4": "normalized"}


def test_the_reported_basis_ignores_the_adjustment() -> None:
    assert series(table("ttm"), "eps_diluted") == {"TTM-FY2023Q4": Decimal(4)}
    assert provenance(table("ttm"), "eps_diluted") == {"TTM-FY2023Q4": "approximated"}
