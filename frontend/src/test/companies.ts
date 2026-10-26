import type { CompanyListItem, CoverageOut, MappingGapsOut } from "@/api/generated/types.gen";

export function companyItem(overrides: Partial<CompanyListItem> = {}): CompanyListItem {
  return {
    id: 1,
    ticker: "AAPL",
    cik: "0000320193",
    name: "Apple Inc.",
    fiscal_year_end_month: 9,
    currency: "USD",
    sic: "3571",
    last_refreshed_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    price: "231.40",
    price_date: "2026-10-07",
    market_cap: "3500000000000.00",
    pe: "34.21",
    ev_ebitda: null,
    revenue_growth: "0.0512",
    ...overrides,
  };
}

function coverageRow(overrides: Partial<CoverageOut> = {}): CoverageOut {
  return {
    statement: "IS",
    freq: "annual",
    cells: 100,
    filled: 95,
    fraction: "0.950000",
    by_provenance: { reported: 80, derived: 10, zero_inferred: 3, approximated: 2 },
    empty_by_cause: { no_filing_data: 0, structural: 1, rule_rejected: 1, not_reported: 3 },
    ...overrides,
  };
}

export function mappingGaps(): MappingGapsOut {
  return {
    coverage: [
      coverageRow(),
      coverageRow({
        freq: "quarterly",
        cells: 400,
        filled: 340,
        fraction: "0.887500",
        by_provenance: { reported: 200, derived: 120, zero_inferred: 12, approximated: 8 },
        empty_by_cause: { no_filing_data: 17, structural: 4, rule_rejected: 0, not_reported: 39 },
      }),
      coverageRow({
        statement: "BS",
        cells: 200,
        filled: 150,
        fraction: "0.750000",
        by_provenance: { reported: 120, derived: 20, zero_inferred: 10, approximated: 0 },
        empty_by_cause: { no_filing_data: 0, structural: 0, rule_rejected: 0, not_reported: 50 },
      }),
    ],
    rule_warnings: [
      {
        rule: "cash_rollforward",
        code: "fx_effect",
        label: "FX effect on cash",
        period_key: "FY2020",
        value: "-1250000000",
        unit: "USD",
        reason: "exceeds 5% of the largest other term",
      },
      {
        rule: "q4_eps",
        code: "eps_diluted",
        label: "Diluted EPS",
        period_key: "FY2023Q4",
        value: "2.51",
        unit: "USD/shares",
        reason: "differs from FY - Q1 - Q2 - Q3",
      },
      {
        rule: "equity_split",
        code: "nci",
        label: "Non-controlling interest",
        period_key: "FY2019",
        value: null,
        unit: "USD",
        reason: "operands come from different filings",
      },
    ],
    missing_items: [
      {
        code: "short_term_debt",
        label: "Short-term debt",
        statement: "BS",
        missing_periods: ["FY2008", "FY2009", "FY2010"],
      },
    ],
    unmapped_concepts: [
      {
        taxonomy: "us-gaap",
        concept: "LongTermDebtCurrent",
        unit: "USD",
        latest_value: "12350000000",
        latest_period_end: "2025-09-27",
        facts: 2,
        suggested_codes: ["short_term_debt", "long_term_debt"],
        classification: null,
      },
      {
        taxonomy: "us-gaap",
        concept: "IncreaseDecreaseInOtherOperatingCapitalNet",
        unit: "USD",
        latest_value: "-1200000000",
        latest_period_end: "2025-09-27",
        facts: 3,
        suggested_codes: [],
        classification: null,
      },
      {
        taxonomy: "us-gaap",
        concept: "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
        unit: "USD",
        latest_value: "10078000000",
        latest_period_end: "2025-09-27",
        facts: 1,
        suggested_codes: ["long_term_debt"],
        classification: { type: "disclosure", reason: "debt maturity schedule", codes: [] },
      },
      {
        taxonomy: "us-gaap",
        concept: "Land",
        unit: "USD",
        latest_value: "10546000000",
        latest_period_end: "2025-09-27",
        facts: 1,
        suggested_codes: ["ppe_net"],
        classification: {
          type: "component",
          reason: "gross property component of the PP&E note",
          codes: ["ppe_net"],
        },
      },
    ],
  };
}
