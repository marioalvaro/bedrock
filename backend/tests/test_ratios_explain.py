"""Ratio cell details (docs/erd/analysis.md "Ratio cell details"): the formula and the inputs of a
ratio value, from the same operand rules that computed it."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from bedrock.ratios.calculator import RatioInputs, compute_ratios
from bedrock.ratios.explain import Term, explain_ratio
from bedrock.ratios.registry import METRICS, RATIOS, Ratio
from tests.test_ratios_calculator import fy, quarter, table, ttm
from tests.test_valuation_ratios import inputs

D = Decimal
FY2024 = (2024, "FY")


def only(terms: tuple[Term, ...]) -> Term:
    (term,) = terms
    return term


def test_a_plain_ratio_lists_its_operands_with_their_values() -> None:
    e = explain_ratio(inputs(), "annual", "ps", FY2024)

    assert (e.code, e.label, e.category, e.unit) == ("ps", "P/S", "Valuation", "x")
    assert (e.fiscal_year, e.fiscal_period, e.value, e.scale) == (2024, "FY", D(3), D(1))
    assert e.definition == "market_cap ÷ revenue"
    assert e.reason is None and e.caveat is None
    assert e.numerator.text == "market_cap" and e.numerator.value == D(600)
    assert e.denominator is not None
    assert (e.denominator.text, e.denominator.value, e.denominator.average) == (
        "revenue",
        D(200),
        False,
    )
    revenue = only(e.denominator.terms)
    assert (revenue.code, revenue.label, revenue.kind, revenue.unit) == (
        "revenue",
        "Revenue",
        "line",
        "USD",
    )
    assert (revenue.value, revenue.sign, revenue.children) == (D(200), 1, ())


def test_the_explained_value_is_the_tables_value() -> None:
    table_ = compute_ratios(inputs(), "annual")
    for row in table_.rows:
        for period, value in zip(table_.periods, row.values, strict=True):
            e = explain_ratio(inputs(), "annual", row.code, (period.fiscal_year, "FY"))
            assert e.value == value, (row.code, period.key)


def test_a_metric_is_expanded_into_its_inputs() -> None:
    e = explain_ratio(inputs(), "annual", "ps", FY2024)

    market_cap = only(e.numerator.terms)
    assert (market_cap.code, market_cap.kind, market_cap.value) == ("market_cap", "metric", D(600))
    assert market_cap.definition == "price × shares_outstanding"
    price, shares = market_cap.children
    assert (price.code, price.kind, price.value) == ("price", "metric", D(60))
    assert (shares.code, shares.kind, shares.value, shares.unit) == (
        "shares_outstanding",
        "line",
        D(10),
        "shares",
    )


def test_a_price_says_which_close_it_is() -> None:
    e = explain_ratio(inputs(), "annual", "ps", FY2024)

    price = only(e.numerator.terms).children[0]
    assert price.note == "close of 2023-12-29, the last on or before the period end 2024-01-01"


def test_enterprise_value_expands_down_to_the_statement_lines() -> None:
    e = explain_ratio(inputs(), "annual", "enterprise_value_usd", FY2024)

    assert e.value == D(642) and e.unit == "USD" and e.denominator is None
    ev = only(e.numerator.terms)
    assert ev.code == "enterprise_value"
    by_code = {t.code: t for t in ev.children}
    assert list(by_code) == [
        "market_cap",
        "total_debt",
        "minority_interest",
        "cash",
        "temporary_equity",
        "short_term_investments",
    ]
    assert by_code["total_debt"].value == D(40)
    assert by_code["short_term_investments"].value is None
    assert [c.code for c in by_code["minority_interest"].children] == [
        "total_equity",
        "equity_parent",
    ]
    assert [c.value for c in by_code["minority_interest"].children] == [D(70), D(60)]
    assert [c.code for c in by_code["market_cap"].children] == ["price", "shares_outstanding"]


def test_an_average_shows_both_ends() -> None:
    e = explain_ratio(inputs(), "annual", "roe", FY2024)

    # net_income_common 20 / avg(equity_parent 60, 40) = 20 / 50
    assert e.value == D("0.4")
    assert e.denominator is not None
    assert (e.denominator.average, e.denominator.value) == (True, D(50))
    assert only(e.denominator.terms).value == D(60)
    assert only(e.denominator.prior_terms).value == D(40)
    assert e.numerator.average is False and e.numerator.prior_terms == ()


def test_a_scale_is_reported() -> None:
    e = explain_ratio(inputs(), "annual", "dso", FY2024)

    assert e.scale == D(365)


def test_a_formula_operand_lists_each_member_with_its_sign() -> None:
    gap = Ratio(
        code="debt_less_cash",
        label="Debt less cash",
        category="Solvency",
        unit="x",
        definition="(total_debt - cash) ÷ revenue",
        numerator="total_debt - cash",
        denominator="revenue",
    )
    e = explain_ratio(inputs(), "annual", "debt_less_cash", FY2024, ratios=(gap,))

    assert e.value == D("0.15")
    assert [(t.code, t.sign, t.value) for t in e.numerator.terms] == [
        ("total_debt", 1, D(40)),
        ("cash", -1, D(10)),
    ]
    assert e.numerator.value == D(30)


def test_a_ratio_used_as_an_operand_is_a_leaf_with_its_definition() -> None:
    e = explain_ratio(inputs(), "annual", "peg", FY2024)

    pe = e.numerator.terms[0]
    assert (pe.code, pe.kind, pe.value, pe.children) == ("pe", "ratio", D(30), ())
    assert pe.definition == "market_cap ÷ net_income_common"


def test_earnings_growth_lists_net_income_now_and_a_year_earlier() -> None:
    e = explain_ratio(inputs(), "annual", "peg", FY2024)

    assert e.denominator is not None
    growth = only(e.denominator.terms)
    assert (growth.code, growth.kind, growth.value) == ("earnings_growth", "metric", D(100))
    assert [(c.code, c.value) for c in growth.children] == [
        ("net_income_common", D(20)),
        ("net_income_common", D(10)),
    ]
    assert growth.children[1].note == "a year earlier"


@pytest.mark.parametrize(
    ("overrides", "code", "reason"),
    [
        ({"prices": []}, "pe", "numerator missing"),
        ({}, "ev_sales", None),
    ],
)
def test_a_null_value_says_why(overrides: dict[str, object], code: str, reason: str | None) -> None:
    e = explain_ratio(replace(inputs(), **overrides), "annual", code, FY2024)  # type: ignore[arg-type]

    assert e.reason == reason
    assert (e.value is None) == (reason is not None)


def test_a_non_positive_denominator_is_named() -> None:
    loss = replace(
        inputs(),
        income=table(
            "IS",
            "annual",
            [fy(2023), fy(2024)],
            {"revenue": [100, 200], "net_income_common": [10, -20]},
        ),
    )

    e = explain_ratio(loss, "annual", "pe", FY2024)

    assert e.value is None and e.reason == "denominator ≤ 0"
    assert e.denominator is not None and e.denominator.value == D(-20)


def test_a_missing_denominator_is_named() -> None:
    e = explain_ratio(inputs(), "annual", "gross_margin", FY2024)

    assert e.value is None and e.reason == "numerator missing"  # no gross_profit in the inputs
    e = explain_ratio(inputs(), "annual", "fcf_per_share", FY2024)
    assert e.value is None and e.reason == "denominator missing"  # no shares_diluted


def test_a_ttm_average_line_notes_where_it_comes_from() -> None:
    periods = [replace(ttm(2024, 1), end=date(2024, 1, 1))]
    q = [quarter(2024, 1)]
    base = inputs()
    ttm_inputs = RatioInputs(
        # the TTM statement has the weighted-average row, always empty
        income=table("IS", "ttm", periods, {"net_income_common": [20], "shares_diluted": [None]}),
        cash_flow=table("CF", "ttm", periods, {"free_cash_flow": [24]}),
        balance=table("BS", "quarterly", periods, {"shares_outstanding": [10]}),
        quarterly_income=table("IS", "quarterly", q, {"shares_diluted": [8]}),
        prices=base.prices,
    )

    e = explain_ratio(ttm_inputs, "ttm", "eps_diluted", (2024, "Q1"))

    assert e.value == D("2.5")
    assert (e.numerator.text, e.denominator.text if e.denominator else None) == (
        "net_income_common",
        "shares_diluted",
    )
    assert e.denominator is not None
    assert only(e.denominator.terms).note == "latest quarter of the window with a value"


def test_an_unknown_ratio_or_period_is_a_key_error_for_the_service_to_name() -> None:
    with pytest.raises(KeyError):
        explain_ratio(inputs(), "annual", "ghost", FY2024)
    with pytest.raises(KeyError):
        explain_ratio(inputs(), "annual", "pe", (1999, "FY"))


def test_every_metric_has_a_definition() -> None:
    assert all(m.definition for m in METRICS)
    assert len(RATIOS) > 0
