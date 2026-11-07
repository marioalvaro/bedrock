import type { EChartsOption, LineSeriesOption } from "echarts";

import type { SeasonalityOut } from "@/api/generated/types.gen";
import { formatChartNumber, formatValue, scaledNumber } from "@/lib/format";
import type { Scale } from "@/lib/scale";

// The Seasonality tab's texts and chart options, from the backend's `SeasonalityOut`. Everything
// here only lays out and formats; the decomposition, factors and strength are the backend's.

const DASH = "—";
const MINUS = "−";
export const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;

/** Color tokens by series position, one list per chart (module constants: `Chart` memoizes on them). */
export const OBSERVED_COLORS = ["--chart-1", "--chart-2"];
export const SEASONAL_COLORS = ["--chart-3"];
export const RESIDUAL_COLORS = ["--muted-foreground"];

export const FACTOR_ROWS = ["Amount", "% of trend"] as const;

// About one axis-label character (12 px tabular digits), in px.
const CHAR_PX = 7;

/** "Seasonal strength 0.98 · 0 = none, 1 = strong". */
export function formatStrength(strength: number): string {
  return `Seasonal strength ${strength.toFixed(2)} · 0 = none, 1 = strong`;
}

// "+" or a true minus before `text` (the magnitude); a magnitude that rounds to zero has no sign.
function signed(number: number, text: string): string {
  if (/^[0.,]+%?$/.test(text)) return text;
  return `${number < 0 ? MINUS : "+"}${text}`;
}

/**
 * An amount in the line's unit, signed: USD and share counts in the page scale ("+16,029" in M),
 * per-share amounts with 2 decimals; a value that rounds to zero is unsigned.
 */
export function formatSignedAmount(value: number, unit: string, scale: Scale): string {
  return signed(value, formatValue(String(Math.abs(value)), unit, scale));
}

/** A fraction as a signed percent with 1 decimal ("+23.1%", "−7.4%"); null "—". */
export function formatSignedPct(value: number | null): string {
  if (value === null) return DASH;
  return signed(value, `${Math.abs(value * 100).toFixed(1)}%`);
}

export interface FactorRow {
  label: (typeof FACTOR_ROWS)[number];
  cells: string[]; // Q1..Q4
}

/** The "Seasonal factors" table: Amount (signed, page scale) and % of trend, by quarter. */
export function factorRows(view: SeasonalityOut, scale: Scale): FactorRow[] {
  const byQuarter = QUARTERS.map((q) => view.factors.find((f) => f.fiscal_period === q));
  return [
    {
      label: "Amount",
      cells: byQuarter.map((f) => (f ? formatSignedAmount(f.value, view.unit, scale) : DASH)),
    },
    { label: "% of trend", cells: byQuarter.map((f) => formatSignedPct(f?.pct ?? null)) },
  ];
}

export interface SeasonalityCharts {
  observed: EChartsOption;
  seasonal: EChartsOption;
  residual: EChartsOption;
}

/**
 * The three stacked charts, sharing x = the period labels (each quarter on its tick):
 * "Observed and trend", "Seasonal" and "Residual" (a line with points), values in the page scale,
 * with one left margin so the plots line up; only the two-series chart has a legend.
 */
export function seasonalityCharts(view: SeasonalityOut, scale: Scale): SeasonalityCharts {
  const { unit } = view;
  const labels = view.periods.map((period) => period.label);
  const values = (data: number[]) => data.map((v) => scaledNumber(String(v), unit, scale));
  const line = (name: string, data: number[], extra: LineSeriesOption = {}): LineSeriesOption => ({
    type: "line",
    name,
    data: values(data),
    symbol: "none",
    ...extra,
  });
  // One left margin for the three plots, so a quarter sits at the same x in each (ECharts sizes
  // `containLabel` per chart). It fits the widest label a nice tick past the largest magnitude
  // could print, negative (in parentheses) included.
  const scaled = [view.observed, view.trend, view.seasonal, view.residual].flatMap(values);
  const largest = Math.max(0, ...scaled.map((v) => Math.abs(v ?? 0)));
  const left = formatChartNumber(-largest * 1.5, unit).length * CHAR_PX + 16;
  const option = (series: LineSeriesOption[]): EChartsOption => ({
    grid: { left, right: 16, top: series.length > 1 ? 32 : 16, bottom: 24, containLabel: false },
    legend:
      series.length > 1 ? { data: series.map((s) => String(s.name)), top: 0 } : { show: false },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v) => formatChartNumber(typeof v === "number" ? v : null, unit),
    },
    xAxis: { type: "category", data: labels, boundaryGap: false },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { formatter: (number: number) => formatChartNumber(number, unit) },
    },
    series,
  });
  return {
    observed: option([line("Observed", view.observed), line("Trend", view.trend)]),
    seasonal: option([line("Seasonal", view.seasonal)]),
    residual: option([line("Residual", view.residual, { symbol: "circle", symbolSize: 4 })]),
  };
}
