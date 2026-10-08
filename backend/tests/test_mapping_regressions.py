# ruff: noqa: E501  (the table rows carry 10-K accession numbers and figures in trailing comments)
"""One assertion per mapping decision of M1 S3, on the recorded fixtures (map-xbrl step 6).

Each case pins the mapped value of a canonical code for two or more fiscal years. Figures come from
the 10-K statements unless the comment says they come from companyfacts. The traps they guard:
a concept that is a component, not the total (MSFT `CostOfGoodsSold`, COST `SalesRevenueNet`), a tag
that changes between years, and a later restatement winning over the original 10-K.
"""

from decimal import Decimal

import pytest

from bedrock.statements.explain import explain_cell
from tests.statements_pipeline import Pipeline, run_pipeline


def usd(millions: str | int) -> Decimal:
    return Decimal(str(millions)) * 1_000_000


def mapped(ticker: str, code: str, period_key: str, freq: str = "annual") -> Decimal | None:
    pipeline = run_pipeline(ticker)
    statement = next(i.statement for i in pipeline.items if i.code == code)
    table = (pipeline.annual if freq == "annual" else pipeline.quarterly)[statement]
    row = next(r for r in table.rows if r.code == code)
    return row.values[[p.key for p in table.periods].index(period_key)]


def source_concept(pipeline: Pipeline, code: str, fiscal_year_end: str) -> str:
    """The concept that supplied the full-year (or instant) value of `code` ending that day."""
    frame = pipeline.canonical
    rows = frame[(frame["code"] == code) & (frame["period_end"].astype(str) == fiscal_year_end)]
    full_year = [
        start is None or (end - start).days >= 350
        for start, end in zip(rows["period_start"], rows["period_end"], strict=True)
    ]
    rows = rows[full_year]
    assert len(rows) == 1, f"{code} {fiscal_year_end}: {len(rows)} source facts"
    return str(rows.iloc[0]["concept"])


# (ticker, code, period, expected). Dollar figures are written in millions.
INCOME_STATEMENT: list[tuple[str, str, str, Decimal]] = [
    # AAPL: 10-Ks FY2015 (0001193125-15-356351), FY2020 (0000320193-20-000096), FY2025 (0000320193-25-000079)
    ("AAPL", "cost_of_revenue", "FY2015", usd(140_089)),
    ("AAPL", "cost_of_revenue", "FY2025", usd(220_960)),
    ("AAPL", "rnd", "FY2015", usd(8_067)),
    ("AAPL", "rnd", "FY2020", usd(18_752)),
    ("AAPL", "rnd", "FY2025", usd(34_550)),
    ("AAPL", "sga", "FY2015", usd(14_329)),
    ("AAPL", "sga", "FY2020", usd(19_916)),
    ("AAPL", "sga", "FY2025", usd(27_601)),
    ("AAPL", "pretax_income", "FY2015", usd(72_515)),
    ("AAPL", "pretax_income", "FY2020", usd(67_091)),
    ("AAPL", "pretax_income", "FY2025", usd(132_729)),
    ("AAPL", "income_tax", "FY2015", usd(19_121)),
    ("AAPL", "income_tax", "FY2020", usd(9_680)),
    ("AAPL", "income_tax", "FY2025", usd(20_719)),
    ("AAPL", "net_income_common", "FY2015", usd(53_394)),
    ("AAPL", "net_income_common", "FY2025", usd(112_010)),
    ("AAPL", "eps_basic", "FY2015", Decimal("9.28")),
    ("AAPL", "eps_basic", "FY2020", Decimal("3.31")),
    ("AAPL", "eps_basic", "FY2025", Decimal("7.49")),
    ("AAPL", "shares_basic", "FY2015", Decimal(5_753_421_000)),
    ("AAPL", "shares_basic", "FY2020", Decimal(17_352_119_000)),
    ("AAPL", "shares_diluted", "FY2015", Decimal(5_793_069_000)),
    ("AAPL", "shares_diluted", "FY2020", Decimal(17_528_214_000)),
    # AAPL interest expense: companyfacts only (the 10-K face statement does not show it).
    ("AAPL", "interest_expense", "FY2015", usd(733)),
    ("AAPL", "interest_expense", "FY2020", usd(2_873)),
    ("AAPL", "interest_expense", "FY2023", usd(3_933)),
    # MSFT: 10-Ks FY2015 (0001193125-15-272806), FY2020 (0001564590-20-034944), FY2026 (0001193125-26-323660)
    ("MSFT", "cost_of_revenue", "FY2015", usd(33_038)),  # not CostOfGoodsSold, goods only: 21,410
    ("MSFT", "cost_of_revenue", "FY2020", usd(46_078)),
    ("MSFT", "cost_of_revenue", "FY2026", usd(106_374)),
    ("MSFT", "rnd", "FY2015", usd(12_046)),
    ("MSFT", "rnd", "FY2020", usd(19_269)),
    ("MSFT", "rnd", "FY2026", usd(35_562)),
    ("MSFT", "pretax_income", "FY2015", usd(18_507)),  # older tag, until FY2021
    ("MSFT", "pretax_income", "FY2020", usd(53_036)),
    ("MSFT", "pretax_income", "FY2026", usd(165_934)),  # newer tag, from FY2020
    ("MSFT", "income_tax", "FY2015", usd(6_314)),
    ("MSFT", "income_tax", "FY2020", usd(8_755)),
    ("MSFT", "income_tax", "FY2026", usd(32_185)),
    ("MSFT", "net_income", "FY2015", usd(12_193)),
    ("MSFT", "net_income", "FY2026", usd(133_749)),
    ("MSFT", "eps_basic", "FY2015", Decimal("1.49")),
    ("MSFT", "eps_basic", "FY2020", Decimal("5.82")),
    ("MSFT", "eps_basic", "FY2026", Decimal("18.00")),
    ("MSFT", "shares_basic", "FY2015", usd(8_177)),
    ("MSFT", "shares_basic", "FY2020", usd(7_610)),
    ("MSFT", "shares_basic", "FY2026", usd(7_429)),
    ("MSFT", "shares_diluted", "FY2015", usd(8_254)),
    ("MSFT", "shares_diluted", "FY2020", usd(7_683)),
    ("MSFT", "shares_diluted", "FY2026", usd(7_453)),
    # MSFT interest expense: companyfacts only. InterestExpense ends FY2024, then InterestExpenseNonoperating.
    ("MSFT", "interest_expense", "FY2015", usd(781)),
    ("MSFT", "interest_expense", "FY2024", usd(2_935)),
    ("MSFT", "interest_expense", "FY2026", usd(3_051)),
    # MSFT revenue restated for ASC 606 in FY2016-17: the newer tag comes first, so revenue and cost
    # of revenue stay on one basis (91,154 - 32,780 = 58,374 = GrossProfit), not the original 85,320.
    ("MSFT", "revenue", "FY2016", usd(91_154)),
    ("MSFT", "revenue", "FY2017", usd(96_571)),
    ("MSFT", "gross_profit", "FY2016", usd(58_374)),
    # COST: 10-Ks FY2015 (0000909832-15-000014), FY2020 (0000909832-20-000017), FY2026 (0000909832-26-000093)
    (
        "COST",
        "revenue",
        "FY2015",
        usd(116_199),
    ),  # `Revenues`, not SalesRevenueNet (no membership fees)
    ("COST", "revenue", "FY2026", usd(303_154)),
    ("COST", "cost_of_revenue", "FY2015", usd(101_065)),  # CostOfGoodsSold, deprecated in 2018
    ("COST", "cost_of_revenue", "FY2020", usd(144_939)),
    ("COST", "cost_of_revenue", "FY2026", usd(264_279)),
    ("COST", "sga", "FY2024", usd(22_810)),
    ("COST", "sga", "FY2026", usd(27_190)),
    # The FY2022 10-K folded preopening expense into SG&A for FY2020: the 10-K said 16,332, the
    # latest vintage says 16,387. The older value stays available as a vintage.
    ("COST", "sga", "FY2020", usd(16_387)),
    ("COST", "interest_expense", "FY2020", usd(160)),
    ("COST", "interest_expense", "FY2026", usd(145)),
    ("COST", "pretax_income", "FY2020", usd(5_367)),
    ("COST", "pretax_income", "FY2026", usd(12_251)),
    ("COST", "income_tax", "FY2020", usd(1_308)),
    ("COST", "income_tax", "FY2026", usd(3_025)),
    ("COST", "net_income", "FY2015", usd(2_409)),  # ProfitLoss: includes noncontrolling interests
    ("COST", "net_income", "FY2020", usd(4_059)),
    ("COST", "net_income", "FY2026", usd(9_226)),  # ProfitLoss ends FY2025: NetIncomeLoss fills in
    ("COST", "net_income_common", "FY2015", usd(2_377)),
    ("COST", "net_income_common", "FY2020", usd(4_002)),
    ("COST", "net_income_nci", "FY2020", usd(57)),
    ("COST", "eps_basic", "FY2020", Decimal("9.05")),
    ("COST", "eps_basic", "FY2026", Decimal("20.78")),
    ("COST", "shares_basic", "FY2020", Decimal(442_297_000)),
    ("COST", "shares_basic", "FY2026", Decimal(443_953_000)),
    ("COST", "shares_diluted", "FY2020", Decimal(443_901_000)),
    ("COST", "shares_diluted", "FY2026", Decimal(444_427_000)),
    # COST has no gross profit line: it is derived, revenue (with membership fees) minus merchandise costs.
    ("COST", "gross_profit", "FY2015", usd(15_134)),
    ("COST", "gross_profit", "FY2020", usd(21_822)),
]


@pytest.mark.parametrize(("ticker", "code", "period", "expected"), INCOME_STATEMENT)
def test_income_statement_mapping(ticker: str, code: str, period: str, expected: Decimal) -> None:
    assert mapped(ticker, code, period) == expected


def test_msft_has_no_single_sga_concept_so_the_residual_absorbs_sales_and_marketing_and_g_and_a() -> (
    None
):
    # FY2020 10-K: sales and marketing 19,598 + general and administrative 5,111 = 24,709.
    assert mapped("MSFT", "sga", "FY2020") is None
    assert mapped("MSFT", "other_operating_expenses", "FY2020") == usd(24_709)
    # FY2026: 26,710 + 7,956 = 34,666.
    assert mapped("MSFT", "other_operating_expenses", "FY2026") == usd(34_666)


def test_costco_reports_no_research_and_development() -> None:
    assert mapped("COST", "rnd", "FY2020") is None
    assert mapped("COST", "rnd", "FY2026") is None


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT"])
def test_companies_without_noncontrolling_interests_have_no_nci_income(ticker: str) -> None:
    assert mapped(ticker, "net_income_nci", "FY2020") is None
    # net income and net income to common are both mapped, so neither depends on the missing NCI.
    assert mapped(ticker, "net_income", "FY2020") == mapped(ticker, "net_income_common", "FY2020")


def test_the_source_concept_follows_the_tag_switch() -> None:
    aapl, cost = run_pipeline("AAPL"), run_pipeline("COST")
    assert source_concept(aapl, "revenue", "2015-09-26") == "SalesRevenueNet"
    assert source_concept(aapl, "revenue", "2025-09-27") == (
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert source_concept(cost, "revenue", "2015-08-30") == "Revenues"
    assert source_concept(cost, "cost_of_revenue", "2015-08-30") == "CostOfGoodsSold"
    assert source_concept(cost, "cost_of_revenue", "2026-08-30") == "CostOfGoodsAndServicesSold"


def test_reported_and_derived_gross_profit_are_marked() -> None:
    aapl, cost = run_pipeline("AAPL"), run_pipeline("COST")
    gross = {
        ticker: next(r for r in p.annual["IS"].rows if r.code == "gross_profit")
        for ticker, p in (("AAPL", aapl), ("COST", cost))
    }
    keys = {t: [p.key for p in run_pipeline(t).annual["IS"].periods] for t in ("AAPL", "COST")}
    assert gross["AAPL"].provenance[keys["AAPL"].index("FY2015")] == "reported"
    assert gross["COST"].provenance[keys["COST"].index("FY2020")] == "derived"


# Balance sheet. FY2015 figures are only used where the FY2016 10-K restated nothing (ASU 2015-03 and
# 2015-17 moved deferred taxes and debt issuance costs): the engine shows the latest vintage.
BALANCE_SHEET: list[tuple[str, str, str, Decimal]] = [
    # AAPL, 10-Ks FY2015 / FY2020 / FY2025
    ("AAPL", "short_term_investments", "FY2015", usd(20_481)),  # AvailableForSaleSecuritiesCurrent
    ("AAPL", "short_term_investments", "FY2020", usd(52_927)),  # MarketableSecuritiesCurrent
    ("AAPL", "short_term_investments", "FY2025", usd(18_763)),
    ("AAPL", "receivables", "FY2015", usd(16_849)),  # trade only; vendor non-trade stays in "other"
    ("AAPL", "receivables", "FY2020", usd(16_120)),
    ("AAPL", "receivables", "FY2025", usd(39_777)),
    ("AAPL", "inventory", "FY2015", usd(2_349)),
    ("AAPL", "inventory", "FY2020", usd(4_061)),
    ("AAPL", "inventory", "FY2025", usd(5_718)),
    ("AAPL", "total_current_assets", "FY2015", usd(89_378)),
    ("AAPL", "total_current_assets", "FY2020", usd(143_713)),
    ("AAPL", "total_current_assets", "FY2025", usd(147_957)),
    ("AAPL", "ppe_net", "FY2015", usd(22_471)),
    ("AAPL", "ppe_net", "FY2020", usd(36_766)),
    ("AAPL", "ppe_net", "FY2025", usd(49_834)),
    ("AAPL", "goodwill", "FY2015", usd(5_116)),  # last separate line: FY2017
    ("AAPL", "intangibles", "FY2015", usd(3_893)),
    (
        "AAPL",
        "long_term_investments",
        "FY2015",
        usd(164_065),
    ),  # AvailableForSaleSecuritiesNoncurrent
    ("AAPL", "long_term_investments", "FY2020", usd(100_887)),  # MarketableSecuritiesNoncurrent
    ("AAPL", "long_term_investments", "FY2025", usd(77_723)),
    ("AAPL", "accounts_payable", "FY2015", usd(35_490)),
    ("AAPL", "accounts_payable", "FY2020", usd(42_296)),
    ("AAPL", "accounts_payable", "FY2025", usd(69_860)),
    ("AAPL", "deferred_revenue_current", "FY2015", usd(8_940)),  # DeferredRevenueCurrent
    (
        "AAPL",
        "deferred_revenue_current",
        "FY2020",
        usd(6_643),
    ),  # ContractWithCustomerLiabilityCurrent
    ("AAPL", "deferred_revenue_current", "FY2025", usd(9_055)),
    ("AAPL", "accrued_liabilities", "FY2015", usd(25_181)),  # "Accrued expenses", last line: FY2017
    ("AAPL", "total_current_liabilities", "FY2015", usd(80_610)),
    ("AAPL", "total_current_liabilities", "FY2020", usd(105_392)),
    ("AAPL", "total_current_liabilities", "FY2025", usd(165_631)),
    (
        "AAPL",
        "long_term_debt",
        "FY2015",
        usd(53_329),
    ),  # 53,463 in the FY2015 10-K, restated in FY2016
    ("AAPL", "long_term_debt", "FY2020", usd(98_667)),
    ("AAPL", "long_term_debt", "FY2025", usd(78_328)),
    ("AAPL", "common_stock_apic", "FY2015", usd(27_416)),
    ("AAPL", "common_stock_apic", "FY2020", usd(50_779)),
    ("AAPL", "common_stock_apic", "FY2025", usd(93_568)),
    # Until FY2013 Apple tags the combined line CommonStockValue: the AAPL override (companyfacts only).
    ("AAPL", "common_stock_apic", "FY2012", usd(16_422)),
    ("AAPL", "common_stock_apic", "FY2013", usd(19_764)),
    ("AAPL", "retained_earnings", "FY2015", usd(92_284)),
    ("AAPL", "retained_earnings", "FY2020", usd(14_966)),
    ("AAPL", "retained_earnings", "FY2025", usd(-14_264)),
    ("AAPL", "aoci", "FY2015", usd(-345)),
    ("AAPL", "aoci", "FY2020", usd(-406)),
    ("AAPL", "aoci", "FY2025", usd(-5_571)),
    ("AAPL", "equity_parent", "FY2015", usd(119_355)),
    ("AAPL", "equity_parent", "FY2020", usd(65_339)),
    (
        "AAPL",
        "total_equity",
        "FY2025",
        usd(73_733),
    ),  # no NCI concept: falls back to StockholdersEquity
    ("AAPL", "total_liabilities_and_equity", "FY2020", usd(323_888)),
    # AAPL right-of-use assets: companyfacts only (inside "other non-current assets" on the face).
    ("AAPL", "operating_lease_rou", "FY2020", usd(8_570)),
    ("AAPL", "operating_lease_rou", "FY2025", usd(11_205)),
    ("AAPL", "operating_lease_liabilities_noncurrent", "FY2020", usd(7_745)),
    ("AAPL", "operating_lease_liabilities_noncurrent", "FY2025", usd(10_911)),
    # MSFT, 10-Ks FY2015 / FY2020 / FY2026
    ("MSFT", "short_term_investments", "FY2015", usd(90_931)),  # AvailableForSaleSecuritiesCurrent
    ("MSFT", "short_term_investments", "FY2020", usd(122_951)),  # ShortTermInvestments
    ("MSFT", "short_term_investments", "FY2026", usd(55_908)),
    ("MSFT", "receivables", "FY2015", usd(17_908)),
    ("MSFT", "receivables", "FY2020", usd(32_011)),
    ("MSFT", "receivables", "FY2026", usd(80_876)),
    ("MSFT", "inventory", "FY2015", usd(2_902)),
    ("MSFT", "inventory", "FY2020", usd(1_895)),
    ("MSFT", "inventory", "FY2026", usd(1_397)),
    ("MSFT", "total_current_assets", "FY2020", usd(181_915)),
    ("MSFT", "total_current_assets", "FY2026", usd(207_710)),
    ("MSFT", "ppe_net", "FY2015", usd(14_731)),
    ("MSFT", "ppe_net", "FY2020", usd(44_151)),
    ("MSFT", "ppe_net", "FY2026", usd(313_076)),
    ("MSFT", "operating_lease_rou", "FY2020", usd(8_753)),
    ("MSFT", "operating_lease_rou", "FY2026", usd(24_177)),
    ("MSFT", "goodwill", "FY2015", usd(16_939)),
    ("MSFT", "goodwill", "FY2020", usd(43_351)),
    ("MSFT", "goodwill", "FY2026", usd(119_651)),
    ("MSFT", "intangibles", "FY2015", usd(4_835)),  # FiniteLivedIntangibleAssetsNet
    ("MSFT", "intangibles", "FY2020", usd(7_038)),
    ("MSFT", "intangibles", "FY2026", usd(18_609)),
    ("MSFT", "long_term_investments", "FY2015", usd(12_053)),
    ("MSFT", "long_term_investments", "FY2020", usd(2_965)),
    ("MSFT", "long_term_investments", "FY2026", usd(36_348)),
    ("MSFT", "accounts_payable", "FY2015", usd(6_591)),
    ("MSFT", "accounts_payable", "FY2020", usd(12_530)),
    ("MSFT", "accounts_payable", "FY2026", usd(42_416)),
    ("MSFT", "deferred_revenue_current", "FY2015", usd(23_223)),  # DeferredRevenueCurrent
    (
        "MSFT",
        "deferred_revenue_current",
        "FY2020",
        usd(36_000),
    ),  # ContractWithCustomerLiabilityCurrent
    ("MSFT", "deferred_revenue_current", "FY2026", usd(72_965)),
    ("MSFT", "total_current_liabilities", "FY2020", usd(72_310)),
    ("MSFT", "total_current_liabilities", "FY2026", usd(168_825)),
    ("MSFT", "long_term_debt", "FY2015", usd(27_808)),
    ("MSFT", "long_term_debt", "FY2020", usd(59_578)),
    ("MSFT", "long_term_debt", "FY2026", usd(31_067)),
    ("MSFT", "operating_lease_liabilities_noncurrent", "FY2020", usd(7_671)),
    ("MSFT", "operating_lease_liabilities_noncurrent", "FY2026", usd(16_532)),
    ("MSFT", "common_stock_apic", "FY2015", usd(68_465)),
    ("MSFT", "common_stock_apic", "FY2020", usd(80_552)),
    ("MSFT", "common_stock_apic", "FY2026", usd(117_406)),
    ("MSFT", "retained_earnings", "FY2015", usd(9_096)),
    ("MSFT", "retained_earnings", "FY2020", usd(34_566)),
    ("MSFT", "retained_earnings", "FY2026", usd(328_265)),
    ("MSFT", "aoci", "FY2015", usd(2_522)),
    ("MSFT", "aoci", "FY2020", usd(3_186)),
    ("MSFT", "aoci", "FY2026", usd(-3_284)),
    ("MSFT", "equity_parent", "FY2020", usd(118_304)),
    ("MSFT", "total_liabilities_and_equity", "FY2026", usd(758_376)),
    # COST, 10-Ks FY2015 / FY2020 / FY2026
    ("COST", "short_term_investments", "FY2015", usd(1_618)),
    ("COST", "short_term_investments", "FY2020", usd(1_028)),
    ("COST", "short_term_investments", "FY2026", usd(1_094)),
    (
        "COST",
        "receivables",
        "FY2015",
        usd(1_224),
    ),  # ReceivablesNetCurrent, not AccountsReceivable...
    ("COST", "receivables", "FY2020", usd(1_550)),
    ("COST", "receivables", "FY2026", usd(3_959)),
    ("COST", "inventory", "FY2015", usd(8_908)),
    ("COST", "inventory", "FY2020", usd(12_242)),
    ("COST", "inventory", "FY2026", usd(19_324)),
    ("COST", "total_current_assets", "FY2020", usd(28_120)),
    ("COST", "total_current_assets", "FY2026", usd(46_582)),
    ("COST", "ppe_net", "FY2015", usd(15_401)),
    ("COST", "ppe_net", "FY2020", usd(21_807)),
    ("COST", "ppe_net", "FY2026", usd(35_633)),
    ("COST", "operating_lease_rou", "FY2020", usd(2_788)),
    ("COST", "operating_lease_rou", "FY2026", usd(2_697)),
    ("COST", "accounts_payable", "FY2015", usd(9_011)),
    ("COST", "accounts_payable", "FY2020", usd(14_172)),
    ("COST", "accounts_payable", "FY2026", usd(22_591)),
    ("COST", "deferred_revenue_current", "FY2020", usd(1_851)),  # deferred membership fees
    ("COST", "deferred_revenue_current", "FY2026", usd(3_006)),
    # COST tags "accrued member rewards" AccruedLiabilitiesCurrent: a component, not all accruals.
    ("COST", "accrued_liabilities", "FY2020", usd(1_393)),
    ("COST", "accrued_liabilities", "FY2026", usd(3_037)),
    ("COST", "total_current_liabilities", "FY2020", usd(24_844)),
    ("COST", "total_current_liabilities", "FY2026", usd(43_952)),
    ("COST", "long_term_debt", "FY2020", usd(7_514)),
    ("COST", "long_term_debt", "FY2026", usd(3_914)),
    ("COST", "operating_lease_liabilities_noncurrent", "FY2020", usd(2_558)),
    ("COST", "operating_lease_liabilities_noncurrent", "FY2026", usd(2_414)),
    # Costco books par value (2) apart from additional paid-in capital: the APIC line maps.
    ("COST", "common_stock_apic", "FY2015", usd(5_218)),
    ("COST", "common_stock_apic", "FY2020", usd(6_698)),
    ("COST", "common_stock_apic", "FY2026", usd(8_830)),
    ("COST", "retained_earnings", "FY2015", usd(6_518)),
    ("COST", "retained_earnings", "FY2020", usd(12_879)),
    ("COST", "retained_earnings", "FY2026", usd(28_591)),
    ("COST", "aoci", "FY2015", usd(-1_121)),
    ("COST", "aoci", "FY2020", usd(-1_297)),
    ("COST", "aoci", "FY2026", usd(-1_620)),
    ("COST", "equity_parent", "FY2015", usd(10_617)),
    ("COST", "equity_parent", "FY2020", usd(18_284)),
    ("COST", "equity_parent", "FY2026", usd(35_803)),
    ("COST", "nci", "FY2015", usd(226)),
    ("COST", "nci", "FY2020", usd(421)),
    ("COST", "total_equity", "FY2020", usd(18_705)),  # StockholdersEquityIncludingPortion...
    ("COST", "total_equity", "FY2026", usd(35_803)),  # no NCI tag any more: StockholdersEquity
    # COST goodwill: companyfacts only (inside "other long-term assets" on the face).
    ("COST", "goodwill", "FY2020", usd(988)),
    ("COST", "goodwill", "FY2026", usd(994)),
]


@pytest.mark.parametrize(("ticker", "code", "period", "expected"), BALANCE_SHEET)
def test_balance_sheet_mapping(ticker: str, code: str, period: str, expected: Decimal) -> None:
    assert mapped(ticker, code, period) == expected


def test_companies_without_a_separate_line_leave_the_item_empty() -> None:
    # The neighbouring items are mapped, so an empty cell means "not reported", not "nothing built".
    assert mapped("AAPL", "total_assets", "FY2020") == usd(323_888)
    assert mapped("COST", "total_assets", "FY2020") == usd(55_556)
    assert mapped("AAPL", "nci", "FY2020") is None
    assert mapped("AAPL", "accrued_liabilities", "FY2020") is None  # relabelled "other" from FY2018
    assert mapped("AAPL", "goodwill", "FY2020") is None  # no separate goodwill line since FY2018
    assert (
        mapped("MSFT", "accrued_liabilities", "FY2020") is None
    )  # accrued compensation is not mapped
    assert mapped("COST", "long_term_investments", "FY2020") is None


def test_short_term_debt_is_left_empty_where_no_single_concept_covers_it() -> None:
    # A mapped concept must equal the canonical definition (current portion of long-term debt AND
    # commercial paper / short-term borrowings): Apple and Microsoft report them on separate lines,
    # so any one concept would understate the debt. Costco's only line is the current portion.
    assert mapped("AAPL", "short_term_debt", "FY2020") is None
    assert mapped("MSFT", "short_term_debt", "FY2020") is None
    assert mapped("COST", "short_term_debt", "FY2020") == usd(95)
    assert mapped("COST", "short_term_debt", "FY2015") == usd(1_283)
    assert mapped("COST", "short_term_debt", "FY2026") == usd(2_248)


def test_residual_lines_absorb_the_components_that_have_no_concept() -> None:
    # AAPL FY2020: other current liabilities = total (105,392) - payables (42,296) - deferred
    # revenue (6,643) = 56,453. It holds the term debt (8,773), commercial paper (4,996) and the
    # reported "other current liabilities" (42,684).
    assert mapped("AAPL", "other_current_liabilities", "FY2020") == usd(56_453)
    # MSFT FY2020: 72,310 - 12,530 - 36,000 = 23,780 (current debt 3,749, accrued compensation,
    # taxes and other).
    assert mapped("MSFT", "other_current_liabilities", "FY2020") == usd(23_780)


def test_a_restated_balance_sheet_keeps_every_vintage() -> None:
    # The FY2016 10-K restated FY2015 total assets (ASU 2015-03 and 2015-17). Every filing that
    # carried the date stays a vintage, the 10-Qs of FY2016 included (they repeat it as a comparative).
    aapl = run_pipeline("AAPL")
    cell = explain_cell(aapl.canonical, aapl.facts, aapl.items, "total_assets", 2015, "FY")
    assert cell.value == usd(290_345)
    assert cell.filing is not None
    assert cell.filing.accession_no == "0001628280-16-020309"  # 10-K FY2016
    first, last = cell.vintages[0], cell.vintages[-1]
    assert (first.value, first.accession_no, first.form) == (
        usd(290_479),
        "0001193125-15-356351",  # 10-K FY2015
        "10-K",
    )
    assert (last.value, last.accession_no) == (usd(290_345), "0001628280-16-020309")
    assert sorted({v.value for v in cell.vintages}) == [usd(290_345), usd(290_479)]


# Cash flow, 10-K figures in the displayed sign convention: outflows negative, a change in a working
# capital account is its cash effect (an increase in receivables is negative).
CASH_FLOW: list[tuple[str, str, str, Decimal]] = [
    # AAPL, 10-Ks FY2015 / FY2020 / FY2025
    ("AAPL", "cf_net_income", "FY2015", usd(53_394)),
    ("AAPL", "cf_net_income", "FY2025", usd(112_010)),
    # FY2015: DepreciationAmortizationAndAccretionNet (11,257). DepreciationDepletionAndAmortization is
    # the rounded depreciation note (9,200) that year, so it must rank behind.
    ("AAPL", "d_and_a", "FY2015", usd(11_257)),
    ("AAPL", "d_and_a", "FY2020", usd(11_056)),
    ("AAPL", "d_and_a", "FY2025", usd(11_698)),
    ("AAPL", "sbc", "FY2015", usd(3_586)),
    ("AAPL", "sbc", "FY2020", usd(6_829)),
    ("AAPL", "sbc", "FY2025", usd(12_863)),
    ("AAPL", "deferred_taxes", "FY2015", usd(1_382)),
    ("AAPL", "deferred_taxes", "FY2020", usd(-215)),
    # sign -1: IncreaseDecreaseInAccountsReceivable is -417. The FY2017 10-K restated FY2015 (it said 611).
    ("AAPL", "change_receivables", "FY2015", usd(417)),
    ("AAPL", "change_receivables", "FY2020", usd(6_917)),
    ("AAPL", "change_receivables", "FY2025", usd(-6_682)),
    ("AAPL", "change_inventory", "FY2015", usd(-238)),
    ("AAPL", "change_inventory", "FY2020", usd(-127)),
    ("AAPL", "change_inventory", "FY2025", usd(1_400)),
    (
        "AAPL",
        "change_payables",
        "FY2015",
        usd(5_001),
    ),  # restated in the FY2017 10-K, which said 5,400
    ("AAPL", "change_payables", "FY2020", usd(-4_062)),
    ("AAPL", "change_payables", "FY2025", usd(902)),
    ("AAPL", "acquisitions", "FY2015", usd(-343)),
    ("AAPL", "acquisitions", "FY2020", usd(-1_524)),
    ("AAPL", "purchases_of_investments", "FY2015", usd(-166_402)),
    ("AAPL", "purchases_of_investments", "FY2020", usd(-114_938)),
    ("AAPL", "purchases_of_investments", "FY2025", usd(-24_407)),
    ("AAPL", "debt_issued", "FY2015", usd(27_114)),
    ("AAPL", "debt_issued", "FY2020", usd(16_091)),
    ("AAPL", "debt_issued", "FY2025", usd(4_481)),
    ("AAPL", "debt_repaid", "FY2020", usd(-12_629)),
    ("AAPL", "debt_repaid", "FY2025", usd(-10_932)),
    ("AAPL", "buybacks", "FY2015", usd(-35_253)),
    ("AAPL", "buybacks", "FY2020", usd(-72_358)),
    ("AAPL", "buybacks", "FY2025", usd(-90_711)),
    ("AAPL", "dividends_paid", "FY2015", usd(-11_561)),
    ("AAPL", "dividends_paid", "FY2020", usd(-14_081)),
    ("AAPL", "dividends_paid", "FY2025", usd(-15_421)),
    ("AAPL", "cfi", "FY2015", usd(-56_274)),
    ("AAPL", "cfi", "FY2020", usd(-4_289)),
    ("AAPL", "cfi", "FY2025", usd(15_195)),
    ("AAPL", "cff", "FY2015", usd(-17_716)),
    ("AAPL", "cff", "FY2020", usd(-86_820)),
    ("AAPL", "cff", "FY2025", usd(-120_686)),
    ("AAPL", "net_change_in_cash", "FY2015", usd(7_276)),
    ("AAPL", "net_change_in_cash", "FY2020", usd(-10_435)),
    ("AAPL", "net_change_in_cash", "FY2025", usd(5_991)),
    # MSFT, 10-Ks FY2015 / FY2020 / FY2026
    ("MSFT", "cf_net_income", "FY2015", usd(12_193)),
    ("MSFT", "sbc", "FY2015", usd(2_574)),  # AllocatedShareBasedCompensationExpense until FY2014
    ("MSFT", "sbc", "FY2020", usd(5_289)),
    ("MSFT", "sbc", "FY2026", usd(12_405)),
    ("MSFT", "deferred_taxes", "FY2015", usd(224)),
    ("MSFT", "deferred_taxes", "FY2020", usd(11)),
    (
        "MSFT",
        "deferred_taxes",
        "FY2026",
        usd(14_189),
    ),  # the cash flow tag, not the tax note's 14,424
    ("MSFT", "change_receivables", "FY2015", usd(1_456)),
    ("MSFT", "change_receivables", "FY2020", usd(-2_577)),
    ("MSFT", "change_receivables", "FY2026", usd(-12_737)),
    ("MSFT", "change_inventory", "FY2015", usd(-272)),
    ("MSFT", "change_inventory", "FY2020", usd(168)),
    ("MSFT", "change_inventory", "FY2026", usd(-461)),
    ("MSFT", "change_payables", "FY2015", usd(-1_054)),
    ("MSFT", "change_payables", "FY2020", usd(3_018)),
    ("MSFT", "change_payables", "FY2026", usd(5_268)),
    ("MSFT", "purchases_of_investments", "FY2015", usd(-98_729)),
    ("MSFT", "purchases_of_investments", "FY2020", usd(-77_190)),
    ("MSFT", "purchases_of_investments", "FY2026", usd(-58_351)),
    ("MSFT", "debt_issued", "FY2024", usd(24_395)),  # ProceedsFromDebtMaturingInMoreThanThreeMonths
    ("MSFT", "debt_repaid", "FY2020", usd(-5_518)),
    ("MSFT", "debt_repaid", "FY2026", usd(-3_000)),
    ("MSFT", "buybacks", "FY2015", usd(-14_443)),
    ("MSFT", "buybacks", "FY2020", usd(-22_968)),
    ("MSFT", "buybacks", "FY2026", usd(-22_271)),
    ("MSFT", "dividends_paid", "FY2015", usd(-9_882)),
    ("MSFT", "dividends_paid", "FY2020", usd(-15_137)),
    ("MSFT", "dividends_paid", "FY2026", usd(-26_445)),
    ("MSFT", "cfi", "FY2015", usd(-23_001)),
    ("MSFT", "cfi", "FY2020", usd(-12_223)),
    ("MSFT", "cfi", "FY2026", usd(-139_500)),
    # ASU 2016-09 moved the excess tax benefit (588) from financing to operating cash flow, applied to
    # FY2015 in the FY2017 10-K: operating 29,080 -> 29,668, financing -9,080 -> -9,668.
    ("MSFT", "cfo", "FY2015", usd(29_668)),
    ("MSFT", "cff", "FY2015", usd(-9_668)),
    ("MSFT", "cff", "FY2020", usd(-46_031)),
    ("MSFT", "cff", "FY2026", usd(-52_546)),
    ("MSFT", "fx_effect", "FY2015", usd(-73)),
    ("MSFT", "fx_effect", "FY2020", usd(-201)),
    ("MSFT", "fx_effect", "FY2026", usd(-196)),
    ("MSFT", "net_change_in_cash", "FY2015", usd(-3_074)),
    ("MSFT", "net_change_in_cash", "FY2020", usd(2_220)),
    ("MSFT", "net_change_in_cash", "FY2026", usd(-9_307)),
    # COST, 10-Ks FY2015 / FY2020 / FY2026
    (
        "COST",
        "cf_net_income",
        "FY2015",
        usd(2_409),
    ),  # ProfitLoss, including noncontrolling interests
    ("COST", "cf_net_income", "FY2020", usd(4_059)),
    ("COST", "cf_net_income", "FY2026", usd(9_226)),
    ("COST", "d_and_a", "FY2015", usd(1_127)),
    ("COST", "d_and_a", "FY2020", usd(1_645)),
    ("COST", "d_and_a", "FY2026", usd(2_674)),
    ("COST", "sbc", "FY2015", usd(394)),
    ("COST", "sbc", "FY2020", usd(619)),
    ("COST", "sbc", "FY2026", usd(924)),
    ("COST", "change_inventory", "FY2015", usd(-890)),
    ("COST", "change_inventory", "FY2020", usd(-791)),
    ("COST", "change_inventory", "FY2026", usd(-1_153)),
    ("COST", "change_payables", "FY2015", usd(880)),
    ("COST", "change_payables", "FY2020", usd(2_261)),
    ("COST", "change_payables", "FY2026", usd(2_755)),
    ("COST", "acquisitions", "FY2020", usd(-1_163)),
    ("COST", "purchases_of_investments", "FY2015", usd(-1_501)),
    ("COST", "purchases_of_investments", "FY2020", usd(-1_626)),
    ("COST", "purchases_of_investments", "FY2026", usd(-788)),
    ("COST", "sales_maturities_of_investments", "FY2015", usd(1_434)),
    ("COST", "sales_maturities_of_investments", "FY2020", usd(1_678)),
    ("COST", "sales_maturities_of_investments", "FY2026", usd(811)),
    ("COST", "debt_issued", "FY2015", usd(1_125)),
    ("COST", "debt_issued", "FY2020", usd(3_992)),
    ("COST", "debt_issued", "FY2026", usd(496)),
    ("COST", "debt_repaid", "FY2020", usd(-3_200)),
    ("COST", "debt_repaid", "FY2026", usd(-69)),
    ("COST", "buybacks", "FY2015", usd(-481)),
    ("COST", "buybacks", "FY2020", usd(-196)),
    ("COST", "buybacks", "FY2026", usd(-848)),
    ("COST", "dividends_paid", "FY2015", usd(-2_865)),
    ("COST", "dividends_paid", "FY2020", usd(-1_479)),
    ("COST", "dividends_paid", "FY2026", usd(-2_458)),
    ("COST", "cfi", "FY2015", usd(-2_480)),
    ("COST", "cfi", "FY2020", usd(-3_891)),
    ("COST", "cfi", "FY2026", usd(-6_378)),
    ("COST", "cff", "FY2015", usd(-2_324)),
    ("COST", "cff", "FY2020", usd(-1_147)),
    ("COST", "cff", "FY2026", usd(-3_355)),
    ("COST", "fx_effect", "FY2015", usd(-418)),
    ("COST", "fx_effect", "FY2020", usd(70)),
    ("COST", "fx_effect", "FY2026", usd(-38)),
    ("COST", "net_change_in_cash", "FY2015", usd(-937)),
    ("COST", "net_change_in_cash", "FY2020", usd(3_893)),
    ("COST", "net_change_in_cash", "FY2026", usd(6_046)),
]


@pytest.mark.parametrize(("ticker", "code", "period", "expected"), CASH_FLOW)
def test_cash_flow_mapping(ticker: str, code: str, period: str, expected: Decimal) -> None:
    assert mapped(ticker, code, period) == expected


def test_cash_flow_lines_without_a_matching_concept_stay_empty() -> None:
    # Microsoft's "Depreciation, amortization, and other" is a custom tag that companyfacts omits;
    # the us-gaap `Depreciation` (34,300 in FY2026) is the note's component, not that line.
    assert mapped("MSFT", "d_and_a", "FY2026") is None
    # Costco tags its deferred taxes IncreaseDecreaseInDeferredIncomeTaxes, whose value is the
    # opposite sign of DeferredIncomeTaxExpenseBenefit (-306 for a 306 add-back): one sign cannot
    # fit both, so it is not mapped.
    assert mapped("COST", "deferred_taxes", "FY2026") is None
    # Apple and Microsoft report investment maturities and sales on two lines: no single concept.
    assert mapped("AAPL", "sales_maturities_of_investments", "FY2020") is None
    assert mapped("MSFT", "sales_maturities_of_investments", "FY2020") is None
    # Apple has no FX line and no receivables line at Costco.
    assert mapped("AAPL", "fx_effect", "FY2020") is None
    assert mapped("COST", "change_receivables", "FY2020") is None
    assert mapped("AAPL", "cfo", "FY2020") == usd(80_674)  # the neighbours are mapped


def test_other_investing_absorbs_the_investment_sales_and_maturities_it_has_no_concept_for() -> (
    None
):
    # AAPL FY2020: the residual is cfi (-4,289) - capex (-7,309) - acquisitions (-1,524) - purchases
    # (-114,938), with no sales/maturities line to subtract: 119,482, so the subtotal still foots.
    assert mapped("AAPL", "other_investing_activities", "FY2020") == usd(
        -4_289 + 7_309 + 1_524 + 114_938
    )


def test_a_cash_flow_total_equals_its_parts_where_all_are_mapped() -> None:
    # COST FY2026: cfo + cfi + cff + fx = net change in cash.
    parts = [mapped("COST", code, "FY2026") for code in ("cfo", "cfi", "cff", "fx_effect")]
    assert None not in parts
    assert sum(p for p in parts if p is not None) == mapped("COST", "net_change_in_cash", "FY2026")
