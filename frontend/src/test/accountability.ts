// Accountability payloads as the API returns them: decimals as strings, timestamps naive UTC
// (the backend stores and serializes them without an offset).
import type {
  AuditPageOut,
  AuditRowOut,
  BacktestOut,
  ScoreRowOut,
  SnapshotCaseOut,
  SnapshotDetailOut,
  SnapshotLineCellOut,
  SnapshotListOut,
  SnapshotOut,
} from "@/api/generated/types.gen";

export function scoreRow(overrides: Partial<ScoreRowOut> = {}): ScoreRowOut {
  return {
    kind: "line",
    code: "revenue",
    label: "Revenue",
    unit: "USD",
    method: "auto",
    freq: "annual",
    horizon: 1,
    n: 10,
    mape: "0.0512",
    bias: "0.0213",
    hit_rate: null,
    n_range: 0,
    ...overrides,
  };
}

// Revenue (annual horizons 1 and 2, Auto and ARIMA; one quarterly row) and a driver with a band.
export function backtestSummary(): ScoreRowOut[] {
  return [
    scoreRow({ method: "arima", horizon: 1, mape: "0.0700", bias: "-0.0300", n: 9 }),
    scoreRow({ method: "auto", horizon: 1 }),
    scoreRow({ method: "auto", horizon: 2, mape: "0.1250", bias: "0.0800", n: 8 }),
    scoreRow({ method: "auto", freq: "quarterly", horizon: 1, mape: "0.0400", n: 30 }),
    scoreRow({
      kind: "driver",
      code: "gross_margin",
      label: "Gross margin",
      unit: "pct",
      method: "auto",
      mape: "0.0200",
      bias: "-0.0100",
      hit_rate: "0.8000",
      n_range: 10,
    }),
  ];
}

export function backtest(overrides: Partial<BacktestOut> = {}): BacktestOut {
  return {
    ran_at: "2026-11-10T12:00:00",
    stale: false,
    origins: [
      {
        as_of_date: "2023-11-03",
        runs: [
          { method: "auto", error: null },
          { method: "arima", error: null },
        ],
      },
      {
        as_of_date: "2024-11-01",
        runs: [
          { method: "auto", error: null },
          { method: "arima", error: "Set these drivers: gross_margin" },
        ],
      },
    ],
    summary: backtestSummary(),
    ...overrides,
  };
}

export const noBacktest = (): BacktestOut => ({
  ran_at: null,
  stale: false,
  origins: [],
  summary: [],
});

export function snapshotOut(overrides: Partial<SnapshotOut> = {}): SnapshotOut {
  return {
    id: 7,
    scenario_id: 1,
    scenario_name: "Main",
    note: "Before the print",
    created_at: "2026-11-09T15:30:00",
    data_as_of: "2025-10-31",
    failed_cases: [],
    scored_periods: 1,
    classification_mode: "off",
    revenue_mape: "0.0312",
    ...overrides,
  };
}

export function snapshotList(overrides: Partial<SnapshotListOut> = {}): SnapshotListOut {
  return {
    snapshots: [snapshotOut(), snapshotOut({ id: 6, note: null, revenue_mape: null })],
    summary: [
      scoreRow({ method: "bear", mape: "0.0900", n: 1 }),
      scoreRow({ method: "base", mape: "0.0312", n: 1, hit_rate: "1", n_range: 1 }),
      scoreRow({ method: "bull", mape: "0.0500", n: 1 }),
    ],
    ...overrides,
  };
}

export function lineCell(overrides: Partial<SnapshotLineCellOut> = {}): SnapshotLineCellOut {
  return {
    fiscal_year: 2026,
    fiscal_period: "FY",
    label: "FY26",
    horizon: 1,
    forecast: "425000000000",
    actual: "416161000000",
    pct_error: "0.02124",
    in_range: true,
    ...overrides,
  };
}

export function snapshotCase(overrides: Partial<SnapshotCaseOut> = {}): SnapshotCaseOut {
  return {
    case: "base",
    error: null,
    warnings: [],
    lines: [
      {
        code: "net_income",
        label: "Net income",
        unit: "USD",
        cells: [
          lineCell({ forecast: "110000000000", actual: null, pct_error: null, in_range: null }),
        ],
      },
      {
        code: "revenue",
        label: "Revenue",
        unit: "USD",
        cells: [
          lineCell(),
          lineCell({
            fiscal_year: 2027,
            label: "FY27",
            horizon: 2,
            forecast: "450000000000",
            actual: null,
            pct_error: null,
            in_range: null,
          }),
        ],
      },
    ],
    drivers: [],
    valuation: [
      {
        key: "dcf",
        label: "DCF",
        value_per_share: "185.5",
        equity_value: "2750000000000",
        enterprise_value: "2800000000000",
        upside: "-0.25",
        error: null,
      },
      {
        key: "ev_ebitda",
        label: "EV/EBITDA",
        value_per_share: null,
        equity_value: null,
        enterprise_value: null,
        upside: null,
        error: "No peer multiple",
      },
    ],
    ...overrides,
  };
}

export function snapshotDetail(overrides: Partial<SnapshotDetailOut> = {}): SnapshotDetailOut {
  return {
    ...snapshotOut(),
    cases: [
      snapshotCase(),
      snapshotCase({
        case: "bull",
        warnings: ["Tax rate held flat"],
        lines: [
          {
            code: "revenue",
            label: "Revenue",
            unit: "USD",
            cells: [lineCell({ forecast: "470000000000", in_range: null })],
          },
        ],
      }),
      snapshotCase({
        case: "bear",
        error: "Set these drivers: gross_margin",
        lines: [],
        valuation: [],
      }),
    ],
    ...overrides,
  };
}

export function auditRow(overrides: Partial<AuditRowOut> = {}): AuditRowOut {
  return {
    id: 41,
    entity: "driver",
    scope: "Main · Base",
    field: "revenue_growth|2027|FY",
    label: "Revenue growth FY27",
    unit: "pct",
    old_value: "0.05",
    new_value: "0.0725",
    action: "edit",
    rationale: null,
    changed_at: "2026-11-10T12:30:00",
    ...overrides,
  };
}

export function auditPage(overrides: Partial<AuditPageOut> = {}): AuditPageOut {
  return { rows: [auditRow()], next_before_id: null, ...overrides };
}
