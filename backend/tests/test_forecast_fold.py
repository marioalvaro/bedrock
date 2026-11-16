"""M7b S5: new canonical rows are folded back into their residual for the forecast
(docs/erd/data-coverage.md "New canonical rows"), so the forecast reads the history it read before
the rows existed."""

from datetime import date
from decimal import Decimal

import pytest

from bedrock.forecast.history import fold_rows
from bedrock.mapping.config import MEMO_CODES, CanonicalItemDef, load_canonical_items
from bedrock.statements.build import Row, StatementTable
from bedrock.statements.periods import Period
from tests.forecast_data import fixture_history
from tests.statements_pipeline import run_pipeline

PERIODS = [
    Period("FY2024", "FY24", 2024, "FY", date(2024, 1, 1), date(2024, 12, 31)),
    Period("FY2025", "FY25", 2025, "FY", date(2025, 1, 1), date(2025, 12, 31)),
]


def item(code: str, **fields: object) -> CanonicalItemDef:
    base: dict[str, object] = {
        "code": code,
        "statement": "BS",
        "label": code,
        "kind": "instant",
        "unit": "USD",
        "sign": 1,
        "parent": "total_current_assets",
        "concepts": (),
        "derive": None,
        "residual": False,
    }
    return CanonicalItemDef(**(base | fields))  # type: ignore[arg-type]


ITEMS = [
    item("total_current_assets", parent=None, concepts=("us-gaap:AssetsCurrent",)),
    item("cash", concepts=("us-gaap:Cash",)),
    item("prepaid", concepts=("us-gaap:Prepaid",), forecast_fold="other_current_assets"),
    item(
        "other_current_assets",
        residual=True,
        derive="total_current_assets - cash - prepaid",
    ),
]


def row(code: str, *values: int | None) -> Row:
    decimals = [None if v is None else Decimal(v) for v in values]
    return Row(
        code,
        code,
        "USD",
        "instant",
        1,
        decimals,
        ["derived" if v is not None else None for v in values],
        [None] * len(values),
        [None] * len(values),
    )


def table(*rows: Row, statement: str = "BS") -> StatementTable:
    return StatementTable(statement, "annual", PERIODS, list(rows), None, [])


def values(t: StatementTable) -> dict[str, list[Decimal | None]]:
    return {r.code: r.values for r in t.rows}


def test_a_folded_row_is_added_back_into_its_residual_and_dropped() -> None:
    tables = {
        "BS": table(
            row("total_current_assets", 100, 120),
            row("cash", 40, 50),
            row("prepaid", 10, 15),
            row("other_current_assets", 50, 55),
        )
    }

    folded = fold_rows(tables, ITEMS)

    assert values(folded["BS"]) == {
        "total_current_assets": [Decimal(100), Decimal(120)],
        "cash": [Decimal(40), Decimal(50)],
        "other_current_assets": [Decimal(60), Decimal(70)],
    }


def test_an_empty_row_leaves_the_residual_as_it_is() -> None:
    tables = {
        "BS": table(
            row("total_current_assets", 100, 120),
            row("prepaid", None, 15),
            row("other_current_assets", 60, 55),
        )
    }

    folded = fold_rows(tables, ITEMS)

    assert values(folded["BS"])["other_current_assets"] == [Decimal(60), Decimal(70)]


def test_an_empty_residual_stays_empty() -> None:
    tables = {"BS": table(row("prepaid", 10, 15), row("other_current_assets", None, 55))}

    folded = fold_rows(tables, ITEMS)

    assert values(folded["BS"]) == {"other_current_assets": [None, Decimal(70)]}


def test_the_residual_keeps_its_provenance() -> None:
    residual = row("other_current_assets", 50, None)
    tables = {"BS": table(row("prepaid", 10, 15), residual)}

    folded = fold_rows(tables, ITEMS)

    assert folded["BS"].rows[0].provenance == residual.provenance


def test_a_row_added_to_the_formula_is_subtracted_back() -> None:
    items = [
        *ITEMS[:2],
        item("refunds", concepts=("us-gaap:R",), forecast_fold="other_current_assets"),
        item("other_current_assets", residual=True, derive="total_current_assets - cash + refunds"),
    ]
    tables = {"BS": table(row("refunds", 10, 15), row("other_current_assets", 50, 55))}

    folded = fold_rows(tables, items)

    assert values(folded["BS"]) == {"other_current_assets": [Decimal(40), Decimal(40)]}


def test_tables_without_a_folded_row_come_back_unchanged() -> None:
    is_table = table(row("revenue", 1, 2), statement="IS")
    bs_table = table(row("cash", 40, 50), row("other_current_assets", 50, 55))

    folded = fold_rows({"IS": is_table, "BS": bs_table}, ITEMS)

    assert folded == {"IS": is_table, "BS": bs_table}


def test_a_row_whose_residual_is_not_in_the_table_is_kept_not_lost() -> None:
    tables = {"BS": table(row("cash", 40, 50), row("prepaid", 10, 15))}

    folded = fold_rows(tables, ITEMS)

    assert values(folded["BS"]) == values(tables["BS"])


def test_no_tables_fold_to_none() -> None:
    assert fold_rows({}, ITEMS) == {}


# --- the recorded companies: folded history = the history before the new rows -------------------


S5_CODES = frozenset(
    {
        "interest_income",
        "deferred_tax_assets",
        "deferred_revenue_noncurrent",
        "deferred_tax_liabilities",
        "pension_liabilities",
        "cash_taxes_paid",
        "cash_interest_paid",
    }
)
S5_MEMO = frozenset({"cash_taxes_paid", "cash_interest_paid"})


def cells(t: StatementTable) -> dict[str, list[tuple[Decimal | None, str | None]]]:
    return {r.code: list(zip(r.values, r.provenance, strict=True)) for r in t.rows}


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "COST", "DE"])
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_the_folded_history_equals_the_history_without_the_new_rows(ticker: str, freq: str) -> None:
    items = load_canonical_items()
    now, before = run_pipeline(ticker), run_pipeline(ticker, drop_codes=S5_CODES)
    tables = now.annual if freq == "annual" else now.quarterly
    old = before.annual if freq == "annual" else before.quarterly

    folded = fold_rows(tables, items)

    for statement, table in folded.items():
        assert table.periods == old[statement].periods
        got = {c: v for c, v in cells(table).items() if c not in S5_MEMO}
        assert got == cells(old[statement]), statement
    assert S5_MEMO <= MEMO_CODES


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "COST", "DE"])
def test_the_fixture_history_a_forecast_reads_is_folded(ticker: str) -> None:
    history = fixture_history(ticker)

    codes = {r.code for t in history.annual.values() for r in t.rows}
    assert not codes & (S5_CODES - S5_MEMO)
    assert codes >= S5_MEMO
