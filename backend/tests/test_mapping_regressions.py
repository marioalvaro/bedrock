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


def provenance_of(ticker: str, code: str, period_key: str, freq: str = "annual") -> str | None:
    pipeline = run_pipeline(ticker)
    statement = next(i.statement for i in pipeline.items if i.code == code)
    table = (pipeline.annual if freq == "annual" else pipeline.quarterly)[statement]
    row = next(r for r in table.rows if r.code == code)
    return row.provenance[[p.key for p in table.periods].index(period_key)]


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
    # FY2015 per-share and share counts are split-adjusted for the 4-for-1 of 2020-08-31:
    # the FY2015 10-K says 9.28, 5,753,421 and 5,793,069 thousand.
    ("AAPL", "eps_basic", "FY2015", Decimal("2.32")),
    ("AAPL", "eps_basic", "FY2020", Decimal("3.31")),
    ("AAPL", "eps_basic", "FY2025", Decimal("7.49")),
    ("AAPL", "shares_basic", "FY2015", Decimal(23_013_684_000)),
    ("AAPL", "shares_basic", "FY2020", Decimal(17_352_119_000)),
    ("AAPL", "shares_diluted", "FY2015", Decimal(23_172_276_000)),
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


def test_msft_sga_is_sales_and_marketing_plus_general_and_administrative() -> None:
    # Microsoft shows the two lines separately and no total, so the override sums them (anchor: sales
    # and marketing). 10-Ks: FY2015 15,713 + 4,611; FY2020 19,598 + 5,111; FY2026 26,710 + 7,956.
    assert mapped("MSFT", "sga", "FY2015") == usd(20_324)
    assert mapped("MSFT", "sga", "FY2020") == usd(24_709)
    assert mapped("MSFT", "sga", "FY2026") == usd(34_666)
    assert source_concept(run_pipeline("MSFT"), "sga", "2020-06-30") == (
        "SellingAndMarketingExpense + GeneralAndAdministrativeExpense"
    )
    # Gross profit - R&D - SG&A = operating income, so nothing is left for the residual.
    assert mapped("MSFT", "other_operating_expenses", "FY2020") == 0
    assert mapped("MSFT", "other_operating_expenses", "FY2026") == 0
    # Apple reports SG&A as one line, so its components in the notes (selling and marketing 19,524,
    # general and administrative 8,077 in FY2025) are not mapped: they would double count.
    assert mapped("AAPL", "sga", "FY2025") == usd(27_601)


def test_costco_reports_no_research_and_development() -> None:
    assert mapped("COST", "rnd", "FY2020") is None
    assert mapped("COST", "rnd", "FY2026") is None


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT"])
def test_companies_without_noncontrolling_interests_have_no_nci_income(ticker: str) -> None:
    # nothing is mapped, and the filing tags no NCI concept: the rule engine infers an exact 0
    assert mapped(ticker, "net_income_nci", "FY2020") == 0
    assert provenance_of(ticker, "net_income_nci", "FY2020") == "zero_inferred"
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
    ("AAPL", "long_term_debt", "FY2020", usd(99_304)),  # 98,667 + finance lease 637 (M3 S6)
    ("AAPL", "long_term_debt", "FY2025", usd(79_020)),  # 78,328 + finance lease 692 (M3 S6)
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
    ("MSFT", "long_term_debt", "FY2020", usd(69_074)),  # 59,578 + finance leases 9,496 (M3 S6)
    (
        "MSFT",
        "long_term_debt",
        "FY2026",
        usd(97_661),
    ),  # 31,067 + finance leases 66,594 (companyfacts, M3 S6)
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
    (
        "COST",
        "long_term_debt",
        "FY2020",
        usd(8_171),
    ),  # 7,514 + finance lease 657 (companyfacts, M3 S6)
    (
        "COST",
        "long_term_debt",
        "FY2026",
        usd(5_233),
    ),  # 3,914 + finance lease 1,319 (companyfacts, M3 S6)
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
    assert mapped("AAPL", "nci", "FY2020") == 0  # no NCI line: an inferred zero (M3 S7)
    assert provenance_of("AAPL", "nci", "FY2020") == "zero_inferred"
    assert mapped("AAPL", "accrued_liabilities", "FY2020") is None  # relabelled "other" from FY2018
    assert mapped("AAPL", "goodwill", "FY2020") is None  # no separate goodwill line since FY2018
    assert (
        mapped("MSFT", "accrued_liabilities", "FY2020") is None
    )  # accrued compensation is not mapped
    assert mapped("COST", "long_term_investments", "FY2020") is None


SHORT_TERM_DEBT: list[tuple[str, str, str, Decimal]] = [
    # AAPL, 10-Ks FY2015 (commercial paper 8,499 + current portion of long-term debt 2,500), FY2020
    # (4,996 + 8,773), FY2024 (9,967 + 10,912), FY2025 (7,979 + 12,350).
    ("AAPL", "short_term_debt", "FY2015", usd(10_999)),
    ("AAPL", "short_term_debt", "FY2020", usd(13_793)),  # + current finance lease 24 (M3 S6)
    ("AAPL", "short_term_debt", "FY2024", usd(21_023)),  # + current finance lease 144
    ("AAPL", "short_term_debt", "FY2025", usd(20_867)),  # + current finance lease 538
    # AAPL FY2014: commercial paper 6,308 and a current portion of 0.
    ("AAPL", "short_term_debt", "FY2014", usd(6_308)),
    # The FY2020 Q2 and Q3 10-Qs call the first line "Commercial paper and repurchase agreement(s)"
    # and tag it OtherShortTermBorrowings (10,029 and 11,166), next to term debt 10,392 and 7,509.
    ("AAPL", "short_term_debt", "FY2020Q2", usd(20_421)),
    ("AAPL", "short_term_debt", "FY2020Q3", usd(18_675)),
    # MSFT, 10-Ks: FY2015 short-term debt 4,985 + current portion 2,499; FY2017 9,072 + 1,049;
    # FY2020 only the current portion, 3,749 (no short-term debt line); FY2024 6,693 + 2,249; FY2025
    # 0 + 2,999; FY2026 9,227 (no line).
    ("MSFT", "short_term_debt", "FY2015", usd(7_484)),
    ("MSFT", "short_term_debt", "FY2017", usd(10_121)),
    ("MSFT", "short_term_debt", "FY2020", usd(3_749)),
    ("MSFT", "short_term_debt", "FY2024", usd(8_942)),
    ("MSFT", "short_term_debt", "FY2025", usd(2_999)),
    ("MSFT", "short_term_debt", "FY2026", usd(9_227)),
    # MSFT 10-Qs without a short-term debt line: Sep 30 2025 and Mar 31 2026 show the current portion.
    ("MSFT", "short_term_debt", "FY2026Q1", usd(7_832)),
    ("MSFT", "short_term_debt", "FY2026Q3", usd(8_839)),
    # COST: the current portion is its only line.
    ("COST", "short_term_debt", "FY2015", usd(1_293)),  # + current capital lease 10 (M3 S6)
    ("COST", "short_term_debt", "FY2020", usd(126)),  # + current finance lease 31
    ("COST", "short_term_debt", "FY2026", usd(2_342)),  # + current finance lease 94
]


@pytest.mark.parametrize(("ticker", "code", "period", "expected"), SHORT_TERM_DEBT)
def test_short_term_debt_is_the_whole_item(
    ticker: str, code: str, period: str, expected: Decimal
) -> None:
    freq = "quarterly" if "Q" in period else "annual"
    assert mapped(ticker, code, period, freq) == expected


def test_a_summed_short_term_debt_names_all_its_sources() -> None:
    aapl, msft = run_pipeline("AAPL"), run_pipeline("MSFT")
    assert source_concept(aapl, "short_term_debt", "2025-09-27") == (
        "CommercialPaper + LongTermDebtCurrent + FinanceLeaseLiabilityCurrent"
    )
    assert source_concept(aapl, "short_term_debt", "2015-09-26") == (
        "CommercialPaper + LongTermDebtCurrent"  # no lease tag before FY2020
    )
    assert source_concept(msft, "short_term_debt", "2015-06-30") == (
        "ShortTermBorrowings + LongTermDebtCurrent"
    )
    assert source_concept(msft, "short_term_debt", "2024-06-30") == (
        "CommercialPaper + LongTermDebtCurrent"
    )
    assert source_concept(msft, "short_term_debt", "2026-06-30") == "LongTermDebtCurrent"


def test_the_current_portion_alone_is_never_shown_for_apple() -> None:
    # Apple's commercial paper moved to another tag in two 10-Qs; a bare LongTermDebtCurrent fallback
    # would have shown 10,392 and 7,509 there, half of the debt. Without a fallback, a quarter whose
    # first line has no known tag stays empty instead.
    aapl = run_pipeline("AAPL")
    frame = aapl.canonical
    alone = frame[
        (frame["code"] == "short_term_debt") & (frame["concept"] == "LongTermDebtCurrent")
    ]
    assert len(alone) == 0


def test_residual_lines_absorb_the_components_that_have_no_concept() -> None:
    # AAPL FY2020: other current liabilities = total (105,392) - payables (42,296) - short-term debt
    # (13,793, now with the 24 current finance lease) - deferred revenue (6,643) = 42,660: the
    # reported "other current liabilities" line (42,684) less that lease, which moved into debt.
    assert mapped("AAPL", "other_current_liabilities", "FY2020") == usd(42_660)
    # MSFT FY2020: 72,310 - 12,530 - 3,749 - 36,000 = 20,031 (accrued compensation, taxes and other).
    assert mapped("MSFT", "other_current_liabilities", "FY2020") == usd(20_031)


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
    ("COST", "debt_issued", "FY2015", usd(1_176)),  # long-term 1,125 + short-term 51 (companyfacts)
    ("COST", "debt_issued", "FY2020", usd(3_992)),
    ("COST", "debt_issued", "FY2026", usd(1_049)),  # long-term 496 + short-term 553
    ("COST", "debt_repaid", "FY2020", usd(-3_200)),
    ("COST", "debt_repaid", "FY2026", usd(-646)),  # long-term 69 + short-term 577
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
    # Microsoft reports investment maturities and sales on two lines, and the sales tag stops after
    # FY2018 (the later "Sales of investments" is a custom tag companyfacts omits): see
    # `test_microsoft_investment_sales_and_maturities_are_left_empty`.
    assert mapped("MSFT", "sales_maturities_of_investments", "FY2020") is None
    # Apple has no FX line: the cash roll-forward gives it (0 in FY2020, derived, M3 S7). Costco
    # has no receivables line.
    assert mapped("AAPL", "fx_effect", "FY2020") == 0
    assert provenance_of("AAPL", "fx_effect", "FY2020") == "derived"
    assert mapped("COST", "change_receivables", "FY2020") is None
    assert mapped("AAPL", "cfo", "FY2020") == usd(80_674)  # the neighbours are mapped


INVESTMENT_SALES_AND_MATURITIES: list[tuple[str, Decimal]] = [
    # AAPL cash flow: "Proceeds from maturities of marketable securities" + "Proceeds from sales of
    # marketable securities". 10-Ks FY2015 (14,538 + 107,447; its FY2014 and FY2013 columns 18,810 +
    # 189,301 and 20,317 + 104,130), FY2020 (69,918 + 50,473; FY2018 55,881 + 47,838), FY2025
    # (40,907 + 12,890).
    ("FY2013", usd(124_447)),
    ("FY2014", usd(208_111)),
    ("FY2015", usd(121_985)),
    ("FY2018", usd(103_719)),
    ("FY2020", usd(120_391)),
    ("FY2025", usd(53_797)),
]


@pytest.mark.parametrize(("period", "expected"), INVESTMENT_SALES_AND_MATURITIES)
def test_apple_investment_sales_and_maturities_are_summed(period: str, expected: Decimal) -> None:
    assert mapped("AAPL", "sales_maturities_of_investments", period) == expected


def test_apple_investment_sales_follow_the_tag_switch_inside_the_sum() -> None:
    # The sales tag changed in FY2017-18 (both tags carry the same figure there, so only one may
    # count) and the maturities tag stayed; the group is anchored on the sales tag for that reason.
    aapl = run_pipeline("AAPL")
    assert source_concept(aapl, "sales_maturities_of_investments", "2015-09-26") == (
        "ProceedsFromSaleOfAvailableForSaleSecurities"
        " + ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities"
    )
    assert source_concept(aapl, "sales_maturities_of_investments", "2018-09-29") == (
        "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt"
        " + ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities"
    )


def test_costco_investment_sales_and_maturities_before_the_combined_line() -> None:
    # COST 10-K FY2011 cash flow: "Maturities of short-term investments" 2,614 / 1,428 / 1,780 and
    # "Sales of investments" 602 / 309 / 183 for FY2011 / FY2010 / FY2009. From FY2012 one combined
    # tag carries the same total (FY2012: 1,821 + 482 = 2,303), which the summed override reproduces.
    assert mapped("COST", "sales_maturities_of_investments", "FY2009") == usd(1_963)
    assert mapped("COST", "sales_maturities_of_investments", "FY2010") == usd(1_737)
    assert mapped("COST", "sales_maturities_of_investments", "FY2011") == usd(3_216)
    assert mapped("COST", "sales_maturities_of_investments", "FY2012") == usd(2_303)
    assert mapped("COST", "sales_maturities_of_investments", "FY2026") == usd(811)  # unchanged
    cost = run_pipeline("COST")
    assert source_concept(cost, "sales_maturities_of_investments", "2011-08-28") == (
        "ProceedsFromMaturitiesPrepaymentsAndCallsOfShorttermInvestments"
        " + ProceedsFromSaleOfShortTermInvestments"
    )
    assert source_concept(cost, "sales_maturities_of_investments", "2026-08-30") == (
        "ProceedsFromSaleAndMaturityOfMarketableSecurities"
    )


def test_microsoft_investment_sales_and_maturities_are_left_empty() -> None:
    # FY2019-26 "Sales of investments" (17,721 in FY2020) is not in companyfacts, so a sum could
    # only cover FY2008-18, and the residual would then jump by the missing line between FY2018
    # and FY2019. Neither tag alone is the whole item.
    assert mapped("MSFT", "sales_maturities_of_investments", "FY2018") is None
    assert mapped("MSFT", "sales_maturities_of_investments", "FY2020") is None


def test_other_investing_absorbs_what_has_no_concept() -> None:
    # AAPL FY2020: cfi (-4,289) - capex (-7,309) - acquisitions (-1,524) - purchases (-114,938) -
    # sales and maturities (120,391) = -909: the non-marketable securities and "Other" lines.
    assert mapped("AAPL", "other_investing_activities", "FY2020") == usd(-909)


def test_a_cash_flow_total_equals_its_parts_where_all_are_mapped() -> None:
    # COST FY2026: cfo + cfi + cff + fx = net change in cash.
    parts = [mapped("COST", code, "FY2026") for code in ("cfo", "cfi", "cff", "fx_effect")]
    assert None not in parts
    assert sum(p for p in parts if p is not None) == mapped("COST", "net_change_in_cash", "FY2026")


# --- M2 S2: dividends per share, goodwill impairment, temporary equity, shares outstanding -----

M2_LINES: list[tuple[str, str, str, Decimal | None]] = [
    # Dividends per share declared (a flow). AAPL is split-adjusted by split_adjust (7-for-1 of
    # 2014-06-09 is already in the filings; the 4-for-1 of 2020-08-31 is applied, so earlier years / 4).
    # 10-K FY2015 says 1.98 and 1.64 for FY2013, the FY2020 10-K says 0.68 / 0.75 / 0.795, FY2025 1.02.
    ("AAPL", "dividends_per_share", "FY2013", Decimal("0.41")),  # 1.64 / 4
    ("AAPL", "dividends_per_share", "FY2015", Decimal("0.495")),  # 1.98 / 4
    ("AAPL", "dividends_per_share", "FY2018", Decimal("0.68")),  # FY2020 10-K, already post-split
    ("AAPL", "dividends_per_share", "FY2020", Decimal("0.795")),
    ("AAPL", "dividends_per_share", "FY2025", Decimal("1.02")),
    # MSFT 10-Ks FY2020 (0001564590-20-034944): 1.68 / 1.84 / 2.04; FY2026 (0001193125-26-323660): 3 / 3.32 / 3.64
    ("MSFT", "dividends_per_share", "FY2018", Decimal("1.68")),
    ("MSFT", "dividends_per_share", "FY2020", Decimal("2.04")),
    ("MSFT", "dividends_per_share", "FY2024", Decimal("3")),
    ("MSFT", "dividends_per_share", "FY2026", Decimal("3.64")),
    # COST: FY2015 10-K says 6.51 (incl. a $5 special), 1.33 and 8.17 (incl. $7 special) for FY2013;
    # FY2026 10-K note: 5.54 and 4.92. FY2008-FY2013 come from the CashPaid fallback (same figures).
    ("COST", "dividends_per_share", "FY2013", Decimal("8.17")),
    ("COST", "dividends_per_share", "FY2014", Decimal("1.33")),
    ("COST", "dividends_per_share", "FY2015", Decimal("6.51")),
    ("COST", "dividends_per_share", "FY2025", Decimal("4.92")),
    ("COST", "dividends_per_share", "FY2026", Decimal("5.54")),
    ("COST", "dividends_per_share", "FY2021", None),  # FY2020-22 10-Ks show dividend totals only
    # Goodwill impairment: companyfacts omits zero lines, so only MSFT's FY2012 charge is a real figure.
    # MSFT 10-K FY2012 (0001193125-12-316848): 6,193 in FY2012, 0 in FY2011 and FY2010.
    ("MSFT", "goodwill_impairment", "FY2012", usd(6_193)),
    ("MSFT", "goodwill_impairment", "FY2011", Decimal(0)),
    ("MSFT", "goodwill_impairment", "FY2020", None),  # none reported
    ("AAPL", "goodwill_impairment", "FY2020", None),
    ("COST", "goodwill_impairment", "FY2020", None),
    # Temporary equity: none of the three has any; the balance sheet foots without it, so the rule
    # engine infers an exact 0 (M3 S7).
    ("AAPL", "temporary_equity", "FY2020", Decimal(0)),
    ("MSFT", "temporary_equity", "FY2020", Decimal(0)),
    ("COST", "temporary_equity", "FY2020", Decimal(0)),
    # Period-end shares outstanding (balance sheet parenthetical). AAPL is split-adjusted: the
    # FY2015 10-K says 5,578,753 thousand (x4), the FY2020 10-K 16,976,763 thousand (post-split).
    ("AAPL", "shares_outstanding", "FY2015", Decimal(22_315_012_000)),
    ("AAPL", "shares_outstanding", "FY2019", Decimal(17_772_945_000)),  # 4,443,236 thousand x4
    ("AAPL", "shares_outstanding", "FY2020", Decimal(16_976_763_000)),
    ("AAPL", "shares_outstanding", "FY2025", Decimal(14_773_260_000)),
    # MSFT 10-Ks FY2020: 7,571 and 7,643 million; FY2026: 7,427 and 7,434 million
    ("MSFT", "shares_outstanding", "FY2019", Decimal(7_643_000_000)),
    ("MSFT", "shares_outstanding", "FY2020", Decimal(7_571_000_000)),
    ("MSFT", "shares_outstanding", "FY2026", Decimal(7_427_000_000)),
    # COST 10-Ks FY2015: 437,952,000 and 437,683,000; FY2020: 441,255,000; FY2026: 443,266,000
    ("COST", "shares_outstanding", "FY2014", Decimal(437_683_000)),
    ("COST", "shares_outstanding", "FY2015", Decimal(437_952_000)),
    ("COST", "shares_outstanding", "FY2020", Decimal(441_255_000)),
    ("COST", "shares_outstanding", "FY2026", Decimal(443_266_000)),
]


@pytest.mark.parametrize(("ticker", "code", "period", "expected"), M2_LINES)
def test_m2_line_mapping(ticker: str, code: str, period: str, expected: Decimal | None) -> None:
    assert mapped(ticker, code, period) == expected


def test_a_dividend_per_share_quarter_is_reported_and_q4_is_the_year_less_the_quarters() -> None:
    # AAPL FY2025: 0.25 + 0.25 + 0.26 reported, FY 1.02, so Q4 = 1.02 - 0.76 = 0.26.
    quarters = [
        mapped("AAPL", "dividends_per_share", f"FY2025Q{n}", "quarterly") for n in (1, 2, 3, 4)
    ]

    assert quarters == [Decimal("0.25"), Decimal("0.25"), Decimal("0.26"), Decimal("0.26")]
    assert sum(quarters) == mapped("AAPL", "dividends_per_share", "FY2025")  # type: ignore[arg-type]


def test_shares_outstanding_is_an_instant_so_q4_is_the_year_end_count() -> None:
    assert mapped("AAPL", "shares_outstanding", "FY2025Q4", "quarterly") == Decimal(14_773_260_000)


# --- M2 S2: Deere & Company (consolidated only) -------------------------------------------------
# DE: 10-Ks FY2013 (0001104659-13-090354), FY2016 (0001047469-16-017244), FY2017 (0001047469-17-007719),
# FY2019 (0001558370-19-011614), FY2020 (0001558370-20-014436), FY2023 (0001558370-23-019812),
# FY2025 (0001104659-25-122321), Q3 FY2025 10-Q (0001558370-25-011789). Figures in millions.
# DE has an unclassified balance sheet, files cost of sales, PP&E and long-term borrowings under `de:`
# extension tags from FY2018/FY2021 that companyfacts omits, and shows Financial Services next to
# Equipment Operations; only the consolidated column is mapped.
DEERE: list[tuple[str, str, Decimal | None]] = [
    # Revenue is the income statement's "Net sales and revenues" total (equipment net sales plus
    # finance and interest income plus other income), not the 38,917 / 31,272 equipment net sales.
    ("revenue", "FY2015", usd("28862.8")),
    ("revenue", "FY2020", usd(35_540)),
    ("revenue", "FY2025", usd(45_684)),
    # Cost of sales is a us-gaap tag until FY2017 (19,933.5), then `de:`: empty, never another tag.
    ("cost_of_revenue", "FY2015", usd("20143.2")),
    ("cost_of_revenue", "FY2017", usd("19933.5")),
    ("cost_of_revenue", "FY2020", None),  # 10-K FY2020 shows no cost of sales line at all
    (
        "cost_of_revenue",
        "FY2025",
        None,
    ),  # 28,159 is a `de:` fact; OtherCostOfOperatingRevenue (82) is a note
    # Gross profit = total revenue less cost of sales in every period: DE's GrossProfit facts are the
    # quarterly-data note's equipment-basis figures (FY2009 Q1 1,018 = net sales 4,560.5 - 3,542.5),
    # excluded in DE.yaml. FY2015: 28,862.8 - 20,143.2. From FY2018 cost of sales is a `de:` fact.
    ("gross_profit", "FY2015", usd("8719.6")),
    ("gross_profit", "FY2017", usd("9804.5")),  # 29,738.0 (restated, the FY2018 10-K) - 19,933.5
    ("gross_profit", "FY2018", None),
    ("gross_profit", "FY2025", None),
    # No operating income line on the income statement; OperatingIncomeLoss is the segment note's
    # "Total operating profit" (FY2020 4,305 against pretax income of 3,883), excluded in DE.yaml.
    ("operating_income", "FY2015", None),
    ("operating_income", "FY2020", None),
    ("operating_income", "FY2023", None),
    # FY2015 balance sheet (FY2016 10-K, dated Oct. 31, 2015; the fiscal year ends Nov. 1): the
    # complete sheet, not the FY2017 10-K's partial restated column (57,883, no total liabilities).
    ("total_assets", "FY2015", usd("57947.6")),
    ("total_liabilities", "FY2015", usd("51190.0")),
    ("total_equity", "FY2015", usd("6757.6")),
    ("inventory", "FY2015", usd("3817.0")),
    ("temporary_equity", "FY2015", Decimal(0)),  # inferred: the sheet foots without it (S7)
    # Interest expense is the consolidated income statement line, not Financial Services' own.
    ("interest_expense", "FY2015", usd("680.0")),
    ("interest_expense", "FY2020", usd(1_247)),
    ("interest_expense", "FY2025", usd(3_170)),
    # Short-term debt = short-term borrowings (DebtCurrent, includes the current maturities of
    # long-term borrowings) + short-term securitization borrowings (SecuredDebt, its own balance sheet
    # line). DebtCurrent alone would leave out 4.7-8.4 B of debt (principle 1). Before FY2020 the
    # short-term borrowings line is not a us-gaap tag, so the item is empty rather than half of it.
    ("short_term_debt", "FY2020", usd(13_264)),  # 8,582 + 4,682
    ("short_term_debt", "FY2022", usd(18_303)),  # 12,592 + 5,711
    ("short_term_debt", "FY2023", usd(24_934)),  # 17,939 + 6,995
    ("short_term_debt", "FY2024", usd(21_964)),  # 13,533 + 8,431
    ("short_term_debt", "FY2025", usd(20_392)),  # 13,796 + 6,596
    ("short_term_debt", "FY2019", None),
    # Long-term borrowings: LongTermDebtNoncurrent until FY2021, then a `de:` tag.
    ("long_term_debt", "FY2013", usd("21577.7")),
    ("long_term_debt", "FY2020", usd(32_734)),
    ("long_term_debt", "FY2022", None),
    ("long_term_debt", "FY2025", None),
    # Marketable securities: AvailableForSaleSecurities until FY2018, MarketableSecurities after.
    ("short_term_investments", "FY2013", usd("1624.8")),
    ("short_term_investments", "FY2016", usd("453.5")),
    ("short_term_investments", "FY2020", usd(641)),
    ("short_term_investments", "FY2023", usd(946)),
    ("short_term_investments", "FY2025", usd(1_411)),
    # "Trade accounts and notes receivable - net": AccountsAndNotesReceivableNet until FY2018, then
    # AccountsReceivableNet. The financing receivables and "other receivables" lines are not trade.
    ("receivables", "FY2013", usd("3758.2")),
    ("receivables", "FY2016", usd("3011.3")),
    ("receivables", "FY2020", usd(4_171)),
    ("receivables", "FY2023", usd(7_739)),
    ("receivables", "FY2025", usd(5_317)),
    ("inventory", "FY2016", usd("3340.5")),
    ("inventory", "FY2020", usd(4_999)),
    ("inventory", "FY2025", usd(7_406)),
    # Property and equipment: PropertyPlantAndEquipmentNet until FY2019, the finance-lease-inclusive
    # tag FY2018-20 (the same figure on the balance sheet), then `de:` from FY2021.
    ("ppe_net", "FY2013", usd("5466.9")),
    ("ppe_net", "FY2019", usd(5_973)),
    ("ppe_net", "FY2020", usd(5_817)),
    ("ppe_net", "FY2025", None),
    # "Common stock ... at paid-in amount" is one line (par plus paid-in capital): CommonStockValue.
    ("common_stock_apic", "FY2013", usd("3524.2")),
    ("common_stock_apic", "FY2020", usd(4_895)),
    ("common_stock_apic", "FY2025", usd(5_668)),
    # The balance sheet is unclassified: no current or noncurrent totals, so none of their breakdown.
    ("total_current_assets", "FY2020", None),
    ("total_current_liabilities", "FY2025", None),
    ("total_noncurrent_liabilities", "FY2025", None),
    ("other_current_assets", "FY2020", None),
    # "Accounts payable and accrued expenses" is one line; mapping it as accounts payable would
    # include accruals.
    ("accounts_payable", "FY2025", None),
    # Redeemable noncontrolling interest sits between liabilities and equity (temporary equity).
    ("temporary_equity", "FY2016", usd("14.0")),
    ("temporary_equity", "FY2019", usd(14)),
    ("temporary_equity", "FY2020", Decimal(0)),  # none: 62,147 + 12,944 = 75,091 (inferred 0, S7)
    ("temporary_equity", "FY2022", usd(92)),
    ("temporary_equity", "FY2023", usd(97)),
    ("temporary_equity", "FY2025", usd(51)),
    (
        "total_liabilities",
        "FY2016",
        usd("51373.7"),
    ),  # restated in the FY2017 10-K (51,436.6 originally)
    ("total_liabilities", "FY2020", usd(62_147)),
    ("total_liabilities", "FY2025", usd(79_989)),
    ("shares_outstanding", "FY2023", Decimal(281_600_000)),
    ("shares_outstanding", "FY2025", Decimal(270_400_000)),
    # tagged from FY2023 only; FY2020 is issued 536,431,204 less treasury 222,775,254 (R7)
    ("shares_outstanding", "FY2020", Decimal(313_655_950)),
    ("dividends_per_share", "FY2015", Decimal("2.40")),
    ("dividends_per_share", "FY2020", Decimal("3.04")),
    ("dividends_per_share", "FY2025", Decimal("6.48")),  # declared; paid was 6.33
    # Cash flow. "Purchases of marketable securities": 130 / 140 / 703, the default investment
    # purchase tags stop after FY2018.
    ("purchases_of_investments", "FY2018", usd(-133)),
    ("purchases_of_investments", "FY2019", usd(-140)),
    ("purchases_of_investments", "FY2020", usd(-130)),
    ("purchases_of_investments", "FY2025", usd(-703)),
    # "Proceeds from maturities and sales of marketable securities" (one line). FY2011-16 are tagged
    # ...OfAvailableForSaleSecurities (1,022.5 / 860.7 / 169.4 in the FY2016 10-K). Since FY2017 that tag
    # holds a note figure (FY2023 37 vs the line's 186), so the Marketable-securities tag must win.
    ("sales_maturities_of_investments", "FY2014", usd("1022.5")),
    ("sales_maturities_of_investments", "FY2015", usd("860.7")),
    ("sales_maturities_of_investments", "FY2016", usd("169.4")),
    ("sales_maturities_of_investments", "FY2018", usd(76)),
    ("sales_maturities_of_investments", "FY2023", usd(186)),
    ("sales_maturities_of_investments", "FY2025", usd(486)),
    # FX effect: the default tags stop in FY2011 (EffectOfExchangeRateOnCashAndCashEquivalents) and
    # restart in FY2017 (...RestrictedCash...); FY2012-16 are tagged ...ContinuingOperations.
    # 10-K FY2016: (73.6) FY2014, (187.3) FY2015, (13.0) FY2016 (FY2017 10-K: same).
    ("fx_effect", "FY2014", usd("-73.6")),
    ("fx_effect", "FY2015", usd("-187.3")),
    ("fx_effect", "FY2016", usd("-13.0")),
    ("fx_effect", "FY2020", usd(32)),
    ("fx_effect", "FY2025", usd(77)),
    ("cfo", "FY2020", usd(7_483)),
    ("cfo", "FY2025", usd(7_459)),
    ("capex", "FY2020", usd(-820)),
    ("capex", "FY2025", usd(-1_360)),
    ("acquisitions", "FY2018", usd(-5_245)),
    ("acquisitions", "FY2020", usd(-66)),
    ("dividends_paid", "FY2020", usd(-956)),
    ("dividends_paid", "FY2025", usd(-1_720)),
    # The cash flow's "Receivables related to sales" is its one operating receivables line (M3 S6
    # verified it, see DEERE_RECEIVABLES); "Accounts payable and accrued expenses" combines two
    # balance-sheet lines, so it is not the canonical payables line.
    ("change_receivables", "FY2025", usd(1_084)),
    ("change_payables", "FY2025", None),
    ("change_inventory", "FY2025", usd(-275)),
]


@pytest.mark.parametrize(("code", "period", "expected"), DEERE)
def test_deere_mapping(code: str, period: str, expected: Decimal | None) -> None:
    assert mapped("DE", code, period) == expected


DEERE_QUARTERS: list[tuple[str, str, Decimal | None]] = [
    # Q3 FY2025 10-Q (Jul. 27, 2025): short-term borrowings 14,607 + securitization 7,610,
    # marketable securities 1,407, trade receivables 6,103, redeemable NCI 84.
    ("short_term_debt", "FY2025Q3", usd(22_217)),
    ("short_term_investments", "FY2025Q3", usd(1_407)),
    ("receivables", "FY2025Q3", usd(6_103)),
    ("temporary_equity", "FY2025Q3", usd(84)),
    ("total_liabilities", "FY2025Q3", usd(82_553)),
]


@pytest.mark.parametrize(("code", "period", "expected"), DEERE_QUARTERS)
def test_deere_quarter_mapping(code: str, period: str, expected: Decimal | None) -> None:
    assert mapped("DE", code, period, "quarterly") == expected


def test_deere_short_term_debt_names_both_balance_sheet_lines() -> None:
    de = run_pipeline("DE")
    assert source_concept(de, "short_term_debt", "2025-11-02") == "DebtCurrent + SecuredDebt"
    assert source_concept(de, "short_term_debt", "2020-11-01") == "DebtCurrent + SecuredDebt"


def test_deere_fy2015_balance_sheet_balances() -> None:
    de = run_pipeline("DE")
    check = {c.period_key: c for c in de.annual["BS"].balance_check}
    assert check["FY2015"].ok
    assert check["FY2015"].difference == 0


def test_deere_has_no_total_current_assets_so_the_balance_check_adds_up_without_them() -> None:
    # 79,989 + 51 + 25,956 = 105,996: liabilities, redeemable NCI and equity make up the assets.
    de = run_pipeline("DE")
    check = {c.period_key: c for c in de.annual["BS"].balance_check}
    assert check["FY2025"].ok
    assert check["FY2025"].difference == 0
    assert check["FY2020"].ok


# --- M3 S6: verified candidates, finance leases in debt, short-term borrowings in the debt flows ---

_FY_END = {"DE": {"FY2025": "2025-11-02", "FY2024": "2024-10-27", "FY2023": "2023-10-29"}}
DEERE_RECEIVABLES: list[tuple[str, Decimal]] = [
    # Deere cash flow, "Receivables related to sales" (IncreaseDecreaseInReceivables, whose sign is
    # the opposite of the cash effect). 10-K FY2025 (accession 0001104659-25-122321): FY2025 1,084,
    # FY2024 421, FY2023 (4,253); read from the filing's R6 page on sec.gov.
    ("FY2025", usd(1_084)),
    ("FY2024", usd(421)),
    ("FY2023", usd(-4_253)),
]


@pytest.mark.parametrize(("period", "expected"), DEERE_RECEIVABLES)
def test_deere_change_in_receivables_is_the_receivables_related_to_sales_line(
    period: str, expected: Decimal
) -> None:
    assert mapped("DE", "change_receivables", period) == expected
    assert source_concept(run_pipeline("DE"), "change_receivables", _FY_END["DE"][period]) == (
        "IncreaseDecreaseInReceivables"
    )


def test_the_receivables_fallback_ranks_after_accounts_receivable() -> None:
    # Apple's, Microsoft's and Costco's cash flows are untouched (the baseline guard checks every
    # cell); the fallback only fills a period the first concept leaves empty.
    items = {i.code: i for i in run_pipeline("DE").items}
    assert items["change_receivables"].concepts == (
        "us-gaap:IncreaseDecreaseInAccountsReceivable",
        "us-gaap:IncreaseDecreaseInReceivables",
    )
    assert mapped("AAPL", "change_receivables", "FY2020") == usd(6_917)
    assert mapped("COST", "change_receivables", "FY2020") is None


COSTCO_DEBT_FLOWS: list[tuple[str, str, Decimal]] = [
    # Costco cash flow, 10-K FY2025 (accession 0000909832-25-000101, R8 page): short-term borrowings
    # are separate lines next to the long-term ones, and both count (user decision 2026-10-25).
    # FY2025: proceeds 816 + 0, repayments (862) + (103); FY2024: 928 + 498, (920) + (1,077);
    # FY2023: 917 + 0, (935) + (75).
    ("debt_issued", "FY2025", usd(816)),
    ("debt_issued", "FY2024", usd(1_426)),
    ("debt_issued", "FY2023", usd(917)),
    ("debt_repaid", "FY2025", usd(-965)),
    ("debt_repaid", "FY2024", usd(-1_997)),
    ("debt_repaid", "FY2023", usd(-1_010)),
]


@pytest.mark.parametrize(("code", "period", "expected"), COSTCO_DEBT_FLOWS)
def test_costco_debt_flows_include_the_short_term_borrowings(
    code: str, period: str, expected: Decimal
) -> None:
    assert mapped("COST", code, period) == expected


def test_a_debt_flow_names_the_long_term_anchor_and_the_short_term_member() -> None:
    cost = run_pipeline("COST")
    assert source_concept(cost, "debt_issued", "2025-08-31") == (
        "ProceedsFromIssuanceOfLongTermDebt + ProceedsFromShortTermDebt"
    )
    assert source_concept(cost, "debt_repaid", "2025-08-31") == (
        "RepaymentsOfLongTermDebt + RepaymentsOfShortTermDebt"
    )


def test_a_year_without_short_term_flows_keeps_the_long_term_figure_alone() -> None:
    # Costco FY2020 (3,992 and (3,200) in the 10-K): no short-term proceeds or repayments facts.
    assert mapped("COST", "debt_issued", "FY2020") == usd(3_992)
    assert mapped("COST", "debt_repaid", "FY2020") == usd(-3_200)


def test_a_net_short_term_flow_stays_in_other_financing() -> None:
    # Apple's commercial paper is one net line (ProceedsFromRepaymentsOfCommercialPaper): it is
    # not split by sign, so no net concept feeds debt_issued or debt_repaid.
    aapl = run_pipeline("AAPL")
    flows = aapl.mappings[aapl.mappings["canonical_code"].isin(["debt_issued", "debt_repaid"])]
    assert not [c for c in flows["concept"] if c.startswith("ProceedsFromRepayments")]
    frame = aapl.canonical
    assert "ProceedsFromRepaymentsOfCommercialPaper" not in set(frame["concept"])


FINANCE_LEASES_IN_DEBT: list[tuple[str, str, str, Decimal]] = [
    # Finance leases count as debt (user decision 2026-10-25); each company's 10-K shows where the
    # lease liability sat, and the figures below are the debt line plus that liability.
    #
    # AAPL: the lease note puts the liabilities in "Other current liabilities" and "Other non-current
    # liabilities", outside the term-debt lines. 10-K FY2025 (R56): current 538 / 144, non-current
    # 692 / 752 for FY2025 / FY2024; 10-K FY2023 (R60): 165 / 129 and 859 / 812 for FY2023 / FY2022.
    # Short-term: commercial paper + current term debt + current lease, e.g. FY2025 7,979 + 12,350 + 538.
    ("AAPL", "short_term_debt", "FY2025", usd(20_867)),
    ("AAPL", "short_term_debt", "FY2024", usd(21_023)),
    ("AAPL", "short_term_debt", "FY2023", usd(15_972)),  # 15,807 + 165
    ("AAPL", "short_term_debt", "FY2022", usd(21_239)),  # 21,110 + 129
    ("AAPL", "long_term_debt", "FY2025", usd(79_020)),  # 78,328 + 692
    ("AAPL", "long_term_debt", "FY2024", usd(86_502)),  # 85,750 + 752
    ("AAPL", "long_term_debt", "FY2023", usd(96_140)),  # 95,281 + 859
    ("AAPL", "long_term_debt", "FY2022", usd(99_771)),  # 98,959 + 812
    ("AAPL", "total_debt", "FY2025", usd(99_887)),
    # Before FY2020 Apple tags no finance lease liability: the lines are the debt alone.
    ("AAPL", "short_term_debt", "FY2019", usd(16_240)),
    ("AAPL", "long_term_debt", "FY2019", usd(91_807)),
    # MSFT: one total (FinanceLeaseLiability), half current and mostly long-term, all in "Other
    # current liabilities" and "Other long-term liabilities". Companyfacts has no split, so the
    # whole liability joins long-term debt. 10-Ks: FY2025 46,172 (R90), FY2024 27,145, FY2020
    # 9,496 (R95), FY2019 6,574, FY2018 4,301 and FY2017 2,538 (R103).
    ("MSFT", "long_term_debt", "FY2025", usd(86_324)),  # 40,152 + 46,172
    ("MSFT", "long_term_debt", "FY2024", usd(69_833)),  # 42,688 + 27,145
    ("MSFT", "long_term_debt", "FY2020", usd(69_074)),  # 59,578 + 9,496
    ("MSFT", "long_term_debt", "FY2019", usd(73_236)),  # 66,662 + 6,574
    ("MSFT", "long_term_debt", "FY2018", usd(76_543)),  # 72,242 + 4,301
    ("MSFT", "long_term_debt", "FY2017", usd(78_611)),  # 76,073 + 2,538
    ("MSFT", "total_debt", "FY2025", usd(89_323)),  # 2,999 + 86,324
    # MSFT before FY2017 has no finance lease liability tag.
    ("MSFT", "long_term_debt", "FY2016", usd(40_557)),
    # COST: current leases in "Other current liabilities", long-term in "Other long-term
    # liabilities". 10-K FY2025 (R52): 78 / 1,401, FY2024: 147 / 1,351; 10-K FY2018 (R43, capital
    # leases): 7 / 390.
    ("COST", "short_term_debt", "FY2025", usd(153)),  # 75 + 78
    ("COST", "short_term_debt", "FY2024", usd(250)),  # 103 + 147
    ("COST", "short_term_debt", "FY2018", usd(97)),  # 90 + 7
    ("COST", "long_term_debt", "FY2025", usd(7_114)),  # 5,713 + 1,401
    ("COST", "long_term_debt", "FY2024", usd(7_145)),  # 5,794 + 1,351
    ("COST", "long_term_debt", "FY2018", usd(6_877)),  # 6,487 + 390
    # COST FY2021-FY2023: companyfacts carries no lease liability, so those years are the debt alone.
    ("COST", "short_term_debt", "FY2021", usd(799)),
    ("COST", "long_term_debt", "FY2021", usd(6_692)),
    # DE: the lease note says the finance leases are inside "Short-term borrowings" and "Long-term
    # borrowings" (10-K FY2025 R147: 39 / 73, FY2024 33 / 72; R24 lists them in the short-term
    # table), so adding them again would count them twice: Deere's lines are unchanged.
    ("DE", "short_term_debt", "FY2025", usd(20_392)),
    ("DE", "short_term_debt", "FY2020", usd(13_264)),
    ("DE", "long_term_debt", "FY2020", usd(32_734)),
    ("DE", "long_term_debt", "FY2021", usd(32_888)),
]


@pytest.mark.parametrize(("ticker", "code", "period", "expected"), FINANCE_LEASES_IN_DEBT)
def test_finance_leases_are_in_debt_where_the_10k_shows_them_outside_it(
    ticker: str, code: str, period: str, expected: Decimal
) -> None:
    assert mapped(ticker, code, period) == expected


def test_the_lease_leaves_the_residual_it_sat_in_so_the_subtotals_still_foot() -> None:
    # Apple FY2025: other non-current liabilities 30,638 before, less the 692 now in long-term debt.
    assert mapped("AAPL", "other_noncurrent_liabilities", "FY2025") == usd(29_946)
    assert mapped("AAPL", "other_current_liabilities", "FY2025") == usd(65_849)  # 66,387 - 538
    for ticker in ("AAPL", "MSFT", "COST"):
        annual = run_pipeline(ticker).annual["BS"]
        keys = [p.key for p in annual.periods]
        rows = {r.code: r.values for r in annual.rows}
        for key in ("FY2024", "FY2025"):
            i = keys.index(key)
            for total, parts in (
                (
                    "total_noncurrent_liabilities",
                    ("long_term_debt", "operating_lease_liabilities_noncurrent"),
                ),
            ):
                assert rows[total][i] is not None
                rest = rows["other_noncurrent_liabilities"][i]
                assert rest is not None and rest > 0
                known = sum((rows[p][i] or Decimal(0) for p in parts), Decimal(0))
                assert known + rest == rows[total][i]


def test_net_debt_follows_the_debt_lines() -> None:
    # Microsoft FY2025: debt 89,323 less cash and short-term investments.
    msft = run_pipeline("MSFT").annual["BS"]
    rows = {r.code: r.values for r in msft.rows}
    i = [p.key for p in msft.periods].index("FY2025")
    assert rows["net_debt"][i] == (
        rows["total_debt"][i] - rows["cash"][i] - (rows["short_term_investments"][i] or 0)
    )


def test_a_lease_member_names_its_source_and_a_pre_842_lease_is_never_added_twice() -> None:
    cost, aapl, msft = run_pipeline("COST"), run_pipeline("AAPL"), run_pipeline("MSFT")
    assert source_concept(cost, "long_term_debt", "2025-08-31") == (
        "LongTermDebtNoncurrent + FinanceLeaseLiabilityNoncurrent"
    )
    assert source_concept(cost, "long_term_debt", "2018-09-02") == (
        "LongTermDebtNoncurrent + CapitalLeaseObligationsNoncurrent"
    )
    assert source_concept(aapl, "short_term_debt", "2025-09-27") == (
        "CommercialPaper + LongTermDebtCurrent + FinanceLeaseLiabilityCurrent"
    )
    assert source_concept(msft, "long_term_debt", "2025-06-30") == (
        "LongTermDebtNoncurrent + FinanceLeaseLiability"
    )
    # The two lease tags of one liability never both feed one cell: the ASC 842 switch is a clean cut.
    for ticker in ("AAPL", "MSFT", "COST", "DE"):
        frame = run_pipeline(ticker).canonical
        debt = frame[frame["code"].isin(["short_term_debt", "long_term_debt"])]
        both = [c for c in debt["concept"] if ("CapitalLease" in c and "FinanceLease" in c)]
        assert both == []


def test_deere_has_no_lease_member_in_its_debt_lines() -> None:
    de = run_pipeline("DE")
    frame = de.canonical
    debt = frame[frame["code"].isin(["short_term_debt", "long_term_debt"])]
    assert not [c for c in debt["concept"] if "Lease" in c]
