import type { DriverEnginesOut, EngineChoicesOut, EngineFitOut } from "@/api/generated/types.gen";

// Shapes of the M6 engine routes, cut from a recorded AAPL Main Base payload (S2, 2026-11-07):
// gross margin, the last 8 years of its run and the 2 forecast years of `driverGrid`.

const HISTORY_YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025];

export function engineFit(overrides: Partial<EngineFitOut> = {}): EngineFitOut {
  return {
    code: "arima",
    label: "ARIMA",
    values: ["0.4577900724", "0.4483942471"],
    p05: ["0.4186296438", "0.3973938854"],
    p25: ["0.4417319215", "0.4274810055"],
    p75: ["0.4738482233", "0.4693074887"],
    p95: ["0.4969505010", "0.4993946089"],
    holdout_mae: "0.0549612179",
    meta: { engine: "arima", order: [1, 0, 0], trend: "c" },
    error: null,
    ...overrides,
  };
}

/** GET …/cases/base/driver-engines?code=gross_margin: Auto picked ARIMA. */
export function driverEngines(overrides: Partial<DriverEnginesOut> = {}): DriverEnginesOut {
  return {
    driver_code: "gross_margin",
    label: "Gross margin",
    unit: "pct",
    engine: "auto",
    used: "arima",
    note: null,
    history_periods: HISTORY_YEARS.map((y) => ({ fiscal_year: y, label: `FY${y % 100}A` })),
    history: ["0.3834", "0.3781", "0.3823", "0.4177", "0.4330", "0.4413", "0.4620", "0.4690"],
    forecast_years: [2026, 2027],
    forecast_labels: ["FY26E", "FY27E"],
    values: ["0.4577900724", "0.4483942471"],
    sources: ["engine", "engine"],
    engines: [
      engineFit(),
      engineFit({
        code: "ets",
        label: "ETS",
        values: ["0.4684778317", "0.4684778317"],
        p05: ["0.4296812246", "0.4154429817"],
        p25: ["0.4525688698", "0.4467303266"],
        p75: ["0.4843867937", "0.4902253369"],
        p95: ["0.5072744389", "0.5215126818"],
        holdout_mae: "0.0665143546",
        meta: { engine: "ets", trend: null },
      }),
      engineFit({
        code: "blend",
        label: "Blend",
        values: ["0.4631339521", "0.4584360394"],
        p05: ["0.4241554342", "0.4064184336"],
        p25: ["0.4471503956", "0.4371056661"],
        p75: ["0.4791175085", "0.4797664128"],
        p95: ["0.5021124699", "0.5104536453"],
        holdout_mae: "0.0607377862",
        meta: { engine: "blend" },
      }),
    ],
    mean: "0.4574754783",
    seasonal: [
      { fiscal_period: "Q1", value: "-0.0003055679" },
      { fiscal_period: "Q2", value: "0.0120570219" },
      { fiscal_period: "Q3", value: "0.0030852309" },
      { fiscal_period: "Q4", value: "-0.0148366850" },
    ],
    ...overrides,
  };
}

/** PUT …/engines reply: gross margin on ETS. */
export function engineChoices(overrides: Partial<EngineChoicesOut> = {}): EngineChoicesOut {
  return {
    scenario_id: 1,
    rows: [
      {
        driver_code: "gross_margin",
        label: "Gross margin",
        group: "Costs",
        unit: "pct",
        engine: "ets",
        used: "ets",
        note: null,
        seasonal: true,
      },
    ],
    ...overrides,
  };
}
