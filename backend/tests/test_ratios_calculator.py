"""compute_ratios (FR-ANL-01..04): operand rules, nulls, EPS, ccc, trimming, caveats, invariants."""

from datetime import date
from decimal import Decimal

import pytest

from bedrock.mapping.config import load_canonical_items
from bedrock.ratios.calculator import RatioInputs, RatioTable, compute_ratios
from bedrock.ratios.caveats import load_caveats
from bedrock.ratios.registry import RATIOS, Ratio, RegistryError
from bedrock.statements.build import RATIO_PLACES, Row, StatementTable, build_statement
from bedrock.statements.periods import Period
from tests.statements_pipeline import run_pipeline

KINDS = {i.code: i.kind for i in load_canonical_items()}
TICKERS = ("AAPL", "MSFT", "COST", "DE")

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


def values(result: RatioTable, code: str) -> list[Decimal | None]:
    return next(row for row in result.rows if row.code == code).values


def keys(result: RatioTable) -> list[str]:
    return [p.key for p in result.periods]


# --- annual fixture: FY2022..FY2024 plus an all-empty FY2025 -------------------------------------

YEARS = [fy(2022), fy(2023), fy(2024), fy(2025)]
ANNUAL = RatioInputs(
    income=table(
        "IS",
        "annual",
        YEARS,
        {
            "revenue": [100, 200, 300, None],
            "cost_of_revenue": [60, 120, 150, None],
            "gross_profit": [40, 80, 150, None],
            "operating_income": [20, 40, 100, None],
            "interest_expense": [5, 0, -2, None],
            "net_income": [10, 20, 30, None],
            "net_income_common": [10, 20, 30, None],
            "eps_diluted": ["1.5", "2.25", "3", None],
            "shares_diluted": [10, 10, 10, None],
        },
    ),
    cash_flow=table("CF", "annual", YEARS, {"free_cash_flow": [8, 16, 24, None]}),
    balance=table(
        "BS",
        "annual",
        YEARS,
        {
            "total_current_assets": [50, 60, 70, None],
            "total_current_liabilities": [25, 30, 35, None],
            "cash": [10, 10, 10, None],
            "short_term_investments": [5, 5, None, None],
            "receivables": [10, 20, 30, None],
            "inventory": [12, 18, None, None],
            "accounts_payable": [6, 9, 12, None],
            "total_assets": [100, 140, 180, None],
            "equity_parent": [40, 60, 80, None],
        },
    ),
)


@pytest.fixture(scope="module")
def annual() -> RatioTable:
    return compute_ratios(ANNUAL, "annual")


def test_rows_follow_the_registry_with_its_metadata(annual: RatioTable) -> None:
    assert annual.freq == "annual"
    assert [r.code for r in annual.rows] == [r.code for r in RATIOS]
    for row, ratio in zip(annual.rows, RATIOS, strict=True):
        assert (row.label, row.category, row.unit, row.definition) == (
            ratio.label,
            ratio.category,
            ratio.unit,
            ratio.definition,
        )
        assert row.caveat is None
        assert len(row.values) == len(annual.periods)


def test_a_period_without_any_ratio_value_is_trimmed(annual: RatioTable) -> None:
    assert keys(annual) == ["FY2022", "FY2023", "FY2024"]


def test_annual_flow_over_flow(annual: RatioTable) -> None:
    assert values(annual, "gross_margin") == [Decimal("0.4"), Decimal("0.4"), Decimal("0.5")]


def test_annual_instant_reads_the_balance_at_the_same_year_end(annual: RatioTable) -> None:
    assert values(annual, "current_ratio") == [Decimal(2), Decimal(2), Decimal(2)]
    assert values(annual, "bvps") == [None, None, None]  # shares_outstanding has no row


def test_annual_average_needs_both_year_ends(annual: RatioTable) -> None:
    # roe = net_income_common ÷ avg(equity_parent); FY2022 has no FY2021 balance
    assert values(annual, "roe") == [None, Decimal("0.4"), Decimal("0.428571")]
    # equity multiplier averages both operands: (120/50, 160/70)
    assert values(annual, "dupont_equity_multiplier") == [None, Decimal("2.4"), Decimal("2.285714")]


def test_results_are_quantized_to_six_places(annual: RatioTable) -> None:
    assert values(annual, "operating_margin")[2] == Decimal("0.333333")
    for row in annual.rows:
        for value in row.values:
            assert value is None or value == value.quantize(RATIO_PLACES)


def test_denominator_zero_or_negative_is_null(annual: RatioTable) -> None:
    assert values(annual, "interest_coverage") == [Decimal(4), None, None]


def test_formula_operand_with_a_null_term_is_null(annual: RatioTable) -> None:
    # (cash + short_term_investments + receivables) ÷ total_current_liabilities
    assert values(annual, "quick_ratio") == [Decimal(1), Decimal("1.166667"), None]


def test_missing_operand_row_is_null(annual: RatioTable) -> None:
    # debt rows absent: total_debt/net_debt never resolve; ebitda lacks d_and_a
    assert values(annual, "debt_to_equity") == [None, None, None]
    assert values(annual, "ebitda_margin") == [None, None, None]


def test_day_counts_are_scaled_by_365(annual: RatioTable) -> None:
    assert values(annual, "dso") == [None, Decimal("27.375"), Decimal("30.416667")]
    assert values(annual, "dio") == [None, Decimal("45.625"), None]
    assert values(annual, "dpo") == [None, Decimal("22.8125"), Decimal("25.55")]


def test_ccc_combines_the_day_counts_and_needs_all_three(annual: RatioTable) -> None:
    assert values(annual, "ccc") == [None, Decimal("50.1875"), None]


def test_ccc_uses_the_quantized_day_counts() -> None:
    periods = [fy(2022), fy(2023)]
    inputs = RatioInputs(
        income=table("IS", "annual", periods, {"revenue": [3, 3], "cost_of_revenue": [3, 3]}),
        cash_flow=table("CF", "annual", periods, {}),
        balance=table(
            "BS",
            "annual",
            periods,
            {"receivables": [1, 1], "inventory": [1, 1], "accounts_payable": [3, 3]},
        ),
    )
    result = compute_ratios(inputs, "annual")
    assert [values(result, c)[-1] for c in ("dso", "dio", "dpo")] == [
        Decimal("121.666667"),
        Decimal("121.666667"),
        Decimal(365),
    ]
    # the displayed rows sum to -121.666666; the unrounded -121.6666667 would round to -121.666667
    assert values(result, "ccc")[-1] == Decimal("-121.666666")


def test_annual_eps_reads_the_eps_line(annual: RatioTable) -> None:
    assert values(annual, "eps_diluted") == [Decimal("1.5"), Decimal("2.25"), Decimal(3)]
    assert values(annual, "fcf_per_share") == [Decimal("0.8"), Decimal("1.6"), Decimal("2.4")]


def test_ratio_without_denominator_is_the_scaled_numerator() -> None:
    doubled = Ratio(
        code="double_rev",
        label="x",
        category="Profitability",
        unit="x",
        definition="revenue × 2",
        numerator="revenue",
        scale=Decimal(2),
    )
    result = compute_ratios(ANNUAL, "annual", ratios=(doubled,))
    assert values(result, "double_rev") == [Decimal(200), Decimal(400), Decimal(600)]


# --- TTM fixture --------------------------------------------------------------------------------

TTM_PERIODS = [ttm(2024, 1), ttm(2024, 2)]
QUARTERS = [
    quarter(2023, 2),
    quarter(2023, 3),
    quarter(2023, 4),
    quarter(2024, 1),
    quarter(2024, 2),
]
BS_QUARTERS = [quarter(2023, 1), quarter(2023, 2), quarter(2024, 1), quarter(2024, 2)]
TTM = RatioInputs(
    income=table(
        "IS",
        "ttm",
        TTM_PERIODS,
        {
            "revenue": [400, 440],
            "net_income_common": [24, 36],
            "eps_diluted": [None, None],  # average-kind lines are empty in a TTM table
            "shares_diluted": [None, None],
        },
    ),
    cash_flow=table("CF", "ttm", TTM_PERIODS, {"free_cash_flow": [48, 60]}),
    balance=table(
        "BS",
        "quarterly",
        BS_QUARTERS,
        {
            "total_current_assets": [999, 999, 90, 100],
            "total_current_liabilities": [1, 1, 45, 40],
            "equity_parent": [40, 50, 60, 70],
        },
    ),
    quarterly_income=table(
        "IS",
        "quarterly",
        QUARTERS,
        {
            "shares_diluted": [9, 10, None, 12, None],
            "eps_diluted": ["0.5", "0.6", None, "0.7", None],
        },
    ),
)


@pytest.fixture(scope="module")
def ttm_table() -> RatioTable:
    return compute_ratios(TTM, "ttm")


def test_ttm_periods_come_from_the_ttm_income_table(ttm_table: RatioTable) -> None:
    assert ttm_table.freq == "ttm"
    assert keys(ttm_table) == ["TTM-FY2024Q1", "TTM-FY2024Q2"]


def test_ttm_flow_reads_the_ttm_value(ttm_table: RatioTable) -> None:
    assert values(ttm_table, "net_margin") == [Decimal("0.06"), Decimal("0.081818")]


def test_ttm_instant_reads_the_quarter_the_window_ends_at(ttm_table: RatioTable) -> None:
    assert values(ttm_table, "current_ratio") == [Decimal(2), Decimal("2.5")]


def test_ttm_average_uses_the_same_quarter_a_year_earlier(ttm_table: RatioTable) -> None:
    assert values(ttm_table, "roe") == [Decimal("0.48"), Decimal("0.6")]


def test_ttm_average_kind_is_the_latest_quarter_with_a_value(ttm_table: RatioTable) -> None:
    # windows: 23Q2..24Q1 (last = 12) and 23Q3..24Q2 (24Q2 empty -> 24Q1 = 12, not 23Q3 = 10)
    assert values(ttm_table, "fcf_per_share") == [Decimal(4), Decimal(5)]


def test_ttm_eps_is_net_income_common_over_latest_diluted_shares(ttm_table: RatioTable) -> None:
    assert values(ttm_table, "eps_diluted") == [Decimal(2), Decimal(3)]


def test_ttm_average_kind_window_without_any_value_is_null() -> None:
    inputs = RatioInputs(
        income=TTM.income,
        cash_flow=TTM.cash_flow,
        balance=TTM.balance,
        quarterly_income=table("IS", "quarterly", QUARTERS, {"shares_diluted": [None] * 5}),
    )
    result = compute_ratios(inputs, "ttm")
    assert values(result, "eps_diluted") == [None, None]


def test_ttm_without_quarterly_income_is_an_error() -> None:
    with pytest.raises(ValueError):
        compute_ratios(RatioInputs(TTM.income, TTM.cash_flow, TTM.balance), "ttm")


def test_empty_inputs_give_every_row_and_no_periods() -> None:
    empty = table("IS", "annual", [], {})
    result = compute_ratios(RatioInputs(empty, empty, empty), "annual")
    assert result.periods == []
    assert [r.code for r in result.rows] == [r.code for r in RATIOS]
    assert all(r.values == [] for r in result.rows)


def test_de_caveat_attaches_to_its_codes_only() -> None:
    caveats = load_caveats()
    de = compute_ratios(ANNUAL, "annual", caveats=caveats["DE"])
    by_code = {r.code: r.caveat for r in de.rows}
    assert by_code["debt_to_ebitda"] == caveats["DE"][0].text
    for code, caveat in by_code.items():
        expected = next((c.text for c in caveats["DE"] if code in c.codes), None)
        assert caveat == expected, code
    assert any(caveat is None for caveat in by_code.values())  # some rows carry none
    aapl = compute_ratios(ANNUAL, "annual", caveats=caveats.get("AAPL", ()))
    assert all(r.caveat is None for r in aapl.rows)


# --- real companies -----------------------------------------------------------------------------

_REAL: dict[tuple[str, str], RatioTable] = {}


def real(ticker: str, freq: str) -> RatioTable:
    if (ticker, freq) not in _REAL:
        p = run_pipeline(ticker)
        if freq == "annual":
            inputs = RatioInputs(p.annual["IS"], p.annual["CF"], p.annual["BS"])
        else:
            inputs = RatioInputs(
                build_statement(p.canonical, p.items, "IS", "ttm"),
                build_statement(p.canonical, p.items, "CF", "ttm"),
                p.quarterly["BS"],
                p.quarterly["IS"],
            )
        _REAL[(ticker, freq)] = compute_ratios(inputs, "annual" if freq == "annual" else "ttm")
    return _REAL[(ticker, freq)]


@pytest.mark.parametrize("freq", ["annual", "ttm"])
@pytest.mark.parametrize("ticker", TICKERS)
def test_dupont_identity_holds(ticker: str, freq: str) -> None:
    result = real(ticker, freq)
    checked = 0
    for nm, at, em, roe in zip(
        values(result, "dupont_net_margin"),
        values(result, "dupont_asset_turnover"),
        values(result, "dupont_equity_multiplier"),
        values(result, "roe"),
        strict=True,
    ):
        if None in (nm, at, em, roe):
            continue
        assert nm is not None and at is not None and em is not None and roe is not None
        bound = Decimal("1e-6") * (1 + abs(at * em) + abs(nm * em) + abs(nm * at))
        assert abs(nm * at * em - roe) <= bound
        checked += 1
    assert checked > 0


@pytest.mark.parametrize("freq", ["annual", "ttm"])
@pytest.mark.parametrize("ticker", TICKERS)
def test_every_period_kept_has_a_value(ticker: str, freq: str) -> None:
    result = real(ticker, freq)
    assert result.periods
    for i in range(len(result.periods)):
        assert any(row.values[i] is not None for row in result.rows)


@pytest.mark.parametrize("ticker", TICKERS)
def test_gross_margin_matches_its_operands(ticker: str) -> None:
    p = run_pipeline(ticker)
    result = real(ticker, "annual")
    income = {r.code: r for r in p.annual["IS"].rows}
    index = {period.key: i for i, period in enumerate(p.annual["IS"].periods)}
    checked = 0
    for period, value in zip(result.periods, values(result, "gross_margin"), strict=True):
        gp = income["gross_profit"].values[index[period.key]]
        rev = income["revenue"].values[index[period.key]]
        if gp is None or rev is None or rev <= 0:
            assert value is None
        else:
            assert value == (gp / rev).quantize(RATIO_PLACES)
            checked += 1
    assert checked > 0


def test_ttm_average_kind_window_rolls_back_into_the_previous_year() -> None:
    # window 23Q2..24Q1: 24Q1 and 23Q4 empty -> the FY2023Q3 value (10)
    inputs = RatioInputs(
        income=TTM.income,
        cash_flow=TTM.cash_flow,
        balance=TTM.balance,
        quarterly_income=table(
            "IS", "quarterly", QUARTERS, {"shares_diluted": [9, 10, None, None, None]}
        ),
    )
    result = compute_ratios(inputs, "ttm")
    assert values(result, "eps_diluted")[0] == Decimal("2.4")


def _custom(code: str, numerator: str) -> Ratio:
    return Ratio(
        code=code,
        label=code,
        category="Profitability",
        unit="x",
        definition=numerator,
        numerator=numerator,
    )


def test_custom_ratio_with_unknown_operand_is_rejected() -> None:
    with pytest.raises(RegistryError):
        compute_ratios(ANNUAL, "annual", ratios=(_custom("bad", "no_such_code"),))


def test_custom_ratio_reading_itself_is_rejected() -> None:
    with pytest.raises(RegistryError):
        compute_ratios(ANNUAL, "annual", ratios=(_custom("loop", "revenue + loop"),))
