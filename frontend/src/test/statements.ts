import type { StatementOut } from "@/api/generated/types.gen";

// A realistic annual income statement payload (shape of GET …/statements), AAPL-like.
export function incomeStatement(overrides: Partial<StatementOut> = {}): StatementOut {
  return {
    ticker: "AAPL",
    statement: "IS",
    freq: "annual",
    basis: "reported",
    currency: "USD",
    balance_check: null,
    periods: [
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
    ],
    rows: [
      {
        code: "revenue",
        label: "Revenue",
        unit: "USD",
        kind: "flow",
        depth: 0,
        values: ["383285000000", "391035000000"],
        provenance: ["reported", "derived"],
        yoy: [null, "0.020219"],
        common_size: ["1.000000", "1.000000"],
      },
      {
        code: "cost_of_revenue",
        label: "Cost of revenue",
        unit: "USD",
        kind: "flow",
        depth: 1,
        values: ["214137000000", "210352000000"],
        provenance: ["reported", "reported"],
        yoy: [null, "-0.017674"],
        common_size: ["0.558700", "0.537900"],
      },
      {
        code: "rnd",
        label: "Research and development",
        unit: "USD",
        kind: "flow",
        depth: 1,
        values: [null, null],
        provenance: [null, null],
        yoy: [null, null],
        common_size: [null, null],
      },
      {
        code: "eps_diluted",
        label: "EPS, diluted",
        unit: "USD/shares",
        kind: "average",
        depth: 0,
        values: ["6.13", "6.08"],
        provenance: ["reported", "reported"],
        yoy: [null, "-0.008157"],
        common_size: [null, null],
      },
    ],
    ...overrides,
  };
}

export function balanceStatement(): StatementOut {
  const base = incomeStatement();
  return {
    ...base,
    statement: "BS",
    rows: [
      {
        code: "total_assets",
        label: "Total assets",
        unit: "USD",
        kind: "instant",
        depth: 0,
        values: ["352583000000", "364980000000"],
        provenance: ["reported", "reported"],
        yoy: [null, "0.035"],
        common_size: ["1.000000", "1.000000"],
      },
    ],
    balance_check: [
      { period_key: "FY2023", difference: "0", ok: true },
      { period_key: "FY2024", difference: "-2000000", ok: false },
    ],
  };
}
