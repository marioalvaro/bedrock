import type {
  CompareOut,
  DriverGridOut,
  DriverImportOut,
  DriverRowOut,
  ForecastOut,
  PeriodOut,
  ScenarioOut,
} from "@/api/generated/types.gen";

// Shapes of the M4 scenario routes, for AAPL (fiscal years ending in September).

const STAMP = "2026-10-31T09:00:00Z";

export function scenario(overrides: Partial<ScenarioOut> = {}): ScenarioOut {
  return {
    id: 1,
    name: "Main",
    is_default: true,
    revenue_method: "growth",
    segment_dimension: null,
    volume_kpi: null,
    price_kpi: null,
    created_at: STAMP,
    updated_at: STAMP,
    ...overrides,
  };
}

/** GET …/scenarios: the default scenario "Main" first, then a user scenario "Cycle". */
export function scenarios(): ScenarioOut[] {
  return [scenario(), scenario({ id: 2, name: "Cycle", is_default: false })];
}

export function driverRow(overrides: Partial<DriverRowOut> = {}): DriverRowOut {
  return {
    code: "revenue_growth",
    label: "Revenue growth",
    group: "Revenue",
    unit: "pct",
    history: ["0.0779", "-0.028", "0.0202"],
    values: ["0.0234", "0.0234"],
    sources: ["default", "default"],
    own: [null, null],
    kind: null,
    rollup: [null, null],
    quarterly: true,
    engine: "auto",
    engine_used: "mean",
    engine_note: null,
    seasonal: false,
    check: [null, null],
    ...overrides,
  };
}

/** GET …/years: FY2026 is in the quarterly span, FY2027 is not; both annual. */
export function yearModes(): DriverGridOut["year_modes"] {
  return [
    { fiscal_year: 2026, label: "FY26E", mode: "annual", in_span: true },
    { fiscal_year: 2027, label: "FY27E", mode: "annual", in_span: false },
  ];
}

/** Both forecast years' modes: FY2026 (in the span) set as `modes[2026]`, FY2027 never in the span. */
export function modesOf(mode: "annual" | "quarterly"): DriverGridOut["year_modes"] {
  return yearModes().map((m) => (m.in_span ? { ...m, mode } : m));
}

/**
 * GET …/drivers of Base: 3 history years and 2 forecast years (kept small: jsdom renders only
 * about 10 grid rows, G25). Rows: revenue growth (default), gross margin (own value in FY2026),
 * tax rate (required, unset), receivable days (held flat in FY2027), buybacks (USD).
 */
export function driverGrid(overrides: Partial<DriverGridOut> = {}): DriverGridOut {
  return {
    scenario_id: 1,
    case: "base",
    freq: "annual",
    year_modes: yearModes(),
    has_quarters: true,
    history_years: [2023, 2024, 2025],
    forecast_years: [2026, 2027],
    history_periods: [2023, 2024, 2025].map((y) => ({
      fiscal_year: y,
      fiscal_period: "FY" as const,
      label: `FY${y % 100}A`,
    })),
    forecast_periods: [2026, 2027].map((y) => ({
      fiscal_year: y,
      fiscal_period: "FY" as const,
      label: `FY${y % 100}E`,
    })),
    rows: [
      driverRow(),
      driverRow({
        code: "gross_margin",
        label: "Gross margin",
        group: "Costs",
        history: ["0.441", "0.462", "0.469"],
        values: ["0.47", "0.4573"],
        sources: ["own", "default"],
        own: ["0.47", null],
        kind: "value",
      }),
      driverRow({
        code: "tax_rate",
        label: "Tax rate",
        group: "Below the line",
        history: [null, null, null],
        values: [null, null],
        sources: [null, null],
      }),
      driverRow({
        code: "receivable_days",
        label: "Receivable days",
        group: "Working capital",
        unit: "days",
        history: ["58.3", "61.2", "62.0"],
        values: ["60.5", null],
        sources: ["default", "default"],
      }),
      driverRow({
        code: "buybacks",
        label: "Buybacks",
        group: "Shareholders",
        unit: "USD",
        history: ["77550000000", "94949000000", "90711000000"],
        values: ["87736666666.67", "87736666666.67"],
        sources: ["default", "default"],
      }),
    ],
    warnings: [],
    ...overrides,
  };
}

/**
 * GET …/drivers?freq=quarterly of Base: 3 actual quarters (Q2–Q4 FY25A) and 2 forecast quarters
 * (Q1–Q2 FY26E; FY2026 is set by quarter), the same five drivers as `driverGrid`. A quarter with no row of its own takes
 * its year's value (source `year`): only gross margin Q1 FY26 is set (own).
 */
export function quarterlyGrid(overrides: Partial<DriverGridOut> = {}): DriverGridOut {
  const quarter = (fiscal_year: number, fiscal_period: "Q1" | "Q2" | "Q3" | "Q4", tag: string) => ({
    fiscal_year,
    fiscal_period,
    label: `${fiscal_period} FY${fiscal_year % 100}${tag}`,
  });
  return {
    scenario_id: 1,
    case: "base",
    freq: "quarterly",
    year_modes: modesOf("quarterly"), // quarter values exist only in a year set by quarter
    has_quarters: true,
    history_years: [2023, 2024, 2025],
    forecast_years: [2026, 2027],
    history_periods: [quarter(2025, "Q2", "A"), quarter(2025, "Q3", "A"), quarter(2025, "Q4", "A")],
    forecast_periods: [quarter(2026, "Q1", "E"), quarter(2026, "Q2", "E")],
    rows: [
      driverRow({
        history: ["0.0507", "0.0384", "0.0627"],
        values: ["0.0234", "0.0234"],
        sources: ["year", "year"],
      }),
      driverRow({
        code: "gross_margin",
        label: "Gross margin",
        group: "Costs",
        history: ["0.468", "0.465", "0.469"],
        values: ["0.48", "0.47"],
        sources: ["own", "year"],
        own: ["0.48", null],
        kind: "value",
      }),
      driverRow({
        code: "tax_rate",
        label: "Tax rate",
        group: "Below the line",
        history: [null, null, null],
        values: [null, null],
        sources: [null, null],
      }),
      driverRow({
        code: "receivable_days",
        label: "Receivable days",
        group: "Working capital",
        unit: "days",
        history: ["58.3", "61.2", "62.0"],
        values: [null, null],
        sources: ["default", "default"],
      }),
      driverRow({
        code: "buybacks",
        label: "Buybacks",
        group: "Shareholders",
        unit: "USD",
        history: ["22000000000", "23500000000", "21000000000"],
        values: ["21934166666.67", "21934166666.67"],
        sources: ["year", "year"],
      }),
    ],
    warnings: [],
    ...overrides,
  };
}

/** GET …/cases/bull/drivers of "Main": revenue growth held as an offset on Base (+3 pts each year). */
export function bullGrid(): DriverGridOut {
  const base = driverGrid();
  return {
    ...base,
    case: "bull",
    rows: [
      driverRow({
        values: ["0.0534", "0.0534"],
        sources: ["offset", "offset"],
        own: ["0.03", "0.03"],
        kind: "offset",
      }),
      driverRow({
        code: "gross_margin",
        label: "Gross margin",
        group: "Costs",
        history: ["0.441", "0.462", "0.469"],
        values: ["0.47", "0.4573"],
        sources: ["base", "default"],
        own: [null, null],
        kind: null,
      }),
      ...base.rows.slice(2),
    ],
  };
}

export function driverImport(overrides: Partial<DriverImportOut> = {}): DriverImportOut {
  return {
    dry_run: true,
    changes: [
      {
        driver_code: "revenue_growth",
        fiscal_year: 2027,
        fiscal_period: "FY",
        old: "0.05",
        new: "0.08",
        old_kind: "value",
        new_kind: "value",
      },
      {
        driver_code: "gross_margin",
        fiscal_year: 2026,
        fiscal_period: "FY",
        old: "0.47",
        new: null,
        old_kind: "value",
        new_kind: null,
      },
    ],
    grid: null,
    ...overrides,
  };
}

function forecastPeriod(year: number, quarter?: number): PeriodOut {
  const period = quarter ? `Q${quarter}` : "FY";
  const short = String(year).slice(2);
  return {
    key: quarter ? `Q${quarter}FY${year}` : `FY${year}`,
    label: quarter ? `Q${quarter} FY${short}E` : `FY${short}E`,
    fiscal_year: year,
    fiscal_period: period,
    period_start: `${year - 1}-09-28`,
    period_end: `${year}-09-26`,
    is_forecast: true,
  };
}

/** GET …/scenarios/1/compare (annual): revenue and EPS for Base, Bull and Bear; Bear cannot run. */
export function comparison(overrides: Partial<CompareOut> = {}): CompareOut {
  return {
    periods: [forecastPeriod(2026), forecastPeriod(2027)],
    codes: [
      { code: "revenue", label: "Revenue", unit: "USD" },
      { code: "eps_diluted", label: "EPS (diluted)", unit: "USD/shares" },
    ],
    cases: [
      {
        case: "base",
        label: "Base",
        values: { revenue: ["425000000000", "435000000000"], eps_diluted: ["7.1", "7.45"] },
        error: null,
      },
      {
        case: "bull",
        label: "Bull",
        values: { revenue: ["437000000000", "460000000000"], eps_diluted: ["7.52", "8.1"] },
        error: null,
      },
      {
        case: "bear",
        label: "Bear",
        values: {},
        error: "Set these drivers: tax_rate",
      },
    ],
    built_from_quarters: [],
    ...overrides,
  };
}

/** GET …/scenarios/{id}/cases/base/forecast?type=IS&freq=annual, trimmed to revenue. */
export function forecast(overrides: Partial<ForecastOut> = {}): ForecastOut {
  return {
    ticker: "AAPL",
    statement: "IS",
    freq: "annual",
    basis: "normalized",
    currency: "USD",
    scenario_id: 1,
    case: "base",
    built_from_quarters: [],
    periods: [forecastPeriod(2026)],
    rows: [],
    balance_check: null,
    integrity: [
      {
        period_key: "FY2026",
        balance_diff: "0",
        cash_diff: "0",
        re_diff: "0",
        quarters_diff: null,
        ok: true,
      },
    ],
    warnings: [],
    ...overrides,
  };
}

function actualPeriod(year: number): PeriodOut {
  return {
    key: `FY${year}`,
    label: `FY${year}`,
    fiscal_year: year,
    fiscal_period: "FY",
    period_start: `${year - 1}-09-28`,
    period_end: `${year}-09-26`,
    is_forecast: false,
  };
}

/**
 * GET …/scenarios/1/cases/base/forecast?type=IS&freq=annual: FY2024–FY2025 actuals (normalized), then
 * FY2026E–FY2027E. Rows: revenue with gross profit under it, and net income.
 */
export function forecastIncome(overrides: Partial<ForecastOut> = {}): ForecastOut {
  const line = (code: string, label: string, depth: number, values: string[]) => ({
    code,
    label,
    unit: "USD",
    kind: "flow" as const,
    depth,
    values,
    provenance: [
      "reported",
      "normalized",
      "forecast",
      "forecast",
    ] as ForecastOut["rows"][number]["provenance"],
    yoy: [null, null, null, null],
    common_size: [null, null, null, null],
    adjustable: false,
    custom: false,
    parent: null,
    common_size_base: null,
  });
  return forecast({
    periods: [actualPeriod(2024), actualPeriod(2025), forecastPeriod(2026), forecastPeriod(2027)],
    rows: [
      line("revenue", "Revenue", 0, [
        "391035000000",
        "416161000000",
        "425900000000",
        "435870000000",
      ]),
      line("gross_profit", "Gross profit", 1, [
        "180683000000",
        "195201000000",
        "199773000000",
        "204453000000",
      ]),
      line("net_income", "Net income", 0, [
        "93736000000",
        "112010000000",
        "114300000000",
        "117900000000",
      ]),
    ],
    integrity: [
      {
        period_key: "FY2026",
        balance_diff: "0",
        cash_diff: "0",
        re_diff: "0",
        quarters_diff: "0",
        ok: true,
      },
      {
        period_key: "FY2027",
        balance_diff: "0",
        cash_diff: "0",
        re_diff: "0",
        quarters_diff: null,
        ok: true,
      },
    ],
    ...overrides,
  });
}
