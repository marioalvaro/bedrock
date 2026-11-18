// Earnings-review payloads as the API returns them: decimals as strings, timestamps naive UTC.
import type {
  EarningsReviewOut,
  FlagChangeOut,
  RangeOut,
  RestatedOut,
  ReviewDriverOut,
  ReviewLineOut,
} from "@/api/generated/types.gen";

import { checkpointOut } from "./checkpoints";

export function rangeOut(overrides: Partial<RangeOut> = {}): RangeOut {
  return {
    low: "410000000000",
    high: "420000000000",
    actual: "416161000000",
    basis: "reported",
    given_on: "2025-10-30",
    surprise: null,
    verdict: "in_range",
    ...overrides,
  };
}

export function reviewLine(overrides: Partial<ReviewLineOut> = {}): ReviewLineOut {
  return {
    code: "revenue",
    label: "Revenue",
    unit: "USD",
    actual: "416161000000",
    prior_year: "391035000000",
    yoy: "0.0643",
    forecast: "425000000000",
    low: "400000000000",
    high: "440000000000",
    pct_error: "0.0212",
    in_range: true,
    consensus: rangeOut({ low: "415000000000", high: "418000000000" }),
    guidance: rangeOut({ verdict: "beat" }),
    ...overrides,
  };
}

export function reviewDriver(overrides: Partial<ReviewDriverOut> = {}): ReviewDriverOut {
  return {
    code: "gross_margin",
    label: "Gross margin",
    unit: "pct",
    forecast: "0.4600",
    actual: "0.4690",
    pct_error: "-0.0192",
    in_range: true,
    source: "manual",
    ...overrides,
  };
}

export function restatedRow(overrides: Partial<RestatedOut> = {}): RestatedOut {
  return {
    statement: "IS",
    code: "revenue",
    label: "Revenue",
    fiscal_year: 2025,
    fiscal_period: "FY",
    unit: "USD",
    before: "391035000000",
    after: "391500000000",
    pct_change: "0.0012",
    ...overrides,
  };
}

export function flagChange(overrides: Partial<FlagChangeOut> = {}): FlagChangeOut {
  return {
    code: "accruals_ratio",
    label: "Accruals ratio",
    unit: "pct",
    before: "none",
    after: "warn",
    value_before: "0.0400",
    value_after: "0.0810",
    ...overrides,
  };
}

export function earningsReview(overrides: Partial<EarningsReviewOut> = {}): EarningsReviewOut {
  return {
    ticker: "AAPL",
    filing: {
      form: "10-K",
      accession_no: "0000320193-26-000105",
      filed_at: "2026-10-31",
      period_end: "2026-09-26",
    },
    period: { fiscal_year: 2026, fiscal_period: "FY", label: "FY26" },
    snapshot: {
      id: 7,
      scenario_name: "Main",
      created_at: "2026-10-31T06:00:00",
      data_as_of: "2026-08-01",
      origin: "auto",
      classification_mode: "off",
    },
    lines: [reviewLine()],
    drivers: [reviewDriver()],
    drivers_note: null,
    restated: [restatedRow()],
    restated_total: 1,
    flags: [flagChange()],
    checkpoints: [checkpointOut({ changed: true, previous_state: "holding", state: "broken" })],
    ...overrides,
  };
}

/** The review of a company with no 10-K or 10-Q loaded. */
export function emptyReview(): EarningsReviewOut {
  return earningsReview({
    filing: null,
    period: null,
    snapshot: null,
    lines: [],
    drivers: [],
    restated: [],
    restated_total: 0,
    flags: [],
    checkpoints: [],
  });
}
