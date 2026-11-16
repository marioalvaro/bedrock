from decimal import Decimal
from pathlib import Path

import pytest

from bedrock.ratios.caveats import Caveat, load_caveats
from bedrock.ratios.registry import RegistryError

DE_TEXT = (
    "Consolidated figures include John Deere Financial. Its debt, interest expense and financing "
    "receivables fund customer purchases, so leverage, coverage and asset-based ratios are not "
    "comparable with an industrial company."
)
DE_CODES = frozenset(
    {
        "debt_to_ebitda",
        "net_debt_to_ebitda",
        "interest_coverage",
        "debt_to_equity",
        "roic",
        "roa",
        "asset_turnover",
        "dupont_asset_turnover",
        "dupont_equity_multiplier",
    }
)


DE_REVENUE_TEXT = (
    "Deere's revenue is net sales and revenues, which include John Deere Financial's finance and "
    "interest income, so gross margin and days sales outstanding are not comparable with an "
    "equipment maker's."
)


DE_EV_CODES = frozenset({"ev_sales", "ev_ebitda", "ev_ebit", "ev_fcf"})
DE_EV_TEXT = (
    "Enterprise value includes John Deere Financial's debt, which funds customer receivables, "
    "so EV multiples are not comparable with an industrial company's."
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "caveats.yaml"
    path.write_text(text)
    return path


def test_shipped_file_has_exactly_the_three_de_entries_in_order() -> None:
    assert load_caveats() == {
        "DE": (
            Caveat(codes=DE_CODES, text=DE_TEXT),
            Caveat(codes=frozenset({"gross_margin", "dso"}), text=DE_REVENUE_TEXT),
            Caveat(codes=DE_EV_CODES, text=DE_EV_TEXT),
        )
    }


def test_code_in_two_caveats_of_one_ticker_raises(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "DE:\n  - codes: [roe, roa]\n    text: one\n  - codes: [dso, roa]\n    text: two\n",
    )
    with pytest.raises(RegistryError, match="roa"):
        load_caveats(path)


def test_same_code_for_different_tickers_is_allowed(tmp_path: Path) -> None:
    path = write(
        tmp_path, "DE:\n  - codes: [roa]\n    text: one\nCAT:\n  - codes: [roa]\n    text: two\n"
    )
    assert set(load_caveats(path)) == {"DE", "CAT"}


def test_ticker_upper_cased_and_entries_kept_in_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "aapl:\n  - codes: [roe]\n    text: one\n  - codes: [roa, dso]\n    text: two\n",
    )
    assert load_caveats(path) == {
        "AAPL": (
            Caveat(codes=frozenset({"roe"}), text="one"),
            Caveat(codes=frozenset({"roa", "dso"}), text="two"),
        )
    }


def test_empty_file_means_no_caveats(tmp_path: Path) -> None:
    assert load_caveats(write(tmp_path, "")) == {}


def test_unknown_ratio_code_raises(tmp_path: Path) -> None:
    path = write(tmp_path, "DE:\n  - codes: [roe, bogus]\n    text: t\n")
    with pytest.raises(RegistryError, match="bogus"):
        load_caveats(path)


def test_empty_codes_raises(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="DE"):
        load_caveats(write(tmp_path, "DE:\n  - codes: []\n    text: t\n"))


@pytest.mark.parametrize("text", ['""', '"   "', "null"])
def test_empty_text_raises(tmp_path: Path, text: str) -> None:
    with pytest.raises(RegistryError, match="DE"):
        load_caveats(write(tmp_path, f"DE:\n  - codes: [roe]\n    text: {text}\n"))


@pytest.mark.parametrize(
    "content",
    [
        "- DE\n",  # not a mapping
        "DE: oops\n",  # entries not a list
        "DE:\n  - just text\n",  # entry not a mapping
        "DE:\n  - codes: roe\n    text: t\n",  # codes not a list
        "DE:\n  - codes: [1]\n    text: t\n",  # code not a string
        "DE:\n  - text: t\n",  # codes missing
        "DE:\n  - codes: [roe]\n    text: t\n    extra: 1\n",  # unknown key
        "DE:\n  - codes: [roe]\n    text: 5\n",  # text not a string
        "1:\n  - codes: [roe]\n    text: t\n",  # ticker not a string
        "DE:\n  - codes: [roe]\n    text: t\nde:\n  - codes: [roa]\n    text: u\n",  # dup ticker
    ],
)
def test_malformed_file_raises(tmp_path: Path, content: str) -> None:
    with pytest.raises(RegistryError):
        load_caveats(write(tmp_path, content))


# --- M7b S4: a generated caveat for a combined operand --------------------------------------


def _combined_inputs(**values: tuple[int | None, ...]):  # type: ignore[no-untyped-def]
    from bedrock.mapping.mapper import map_facts
    from bedrock.mapping.vintage import select_vintage
    from bedrock.ratios.calculator import RatioInputs
    from bedrock.statements.build import build_statement
    from tests.engine_data import facts
    from tests.test_combined_lines import BS_ITEMS, BS_MAP, balances

    canonical = map_facts(select_vintage(facts(balances(**values))), BS_MAP, BS_ITEMS)
    table = {s: build_statement(canonical, BS_ITEMS, s, "annual") for s in ("IS", "CF", "BS")}
    return RatioInputs(table["IS"], table["CF"], table["BS"])


def _ratio(code: str, numerator: str):  # type: ignore[no-untyped-def]
    from bedrock.ratios.registry import Ratio

    return Ratio(
        code=code,
        label=code,
        category="Liquidity",
        unit="x",
        definition=code,
        numerator=numerator,
        denominator="total_current_liabilities",
    )


COMBINED_AP = {
    "LiabilitiesCurrent": (100, 100, 100, 100),
    "AccountsPayableAndAccruedLiabilitiesCurrent": (60, 61, 62, 63),
}


def test_a_ratio_reading_a_carrier_says_what_it_includes() -> None:
    from bedrock.ratios.calculator import compute_ratios

    ratios = (_ratio("payables_share", "accounts_payable"), _ratio("plain", "revenue"))
    table = compute_ratios(_combined_inputs(**COMBINED_AP), "annual", (), ratios)
    rows = {r.code: r for r in table.rows}

    assert rows["payables_share"].caveat == "Accounts payable includes Accrued liabilities."
    assert rows["plain"].caveat is None


def test_a_ratio_reading_a_covered_line_names_its_carrier() -> None:
    from bedrock.ratios.calculator import compute_ratios

    ratios = (_ratio("accrued_share", "accrued_liabilities"),)
    table = compute_ratios(_combined_inputs(**COMBINED_AP), "annual", (), ratios)

    assert table.rows[0].caveat == "Accounts payable includes Accrued liabilities."


def test_the_generated_caveat_is_appended_to_the_company_caveat() -> None:
    from bedrock.ratios.calculator import compute_ratios
    from bedrock.ratios.explain import explain_ratio

    inputs = _combined_inputs(**COMBINED_AP)
    ratios = (_ratio("payables_share", "accounts_payable"),)
    caveats = (Caveat(frozenset({"payables_share"}), "Company text."),)
    table = compute_ratios(inputs, "annual", caveats, ratios)
    explained = explain_ratio(inputs, "annual", "payables_share", (2023, "FY"), caveats, ratios)

    expected = "Company text. Accounts payable includes Accrued liabilities."
    assert table.rows[0].caveat == explained.caveat == expected


def test_no_marker_no_generated_caveat() -> None:
    from bedrock.ratios.calculator import compute_ratios

    inputs = _combined_inputs(
        LiabilitiesCurrent=(100, 100, 100, 100), AccountsPayableCurrent=(40, 41, 42, 43)
    )
    table = compute_ratios(inputs, "annual", (), (_ratio("payables_share", "accounts_payable"),))

    assert table.rows[0].caveat is None


def test_a_combined_line_covering_no_row_says_it_holds_other_lines() -> None:
    from bedrock.ratios.calculator import generated_caveat

    assert generated_caveat({"Change in payables": ()}) == (
        "Change in payables includes other lines reported with it."
    )
    assert generated_caveat({"Cash": ("Short-term investments", "Receivables")}) == (
        "Cash includes Short-term investments and Receivables."
    )


# --- M7b: a covered operand counts 0 beside its carrier (the statement formulas' rule) ----------


def _value(inputs, numerator: str):  # type: ignore[no-untyped-def]
    from bedrock.ratios.calculator import Operands

    ratios = (_ratio("probe", numerator),)
    return Operands(inputs, "annual", ratios).ratio("probe", (2023, "FY"))


def test_a_covered_operand_counts_zero_beside_its_carrier_in_a_ratio_formula() -> None:
    inputs = _combined_inputs(**COMBINED_AP)

    # accrued liabilities is empty, its amount inside accounts payable (63 of 100 at the year end)
    assert _value(inputs, "accounts_payable + accrued_liabilities") == Decimal("0.63")


def test_a_covered_operand_alone_leaves_the_ratio_empty() -> None:
    assert _value(_combined_inputs(**COMBINED_AP), "accrued_liabilities") is None


def test_a_covered_operand_of_the_other_sign_than_its_carrier_leaves_the_ratio_empty() -> None:
    inputs = _combined_inputs(**COMBINED_AP)

    assert _value(inputs, "accounts_payable - accrued_liabilities") is None


def test_an_operand_missing_for_another_reason_still_empties_the_ratio() -> None:
    inputs = _combined_inputs(
        LiabilitiesCurrent=(100, 100, 100, 100), AccountsPayableCurrent=(40, 41, 42, 43)
    )

    assert _value(inputs, "accounts_payable + accrued_liabilities") is None


def test_a_metric_counts_a_covered_input_as_zero_when_its_carrier_is_an_input_too() -> None:
    from bedrock.mapping.mapper import map_facts
    from bedrock.mapping.vintage import select_vintage
    from bedrock.ratios.calculator import Operands, RatioInputs
    from bedrock.statements.build import build_statement
    from tests.engine_data import facts, item, mappings
    from tests.test_combined_lines import B, balances

    items = [
        item("revenue"),
        item("total_debt", "BS", kind="instant"),
        item("total_equity", "BS", kind="instant"),
        item("cash", "BS", kind="instant"),
        item("short_term_investments", "BS", kind="instant"),
    ]
    maps = mappings(
        ("revenue", "Revenues", 0),
        ("total_debt", "DebtAndFinanceLeaseObligations", 0),
        ("total_equity", "StockholdersEquity", 0),
        ("cash", "CashAndCashEquivalentsAtCarryingValue", 0),
        ("cash", "CashCashEquivalentsAndShortTermInvestments", 1, False, "short_term_investments"),
        ("short_term_investments", "ShortTermInvestments", 0),
    )
    rows = balances(
        DebtAndFinanceLeaseObligations=(50, 50, 50, 50),
        StockholdersEquity=(80, 80, 80, 80),
        CashCashEquivalentsAndShortTermInvestments=(30, 30, 30, 30),
    )
    canonical = map_facts(select_vintage(facts(rows)), maps, items)
    table = {s: build_statement(canonical, items, s, "annual") for s in ("IS", "CF", "BS")}
    ops = Operands(RatioInputs(table["IS"], table["CF"], table["BS"]), "annual")

    # debt 50 + equity 80 − cash 30, which already holds the short-term investments
    assert ops.value("invested_capital", (2023, "FY")) == 100 * B
