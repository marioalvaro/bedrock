import type {
  AdjustmentOut,
  CellAdjustmentOut,
  CorporateActionOut,
} from "@/api/generated/types.gen";

// Shapes of GET …/adjustments, the cell detail's `adjustments` and GET …/corporate-actions.

export function adjustment(overrides: Partial<AdjustmentOut> = {}): AdjustmentOut {
  return {
    id: 7,
    canonical_code: "sga",
    label: "SG&A",
    fiscal_year: 2024,
    fiscal_period: "FY",
    amount: "-25000000",
    category: "one-off",
    reason: "Legal settlement",
    created_at: "2026-10-12T09:30:00",
    updated_at: "2026-10-12T09:30:00",
    ...overrides,
  };
}

export function cellAdjustment(overrides: Partial<CellAdjustmentOut> = {}): CellAdjustmentOut {
  return { ...adjustment(), via: null, ...overrides };
}

// AAPL's 7-for-1 (2014) and 4-for-1 (2020) splits, plus a made-up 1-for-10 reverse split.
export function corporateActions(): CorporateActionOut[] {
  return [
    { type: "split", effective_date: "2014-06-09", ratio: "7", source: "yfinance" },
    { type: "split", effective_date: "2020-08-31", ratio: "4", source: "yfinance" },
    { type: "reverse_split", effective_date: "2023-05-01", ratio: "0.1", source: "yfinance" },
  ];
}
