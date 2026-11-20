// Thesis-checkpoint payloads as the API returns them: decimals as strings, timestamps naive UTC.
import type { CheckpointListOut, CheckpointOut } from "@/api/generated/types.gen";

export function checkpointOut(overrides: Partial<CheckpointOut> = {}): CheckpointOut {
  return {
    id: 1,
    label: "Gross margin holds",
    statement: "gross_margin > 44%",
    freq: "ttm",
    margin: null,
    state: "holding",
    previous_state: "holding",
    changed: false,
    at_risk_by: null,
    period: { fiscal_year: 2026, fiscal_period: "Q3", label: "Q3 FY26 TTM" },
    left: "0.4520",
    right: "0.4400",
    gap: "0.0120",
    unit: "pct",
    error: null,
    created_at: "2026-11-18T10:00:00",
    updated_at: "2026-11-18T10:00:00",
    ...overrides,
  };
}

export function checkpointList(overrides: Partial<CheckpointListOut> = {}): CheckpointListOut {
  return {
    report: { form: "10-Q", filed_at: "2026-08-01" },
    checkpoints: [checkpointOut()],
    ...overrides,
  };
}
