import type {
  CapitalAllocationOut,
  FlagsOut,
  OffBalanceItemOut,
  PeriodOut,
  QoeCustomRuleOut,
  QoeRuleOut,
  RatiosOut,
} from "@/api/generated/types.gen";

// Shapes of GET …/ratios, …/flags, …/capital-allocation, …/off-balance-items and /qoe-rules.

export function annualPeriods(): PeriodOut[] {
  return [
    {
      key: "FY2023",
      label: "FY2023",
      fiscal_year: 2023,
      fiscal_period: "FY",
      period_start: "2022-10-01",
      period_end: "2023-09-30",
      is_forecast: false,
    },
    {
      key: "FY2024",
      label: "FY2024",
      fiscal_year: 2024,
      fiscal_period: "FY",
      period_start: "2023-10-01",
      period_end: "2024-09-28",
      is_forecast: false,
    },
  ];
}

const DE_LEVERAGE_CAVEAT =
  "Consolidated figures include John Deere Financial. Its debt, interest expense and financing " +
  "receivables fund customer purchases, so leverage, coverage and asset-based ratios are not " +
  "comparable with an industrial company.";
const DE_REVENUE_CAVEAT =
  "Deere's revenue is net sales and revenues, which include John Deere Financial's finance and " +
  "interest income, so gross margin and days sales outstanding are not comparable with an " +
  "equipment maker's.";

// One row of each unit, two categories with caveats (DE-like) and one row without a value.
export function ratios(overrides: Partial<RatiosOut> = {}): RatiosOut {
  return {
    ticker: "DE",
    freq: "annual",
    basis: "reported",
    periods: annualPeriods(),
    rows: [
      {
        code: "gross_margin",
        label: "Gross margin",
        category: "Profitability",
        unit: "pct",
        definition: "gross_profit ÷ revenue",
        caveat: DE_REVENUE_CAVEAT,
        values: ["0.441311", "0.462063"],
      },
      {
        code: "roe",
        label: "Return on equity",
        category: "Profitability",
        unit: "pct",
        definition: "net_income_common ÷ avg(equity_parent)",
        caveat: null,
        values: ["-0.034", "1.645935"],
      },
      {
        code: "debt_to_equity",
        label: "Debt / equity",
        category: "Solvency",
        unit: "x",
        definition: "total_debt ÷ total_equity",
        caveat: DE_LEVERAGE_CAVEAT,
        values: ["2.8401", "2.4512"],
      },
      {
        code: "interest_coverage",
        label: "Interest coverage",
        category: "Solvency",
        unit: "x",
        definition: "operating_income ÷ interest_expense",
        caveat: DE_LEVERAGE_CAVEAT,
        values: [null, null],
      },
      {
        code: "dso",
        label: "Days sales outstanding",
        category: "Efficiency",
        unit: "days",
        definition: "avg(receivables) ÷ revenue × 365",
        caveat: DE_REVENUE_CAVEAT,
        values: ["61.234", "58.7"],
      },
      {
        code: "eps_diluted",
        label: "EPS (diluted)",
        category: "Per share",
        unit: "USD/shares",
        definition: "annual: the IS eps_diluted line; TTM: net_income_common ÷ shares_diluted",
        caveat: null,
        values: ["34.63", "25.62"],
      },
    ],
    ...overrides,
  };
}

// One rule of each direction and unit, with every severity and a null value.
export function flags(overrides: Partial<FlagsOut> = {}): FlagsOut {
  return {
    ticker: "AAPL",
    freq: "annual",
    periods: annualPeriods(),
    rules: [
      {
        code: "accruals_ratio",
        label: "Accruals ratio",
        rule: "(net_income − cfo) ÷ avg(total_assets)",
        direction: "above",
        unit: "pct",
        warn: "0.05",
        alert: "0.1",
        values: ["0.062", "0.15"],
        severity: ["warn", "alert"],
        custom: false,
        warn_formula: null,
        alert_formula: null,
        warn_levels: ["0.05", "0.05"],
        alert_levels: ["0.1", "0.1"],
        error: null,
      },
      {
        code: "cfo_to_net_income",
        label: "CFO / net income",
        rule: "cfo ÷ net_income; null when net_income ≤ 0",
        direction: "below",
        unit: "x",
        warn: "0.8",
        alert: "0",
        values: ["1.2", null],
        severity: ["none", null],
        custom: false,
        warn_formula: null,
        alert_formula: null,
        warn_levels: ["0.8", null],
        alert_levels: ["0", null],
        error: null,
      },
      {
        code: "goodwill_impairment",
        label: "Goodwill impairment",
        rule: "goodwill_impairment ÷ goodwill at the previous period end",
        direction: "above",
        unit: "pct",
        warn: "0",
        alert: null,
        values: ["0", "0"],
        severity: ["none", "none"],
        custom: false,
        warn_formula: null,
        alert_formula: null,
        warn_levels: ["0", "0"],
        alert_levels: [null, null],
        error: null,
      },
    ],
    off_balance_items: offBalanceItems(),
    ...overrides,
  };
}

export function offBalanceItem(overrides: Partial<OffBalanceItemOut> = {}): OffBalanceItemOut {
  return {
    id: 3,
    kind: "purchase_commitment",
    description: "Unconditional purchase obligations",
    amount: "12500000000",
    as_of: "2024-09-28",
    source_note: "10-K Note 12",
    created_at: "2026-10-12T09:30:00",
    updated_at: "2026-10-12T09:30:00",
    ...overrides,
  };
}

// Newest `as_of` first, as the API orders them; the second has no amount and no source note.
export function offBalanceItems(): OffBalanceItemOut[] {
  return [
    offBalanceItem(),
    offBalanceItem({
      id: 2,
      kind: "guarantee",
      description: "Guarantees of supplier debt",
      amount: null,
      as_of: "2023-09-30",
      source_note: null,
    }),
  ];
}

// Every row of the table, in order; outflows negative.
export function capitalAllocation(
  overrides: Partial<CapitalAllocationOut> = {},
): CapitalAllocationOut {
  return {
    ticker: "AAPL",
    freq: "annual",
    periods: annualPeriods(),
    rows: [
      {
        code: "cfo",
        label: "Cash from operations",
        unit: "USD",
        values: ["110543000000", "118254000000"],
        pct_of_cfo: null,
        pct_of_fcf: null,
      },
      {
        code: "free_cash_flow",
        label: "Free cash flow",
        unit: "USD",
        values: ["99584000000", "108807000000"],
        pct_of_cfo: null,
        pct_of_fcf: null,
      },
      {
        code: "capex",
        label: "Capital expenditures",
        unit: "USD",
        values: ["-10959000000", "-9447000000"],
        pct_of_cfo: ["0.099138", "0.079887"],
        pct_of_fcf: ["0.110048", "0.086824"],
      },
      {
        code: "d_and_a",
        label: "Depreciation & amortization",
        unit: "USD",
        values: ["11519000000", "11445000000"],
        pct_of_cfo: null,
        pct_of_fcf: null,
      },
      {
        code: "capex_to_da",
        label: "Capex / D&A",
        unit: "x",
        values: ["0.951385", "0.825426"],
        pct_of_cfo: null,
        pct_of_fcf: null,
      },
      {
        code: "acquisitions",
        label: "Acquisitions",
        unit: "USD",
        values: [null, null],
        pct_of_cfo: [null, null],
        pct_of_fcf: [null, null],
      },
      {
        code: "buybacks",
        label: "Buybacks",
        unit: "USD",
        values: ["-77550000000", "-94949000000"],
        pct_of_cfo: ["0.701537", "0.802924"],
        pct_of_fcf: ["0.778739", "0.872637"],
      },
      {
        code: "dividends_paid",
        label: "Dividends",
        unit: "USD",
        values: ["-15025000000", "-15234000000"],
        pct_of_cfo: ["0.135920", "0.128824"],
        pct_of_fcf: ["0.150877", "0.140009"],
      },
      {
        code: "shareholder_returns",
        label: "Buybacks + dividends",
        unit: "USD",
        values: ["-92575000000", "-110183000000"],
        pct_of_cfo: ["0.837457", "0.931748"],
        pct_of_fcf: ["0.929617", "1.012646"],
      },
      {
        code: "net_share_change",
        label: "Net share-count change",
        unit: "pct",
        values: ["-0.024", "-0.0264"],
        pct_of_cfo: null,
        pct_of_fcf: null,
      },
    ],
    ...overrides,
  };
}

export function qoeRule(overrides: Partial<QoeRuleOut> = {}): QoeRuleOut {
  return {
    code: "accruals_ratio",
    label: "Accruals ratio",
    rule: "(net_income − cfo) ÷ avg(total_assets)",
    direction: "above",
    unit: "pct",
    warn: "0.05",
    alert: "0.1",
    default_warn: "0.05",
    default_alert: "0.1",
    overridden: false,
    custom: false,
    formula: null,
    warn_formula: null,
    alert_formula: null,
    error: null,
    ...overrides,
  };
}

// A pct rule at its defaults, an overridden one, and an x rule.
export function qoeRules(): QoeRuleOut[] {
  return [
    qoeRule(),
    qoeRule({
      code: "sbc_to_revenue",
      label: "SBC / revenue",
      rule: "sbc ÷ revenue",
      warn: "0.01",
      alert: "0.02",
      default_warn: "0.05",
      default_alert: "0.1",
      overridden: true,
    }),
    qoeRule({
      code: "cfo_to_net_income",
      label: "CFO / net income",
      rule: "cfo ÷ net_income; null when net_income ≤ 0",
      direction: "below",
      unit: "x",
      warn: "0.8",
      alert: "0",
      default_warn: "0.8",
      default_alert: "0",
    }),
  ];
}

export function qoeCustomRule(overrides: Partial<QoeCustomRuleOut> = {}): QoeCustomRuleOut {
  return {
    id: 1,
    code: "custom_1",
    label: "Accruals (mine)",
    formula: "(net_income - cfo) / avg(total_assets)",
    direction: "above",
    unit: "pct",
    warn: "0.05",
    alert: "0.1",
    warn_formula: null,
    alert_formula: null,
    error: null,
    created_at: "2026-10-17T10:00:00Z",
    updated_at: "2026-10-17T10:00:00Z",
    ...overrides,
  };
}
