"""capital_allocation (FR-ANL-06): rows, % of CFO/FCF, nulls, net share change, TTM, trimming."""

import itertools
from datetime import date
from decimal import Decimal

import pytest

from bedrock.analysis.capital_allocation import (
    CapitalAllocationTable,
    CapitalRow,
    capital_allocation,
)
from bedrock.mapping.config import load_canonical_items
from bedrock.ratios.calculator import RatioInputs
from bedrock.statements.build import RATIO_PLACES, Row, StatementTable, build_statement
from bedrock.statements.periods import Period
from tests.statements_pipeline import run_pipeline

KINDS = {i.code: i.kind for i in load_canonical_items()}

Values = list[Decimal | int | str | None]


def D(value: Decimal | int | str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def fy(year: int) -> Period:
    return Period(
        f"FY{year}", f"FY{year % 100}", year, "FY", date(year - 1, 1, 1), date(year, 1, 1)
    )


def quarter(year: int, q: int) -> Period:
    return Period(
        f"FY{year}Q{q}", f"Q{q} FY{year % 100}", year, f"Q{q}", date(year, 1, 1), date(year, 3, q)
    )


def ttm(year: int, q: int) -> Period:
    return Period(
        f"TTM-FY{year}Q{q}", f"TTM Q{q}", year, f"Q{q}", date(year - 1, 1, 1), date(year, 3, q)
    )


def table(
    statement: str, freq: str, periods: list[Period], rows: dict[str, Values]
) -> StatementTable:
    built = []
    for code, values in rows.items():
        assert len(values) == len(periods), code
        n = len(values)
        built.append(
            Row(
                code,
                code,
                "USD",
                KINDS[code],
                0,
                [D(v) for v in values],
                [None] * n,
                [None] * n,
                [None] * n,
            )
        )
    return StatementTable(statement, freq, periods, built, None, [])


def row(result: CapitalAllocationTable, code: str) -> CapitalRow:
    return next(r for r in result.rows if r.code == code)


def keys(result: CapitalAllocationTable) -> list[str]:
    return [p.key for p in result.periods]


# --- annual fixture ------------------------------------------------------------------------------
# FY2021 holds only a share count (a prior for FY2022; trimmed), FY2026 is empty (trimmed).
# FY2022: the ordinary case. FY2023: a capex inflow, d_and_a = 0, missing acquisitions/dividends.
# FY2024: cfo = 0 and fcf < 0 (no % base), d_and_a < 0, missing buybacks.
# FY2025: only capex (no cfo, no fcf, no d_and_a).

YEARS = [fy(2021), fy(2022), fy(2023), fy(2024), fy(2025), fy(2026)]
ANNUAL_ROWS: dict[str, Values] = {
    "cfo": [None, 100, 200, 0, None, None],
    "free_cash_flow": [None, 80, 210, -10, None, None],
    "capex": [None, -20, 10, -10, -7, None],
    "d_and_a": [None, 10, 0, -5, None, None],
    "acquisitions": [None, -5, None, 3, None, None],
    "buybacks": [None, -30, -40, None, None, None],
    "dividends_paid": [None, -10, None, -12, None, None],
}
ANNUAL = RatioInputs(
    income=table("IS", "annual", YEARS, {"revenue": [None] * 6}),
    cash_flow=table("CF", "annual", YEARS, ANNUAL_ROWS),
    balance=table(
        "BS", "annual", YEARS, {"shares_outstanding": [1000, 1000, 950, 1045, None, None]}
    ),
)


@pytest.fixture(scope="module")
def annual() -> CapitalAllocationTable:
    return capital_allocation(ANNUAL, "annual")


def test_rows_in_erd_order_with_labels_units_and_pct_marks(annual: CapitalAllocationTable) -> None:
    expected = [
        ("cfo", "Cash from operations", "USD", False),
        ("free_cash_flow", "Free cash flow", "USD", False),
        ("capex", "Capital expenditures", "USD", True),
        ("d_and_a", "Depreciation & amortization", "USD", False),
        ("capex_to_da", "Capex / D&A", "x", False),
        ("acquisitions", "Acquisitions", "USD", True),
        ("buybacks", "Buybacks", "USD", True),
        ("dividends_paid", "Dividends", "USD", True),
        ("shareholder_returns", "Buybacks + dividends", "USD", True),
        ("net_share_change", "Net share-count change", "pct", False),
    ]
    assert [(r.code, r.label, r.unit) for r in annual.rows] == [e[:3] for e in expected]
    for r, (_, _, _, marked) in zip(annual.rows, expected, strict=True):
        if marked:
            assert r.pct_of_cfo is not None and len(r.pct_of_cfo) == len(annual.periods)
            assert r.pct_of_fcf is not None and len(r.pct_of_fcf) == len(annual.periods)
        else:
            assert r.pct_of_cfo is None and r.pct_of_fcf is None, r.code
    assert annual.freq == "annual"


def test_periods_without_any_value_are_trimmed(annual: CapitalAllocationTable) -> None:
    assert keys(annual) == ["FY2022", "FY2023", "FY2024", "FY2025"]
    assert all(len(r.values) == 4 for r in annual.rows)


def test_usd_rows_are_the_statement_values(annual: CapitalAllocationTable) -> None:
    for code, values in ANNUAL_ROWS.items():
        assert row(annual, code).values == [D(v) for v in values[1:5]], code


def test_usd_values_are_not_quantized() -> None:
    periods = [fy(2024)]
    inputs = RatioInputs(
        income=table("IS", "annual", periods, {}),
        cash_flow=table(
            "CF",
            "annual",
            periods,
            {"cfo": ["3.123456789"], "free_cash_flow": ["3"], "capex": ["-1.000000001"]},
        ),
        balance=table("BS", "annual", periods, {}),
    )
    result = capital_allocation(inputs, "annual")
    assert row(result, "cfo").values == [Decimal("3.123456789")]
    assert row(result, "capex").values == [Decimal("-1.000000001")]
    pct = row(result, "capex").pct_of_cfo
    # 1.000000001 / 3.123456789 = 0.3201581... by hand
    assert pct == [Decimal("0.320158")]
    assert pct is not None and pct[0] is not None
    assert pct[0].as_tuple().exponent == -6


def test_capex_to_da(annual: CapitalAllocationTable) -> None:
    # 20 / 10; d_and_a = 0, < 0 and None give null
    assert row(annual, "capex_to_da").values == [Decimal("2.000000"), None, None, None]


def test_pct_of_cfo_and_fcf_signs_and_null_bases(annual: CapitalAllocationTable) -> None:
    capex = row(annual, "capex")
    # outflow -> positive share; inflow (FY2023) -> negative; cfo 0 / fcf < 0 / None -> null
    assert capex.pct_of_cfo == [Decimal("0.2"), Decimal("-0.05"), None, None]
    assert capex.pct_of_fcf == [Decimal("0.25"), Decimal("-0.047619"), None, None]
    acquisitions = row(annual, "acquisitions")
    assert acquisitions.pct_of_cfo == [Decimal("0.05"), None, None, None]
    assert acquisitions.pct_of_fcf == [Decimal("0.0625"), None, None, None]
    buybacks = row(annual, "buybacks")
    assert buybacks.pct_of_cfo == [Decimal("0.3"), Decimal("0.2"), None, None]
    assert buybacks.pct_of_fcf == [Decimal("0.375"), Decimal("0.190476"), None, None]
    dividends = row(annual, "dividends_paid")
    assert dividends.pct_of_cfo == [Decimal("0.1"), None, None, None]
    assert dividends.pct_of_fcf == [Decimal("0.125"), None, None, None]


def test_shareholder_returns_needs_both_lines(annual: CapitalAllocationTable) -> None:
    returns = row(annual, "shareholder_returns")
    # FY2023 has no dividends, FY2024 no buybacks, FY2025 neither
    assert returns.values == [Decimal(-40), None, None, None]
    assert returns.pct_of_cfo == [Decimal("0.4"), None, None, None]
    assert returns.pct_of_fcf == [Decimal("0.5"), None, None, None]


def test_net_share_change_sign(annual: CapitalAllocationTable) -> None:
    # FY2022 flat against the trimmed FY2021; FY2023 shrinks (accretion, negative);
    # FY2024 grows (dilution, positive); FY2025 has no share count
    assert row(annual, "net_share_change").values == [
        Decimal("0.000000"),
        Decimal("-0.050000"),
        Decimal("0.100000"),
        None,
    ]


def test_quantized_values_have_six_places(annual: CapitalAllocationTable) -> None:
    for r in annual.rows:
        lists = [r.pct_of_cfo or [], r.pct_of_fcf or []]
        if r.unit != "USD":
            lists.append(r.values)
        for value in itertools.chain.from_iterable(lists):
            if value is not None:
                assert value.as_tuple().exponent == -6, r.code


def test_empty_inputs_give_every_row_and_no_periods() -> None:
    empty = table("IS", "annual", [], {})
    result = capital_allocation(RatioInputs(empty, empty, empty), "annual")
    assert result.periods == []
    assert len(result.rows) == 10
    assert all(r.values == [] for r in result.rows)


# --- invariants over a grid (hypothesis is not installed) ----------------------------------------

GRID = [None, -50, -3, 0, 7, 120]


@pytest.mark.parametrize("cfo", GRID)
def test_invariants_over_grid(cfo: int | None) -> None:
    combos = list(itertools.product(GRID, GRID, GRID))
    periods = [fy(2000 + i) for i in range(len(combos))]
    n = len(periods)
    inputs = RatioInputs(
        income=table("IS", "annual", periods, {}),
        cash_flow=table(
            "CF",
            "annual",
            periods,
            {
                "cfo": [cfo] * n,
                "free_cash_flow": [c[2] for c in combos],
                "buybacks": [c[0] for c in combos],
                "dividends_paid": [c[1] for c in combos],
            },
        ),
        balance=table("BS", "annual", periods, {}),
    )
    result = capital_allocation(inputs, "annual")
    index = {p.key: i for i, p in enumerate(periods)}
    returns = row(result, "shareholder_returns")
    for code in ("buybacks", "dividends_paid", "shareholder_returns"):
        r = row(result, code)
        assert r.pct_of_cfo is not None and r.pct_of_fcf is not None
        for p, value, of_cfo, of_fcf in zip(
            result.periods, r.values, r.pct_of_cfo, r.pct_of_fcf, strict=True
        ):
            fcf = D(combos[index[p.key]][2])
            for share, base in ((of_cfo, D(cfo)), (of_fcf, fcf)):
                if value is None or base is None or base <= 0:
                    assert share is None
                else:
                    assert share is not None
                    assert abs(share * base + value) <= RATIO_PLACES * base
    for p, total in zip(result.periods, returns.values, strict=True):
        buybacks, dividends, _ = combos[index[p.key]]
        if buybacks is None or dividends is None:
            assert total is None
        else:
            assert total == buybacks + dividends


# --- TTM -----------------------------------------------------------------------------------------

TTM_PERIODS = [ttm(2024, 2), ttm(2025, 2)]
QUARTERS = [quarter(2024, 2), quarter(2025, 1), quarter(2025, 2)]
TTM_INPUTS = RatioInputs(
    income=table("IS", "ttm", TTM_PERIODS, {"revenue": [None, None]}),
    cash_flow=table(
        "CF",
        "ttm",
        TTM_PERIODS,
        {"cfo": [400, 500], "free_cash_flow": [300, 400], "capex": [-100, -100]},
    ),
    balance=table("BS", "quarterly", QUARTERS, {"shares_outstanding": [100, 50, 90]}),
    quarterly_income=table("IS", "quarterly", QUARTERS, {"revenue": [None, None, None]}),
)


def test_ttm_reads_ttm_flows_and_quarter_end_shares() -> None:
    result = capital_allocation(TTM_INPUTS, "ttm")
    assert result.freq == "ttm"
    assert keys(result) == ["TTM-FY2024Q2", "TTM-FY2025Q2"]
    assert row(result, "cfo").values == [Decimal(400), Decimal(500)]
    assert row(result, "capex").pct_of_cfo == [Decimal("0.25"), Decimal("0.2")]
    # Q2 FY2025 (90) against Q2 FY2024 (100), not against Q1 FY2025; no Q2 FY2023 -> null
    assert row(result, "net_share_change").values == [None, Decimal("-0.1")]


def test_ttm_without_quarterly_income_raises() -> None:
    inputs = RatioInputs(TTM_INPUTS.income, TTM_INPUTS.cash_flow, TTM_INPUTS.balance)
    with pytest.raises(ValueError):
        capital_allocation(inputs, "ttm")


# --- real data: AAPL's 4-for-1 split (Aug 2020) --------------------------------------------------


def _shares_change(result: CapitalAllocationTable) -> dict[str, Decimal | None]:
    r = row(result, "net_share_change")
    return {p.key: v for p, v in zip(result.periods, r.values, strict=True)}


def test_aapl_net_share_change_is_split_adjusted() -> None:
    p = run_pipeline("AAPL")
    annual = _shares_change(
        capital_allocation(RatioInputs(p.annual["IS"], p.annual["CF"], p.annual["BS"]), "annual")
    )
    for key in ("FY2020", "FY2021"):
        value = annual[key]
        assert value is not None and abs(value) < Decimal("0.1"), (key, value)
    ttm_result = capital_allocation(
        RatioInputs(
            build_statement(p.canonical, p.items, "IS", "ttm"),
            build_statement(p.canonical, p.items, "CF", "ttm"),
            p.quarterly["BS"],
            p.quarterly["IS"],
        ),
        "ttm",
    )
    checked = [
        v
        for k, v in _shares_change(ttm_result).items()
        if k.startswith(("TTM-FY2020", "TTM-FY2021")) and v is not None
    ]
    assert checked
    assert all(abs(v) < Decimal("0.1") for v in checked), checked
