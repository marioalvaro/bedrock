from collections.abc import Mapping
from decimal import Decimal

import pytest

from bedrock.mapping.config import load_canonical_items
from bedrock.ratios.registry import (
    METRICS,
    RATIOS,
    Metric,
    Ratio,
    RegistryError,
    operand_codes,
    validate,
)

CANONICAL = frozenset({"revenue", "cost_of_revenue", "net_income", "eps_diluted"})


def const(inputs: Mapping[str, Decimal | None]) -> Decimal | None:
    return Decimal(1)


def metric(code: str, *inputs: str) -> Metric:
    return Metric(code=code, label=code, inputs=inputs, fn=const)


def ratio(
    code: str,
    numerator: str,
    denominator: str | None = None,
    ttm: tuple[str, str | None] | None = None,
) -> Ratio:
    return Ratio(
        code=code,
        label=code,
        category="Profitability",
        unit="pct",
        definition=code,
        numerator=numerator,
        denominator=denominator,
        ttm=ttm,
    )


# --- operand_codes -------------------------------------------------------------------------


def test_operand_codes_single() -> None:
    assert operand_codes("revenue") == ["revenue"]


def test_operand_codes_formula_in_order() -> None:
    assert operand_codes("a + b - c") == ["a", "b", "c"]


@pytest.mark.parametrize("text", ["", "a +", "a * b", "(a + b)"])
def test_operand_codes_malformed_raises(text: str) -> None:
    with pytest.raises(RegistryError):
        operand_codes(text)


# --- validate ------------------------------------------------------------------------------


def test_validate_accepts_consistent_registry() -> None:
    metrics = (metric("gp", "revenue", "cost_of_revenue"), metric("gp2", "gp"))
    ratios = (
        ratio("margin", "gp", "revenue"),
        ratio("double", "margin + margin"),
    )
    validate(metrics, ratios, CANONICAL)


def test_validate_rejects_duplicate_ratio_code() -> None:
    with pytest.raises(RegistryError, match="margin"):
        validate((), (ratio("margin", "revenue"), ratio("margin", "net_income")), CANONICAL)


def test_validate_rejects_duplicate_metric_code() -> None:
    with pytest.raises(RegistryError, match="gp"):
        validate((metric("gp", "revenue"), metric("gp", "revenue")), (), CANONICAL)


def test_validate_rejects_code_shared_by_metric_and_ratio() -> None:
    with pytest.raises(RegistryError, match="gp"):
        validate((metric("gp", "revenue"),), (ratio("gp", "revenue"),), CANONICAL)


def test_validate_rejects_metric_shadowing_canonical_code() -> None:
    with pytest.raises(RegistryError, match="revenue"):
        validate((metric("revenue", "net_income"),), (), CANONICAL)


def test_validate_allows_ratio_named_like_its_canonical_line() -> None:
    # `eps_diluted` reads its own canonical line: the operand means the canonical code.
    validate((), (ratio("eps_diluted", "eps_diluted"),), CANONICAL)


def test_validate_rejects_unknown_numerator() -> None:
    with pytest.raises(RegistryError, match="bogus"):
        validate((), (ratio("r", "bogus", "revenue"),), CANONICAL)


def test_validate_rejects_unknown_denominator_term() -> None:
    with pytest.raises(RegistryError, match="bogus"):
        validate((), (ratio("r", "revenue", "net_income + bogus"),), CANONICAL)


def test_validate_rejects_unknown_ttm_operand() -> None:
    with pytest.raises(RegistryError, match="bogus"):
        validate((), (ratio("r", "revenue", ttm=("bogus", "revenue")),), CANONICAL)


def test_validate_rejects_unknown_metric_input() -> None:
    with pytest.raises(RegistryError, match="bogus"):
        validate((metric("gp", "revenue", "bogus"),), (), CANONICAL)


def test_validate_rejects_metric_input_that_is_a_ratio() -> None:
    # Metrics are evaluated before ratios, so a metric may read canonical codes and metrics only.
    with pytest.raises(RegistryError, match="margin"):
        validate((metric("gp", "margin"),), (ratio("margin", "revenue"),), CANONICAL)


def test_validate_rejects_malformed_operand() -> None:
    with pytest.raises(RegistryError, match="r"):
        validate((), (ratio("r", "revenue * 2"),), CANONICAL)


def test_validate_rejects_ratio_cycle() -> None:
    ratios = (ratio("a", "b"), ratio("b", "c + revenue"), ratio("c", "a", "revenue"))
    with pytest.raises(RegistryError, match="cycle"):
        validate((), ratios, CANONICAL)


def test_validate_rejects_ratio_self_reference() -> None:
    with pytest.raises(RegistryError, match="cycle"):
        validate((), (ratio("a", "revenue", "a"),), CANONICAL)


def test_validate_rejects_ratio_cycle_via_ttm() -> None:
    ratios = (ratio("a", "revenue", ttm=("b", None)), ratio("b", "a"))
    with pytest.raises(RegistryError, match="cycle"):
        validate((), ratios, CANONICAL)


def test_validate_rejects_metric_cycle() -> None:
    metrics = (metric("m1", "m2"), metric("m2", "revenue", "m1"))
    with pytest.raises(RegistryError, match="cycle"):
        validate(metrics, (), CANONICAL)


# --- shipped registry ----------------------------------------------------------------------

EXPECTED = [
    ("gross_margin", "Gross margin", "Profitability", "gross_profit ÷ revenue", "pct"),
    ("operating_margin", "Operating margin", "Profitability", "operating_income ÷ revenue", "pct"),
    ("ebitda_margin", "EBITDA margin", "Profitability", "ebitda ÷ revenue", "pct"),
    ("net_margin", "Net margin", "Profitability", "net_income_common ÷ revenue", "pct"),
    ("fcf_margin", "FCF margin", "Profitability", "free_cash_flow ÷ revenue", "pct"),
    ("roe", "Return on equity", "Profitability", "net_income_common ÷ avg(equity_parent)", "pct"),
    ("roa", "Return on assets", "Profitability", "net_income ÷ avg(total_assets)", "pct"),
    (
        "invested_capital_usd",
        "Invested capital",
        "Profitability",
        "total_debt + total_equity − cash − short_term_investments",
        "USD",
    ),
    (
        "roic",
        "Return on invested capital",
        "Profitability",
        "nopat ÷ avg(invested_capital)",
        "pct",
    ),
    ("dupont_net_margin", "Net margin", "DuPont", "net_income_common ÷ revenue", "pct"),
    ("dupont_asset_turnover", "Asset turnover", "DuPont", "revenue ÷ avg(total_assets)", "x"),
    (
        "dupont_equity_multiplier",
        "Equity multiplier",
        "DuPont",
        "avg(total_assets) ÷ avg(equity_parent)",
        "x",
    ),
    (
        "current_ratio",
        "Current ratio",
        "Liquidity",
        "total_current_assets ÷ total_current_liabilities",
        "x",
    ),
    (
        "quick_ratio",
        "Quick ratio",
        "Liquidity",
        "(cash + short_term_investments + receivables) ÷ total_current_liabilities",
        "x",
    ),
    ("debt_to_ebitda", "Debt / EBITDA", "Solvency", "total_debt ÷ ebitda", "x"),
    ("net_debt_to_ebitda", "Net debt / EBITDA", "Solvency", "net_debt ÷ ebitda", "x"),
    (
        "interest_coverage",
        "Interest coverage",
        "Solvency",
        "operating_income ÷ interest_expense",
        "x",
    ),
    ("debt_to_equity", "Debt / equity", "Solvency", "total_debt ÷ total_equity", "x"),
    ("asset_turnover", "Asset turnover", "Efficiency", "revenue ÷ avg(total_assets)", "x"),
    (
        "dso",
        "Days sales outstanding",
        "Efficiency",
        "avg(receivables) ÷ revenue × 365",
        "days",
    ),
    (
        "dio",
        "Days inventory outstanding",
        "Efficiency",
        "avg(inventory) ÷ cost_of_revenue × 365",
        "days",
    ),
    (
        "dpo",
        "Days payables outstanding",
        "Efficiency",
        "avg(accounts_payable) ÷ cost_of_revenue × 365",
        "days",
    ),
    (
        "ccc",
        "Cash conversion cycle",
        "Efficiency",
        "dso + dio − dpo (null unless all three exist)",
        "days",
    ),
    (
        "eps_diluted",
        "EPS (diluted)",
        "Per share",
        "annual: the IS `eps_diluted` line; TTM: net_income_common ÷ shares_diluted",
        "USD/shares",
    ),
    (
        "fcf_per_share",
        "FCF per share",
        "Per share",
        "free_cash_flow ÷ shares_diluted",
        "USD/shares",
    ),
    (
        "bvps",
        "Book value per share",
        "Per share",
        "equity_parent ÷ shares_outstanding",
        "USD/shares",
    ),
    (
        "dps",
        "Dividends per share",
        "Per share",
        "dividends_per_share (TTM: the TTM sum)",
        "USD/shares",
    ),
    (
        "pe",
        "P/E",
        "Valuation",
        "market_cap ÷ net_income_common",
        "x",
    ),
    (
        "earnings_yield",
        "Earnings yield",
        "Valuation",
        "net_income_common ÷ market_cap",
        "pct",
    ),
    (
        "peg",
        "PEG",
        "Valuation",
        "pe ÷ earnings_growth (net income growth, percentage points)",
        "x",
    ),
    (
        "pb",
        "P/B",
        "Valuation",
        "market_cap ÷ equity_parent",
        "x",
    ),
    (
        "ps",
        "P/S",
        "Valuation",
        "market_cap ÷ revenue",
        "x",
    ),
    (
        "p_fcf",
        "P/FCF",
        "Valuation",
        "market_cap ÷ free_cash_flow",
        "x",
    ),
    (
        "fcf_yield",
        "FCF yield",
        "Valuation",
        "free_cash_flow ÷ market_cap",
        "pct",
    ),
    (
        "enterprise_value_usd",
        "Enterprise value",
        "Valuation",
        "market_cap + total_debt + minority_interest − cash "
        "(+ temporary_equity − short_term_investments)",
        "USD",
    ),
    (
        "ev_sales",
        "EV/Sales",
        "Valuation",
        "enterprise_value ÷ revenue",
        "x",
    ),
    (
        "ev_ebitda",
        "EV/EBITDA",
        "Valuation",
        "enterprise_value ÷ ebitda",
        "x",
    ),
    (
        "ev_ebit",
        "EV/EBIT",
        "Valuation",
        "enterprise_value ÷ operating_income",
        "x",
    ),
    (
        "ev_fcf",
        "EV/FCF",
        "Valuation",
        "enterprise_value ÷ free_cash_flow",
        "x",
    ),
    (
        "dividend_yield",
        "Dividend yield",
        "Valuation",
        "dps ÷ price",
        "pct",
    ),
    (
        "payout_ratio",
        "Payout ratio",
        "Valuation",
        "cash_dividends ÷ net_income_common",
        "pct",
    ),
]


def test_shipped_ratio_codes_in_erd_order() -> None:
    assert [r.code for r in RATIOS] == [row[0] for row in EXPECTED]


def test_shipped_ratio_rows_match_erd_table() -> None:
    assert [(r.code, r.label, r.category, r.definition, r.unit) for r in RATIOS] == EXPECTED


def test_shipped_metric_codes_in_order() -> None:
    assert [m.code for m in METRICS] == [
        "ebitda",
        "tax_rate",
        "nopat",
        "invested_capital",
        "price",
        "market_cap",
        "minority_interest",
        "enterprise_value",
        "cash_dividends",
        "earnings_growth",
    ]


def test_shipped_registry_validates_against_canonical_items() -> None:
    codes = frozenset(item.code for item in load_canonical_items())
    validate(METRICS, RATIOS, codes)


def by_code(code: str) -> Ratio:
    return next(r for r in RATIOS if r.code == code)


@pytest.mark.parametrize(
    ("code", "numerator", "denominator", "avg_num", "avg_den", "scale"),
    [
        ("gross_margin", "gross_profit", "revenue", False, False, 1),
        ("ebitda_margin", "ebitda", "revenue", False, False, 1),
        ("roe", "net_income_common", "equity_parent", False, True, 1),
        ("roa", "net_income", "total_assets", False, True, 1),
        ("roic", "nopat", "invested_capital", False, True, 1),
        ("invested_capital_usd", "invested_capital", None, False, False, 1),
        ("enterprise_value_usd", "enterprise_value", None, False, False, 1),
        ("dupont_equity_multiplier", "total_assets", "equity_parent", True, True, 1),
        (
            "quick_ratio",
            "cash + short_term_investments + receivables",
            "total_current_liabilities",
            False,
            False,
            1,
        ),
        ("net_debt_to_ebitda", "net_debt", "ebitda", False, False, 1),
        ("dso", "receivables", "revenue", True, False, 365),
        ("dio", "inventory", "cost_of_revenue", True, False, 365),
        ("dpo", "accounts_payable", "cost_of_revenue", True, False, 365),
        ("ccc", "dso + dio - dpo", None, False, False, 1),
        ("eps_diluted", "eps_diluted", None, False, False, 1),
        ("dps", "dividends_per_share", None, False, False, 1),
    ],
)
def test_shipped_ratio_operands(
    code: str,
    numerator: str,
    denominator: str | None,
    avg_num: bool,
    avg_den: bool,
    scale: int,
) -> None:
    r = by_code(code)
    assert (r.numerator, r.denominator, r.avg_numerator, r.avg_denominator, r.scale) == (
        numerator,
        denominator,
        avg_num,
        avg_den,
        Decimal(scale),
    )


def test_only_eps_has_ttm_override() -> None:
    assert {r.code: r.ttm for r in RATIOS if r.ttm is not None} == {
        "eps_diluted": ("net_income_common", "shares_diluted")
    }


# --- metric functions ----------------------------------------------------------------------


def metric_fn(code: str) -> Metric:
    return next(m for m in METRICS if m.code == code)


def run(code: str, **values: str | None) -> Decimal | None:
    m = metric_fn(code)
    assert set(values) == set(m.inputs)
    return m.fn({k: None if v is None else Decimal(v) for k, v in values.items()})


def test_ebitda() -> None:
    assert run("ebitda", operating_income="100.5", d_and_a="20") == Decimal("120.5")


def test_tax_rate() -> None:
    assert run("tax_rate", income_tax="21", pretax_income="100") == Decimal("0.21")


def test_tax_rate_clamped_below_zero() -> None:
    assert run("tax_rate", income_tax="-5", pretax_income="100") == Decimal(0)


def test_tax_rate_clamped_above_one() -> None:
    assert run("tax_rate", income_tax="150", pretax_income="100") == Decimal(1)


@pytest.mark.parametrize("pretax", ["0", "-10"])
def test_tax_rate_null_when_pretax_not_positive(pretax: str) -> None:
    assert run("tax_rate", income_tax="5", pretax_income=pretax) is None


def test_nopat() -> None:
    assert run("nopat", operating_income="200", tax_rate="0.25") == Decimal("150.00")


def test_invested_capital() -> None:
    got = run(
        "invested_capital",
        total_debt="100",
        total_equity="300",
        cash="50",
        short_term_investments="25",
    )
    assert got == Decimal(325)


@pytest.mark.parametrize("code", ["ebitda", "tax_rate", "nopat", "invested_capital"])
def test_metric_none_when_any_input_none(code: str) -> None:
    m = metric_fn(code)
    for missing in m.inputs:
        values: dict[str, Decimal | None] = {k: Decimal(10) for k in m.inputs}
        values[missing] = None
        assert m.fn(values) is None, missing
