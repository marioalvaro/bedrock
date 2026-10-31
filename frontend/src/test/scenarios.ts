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
    name: "Base",
    is_default: true,
    base_id: null,
    revenue_method: "growth",
    segment_dimension: null,
    volume_kpi: null,
    price_kpi: null,
    created_at: STAMP,
    updated_at: STAMP,
    ...overrides,
  };
}

/** GET …/scenarios: the defaults, Base first. */
export function scenarios(): ScenarioOut[] {
  return [
    scenario(),
    scenario({ id: 2, name: "Bull", is_default: false, base_id: 1 }),
    scenario({ id: 3, name: "Bear", is_default: false, base_id: 1 }),
  ];
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
    ...overrides,
  };
}

/**
 * GET …/drivers of Base: 3 history years and 2 forecast years (kept small: jsdom renders only
 * about 10 grid rows, G25). Rows: revenue growth (default), gross margin (own value in FY2026),
 * tax rate (required, unset), receivable days (held flat in FY2027), buybacks (USD).
 */
export function driverGrid(overrides: Partial<DriverGridOut> = {}): DriverGridOut {
  return {
    scenario_id: 1,
    history_years: [2023, 2024, 2025],
    forecast_years: [2026, 2027],
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

/** GET …/drivers of Bull: revenue growth held as an offset on Base (+3 pts each year). */
export function bullGrid(): DriverGridOut {
  const base = driverGrid();
  return {
    ...base,
    scenario_id: 2,
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
        old: "0.05",
        new: "0.08",
        old_kind: "value",
        new_kind: "value",
      },
      {
        driver_code: "gross_margin",
        fiscal_year: 2026,
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

/** GET …/scenarios/compare (annual): revenue and EPS for the three defaults; Bear cannot run. */
export function comparison(overrides: Partial<CompareOut> = {}): CompareOut {
  return {
    periods: [forecastPeriod(2026), forecastPeriod(2027)],
    codes: [
      { code: "revenue", label: "Revenue", unit: "USD" },
      { code: "eps_diluted", label: "EPS (diluted)", unit: "USD/shares" },
    ],
    scenarios: [
      {
        id: 1,
        name: "Base",
        values: { revenue: ["425000000000", "435000000000"], eps_diluted: ["7.1", "7.45"] },
        error: null,
      },
      {
        id: 2,
        name: "Bull",
        values: { revenue: ["437000000000", "460000000000"], eps_diluted: ["7.52", "8.1"] },
        error: null,
      },
      {
        id: 3,
        name: "Bear",
        values: {},
        error: "Set these drivers: tax_rate",
      },
    ],
    ...overrides,
  };
}

/** GET …/scenarios/{id}/forecast?type=IS&freq=annual, trimmed to revenue. */
export function forecast(overrides: Partial<ForecastOut> = {}): ForecastOut {
  return {
    ticker: "AAPL",
    statement: "IS",
    freq: "annual",
    basis: "normalized",
    currency: "USD",
    scenario_id: 1,
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
