import type { CompanyListItem, MappingGapsOut } from "@/api/generated/types.gen";

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

export function mappingGaps(): MappingGapsOut {
  return {
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
        concept: "IncreaseDecreaseInOtherOperatingCapitalNet",
        unit: "USD",
        latest_value: "-1200000000",
        latest_period_end: "2025-09-27",
        facts: 3,
      },
    ],
  };
}
