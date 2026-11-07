import type { EChartsOption, LineSeriesOption } from "echarts";

import type { DriverEnginesOut, EngineFitOut } from "@/api/generated/types.gen";
import { formatChartNumber, scaledNumber } from "@/lib/format";
import type { Scale } from "@/lib/scale";

import { formatDriverValue, formatEngineError, type DriverUnit } from "./driverCells";

// The Engines sheet's chart and table, from the backend's `DriverEnginesOut`. Everything here only
// lays out and formats; the values, bands and errors are the backend's.

export const BAND_LOW = "90% range low";
export const BAND = "90% range";

/** Color tokens by series position: History, ARIMA, ETS, Blend, the case, the band's two lines. */
export const ENGINE_CHART_COLORS = [
  "--muted-foreground",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-1",
  "--chart-1",
  "--chart-1",
];

// A driver value as a chart number: pct in percent, days as they are, USD in the page scale.
function chartNumber(value: string | null | undefined, unit: DriverUnit, scale: Scale) {
  const number = scaledNumber(value ?? null, unit, scale);
  return number !== null && unit === "pct" ? number * 100 : number;
}

// An axis or tooltip number, in the unit the chart draws.
const chartText = (value: number, unit: DriverUnit) =>
  `${formatChartNumber(value, unit)}${unit === "pct" ? "%" : ""}`;

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
const escapeHtml = (text: string) => text.replace(/[&<>"]/g, (c) => ESCAPES[c] ?? c);

/** The engine whose 90% band the sheet draws: the one in use, when it fit. */
export function bandEngine(view: DriverEnginesOut): EngineFitOut | undefined {
  const used = view.engines.find((engine) => engine.code === view.used);
  return used && !used.error && used.values.length > 0 ? used : undefined;
}

/**
 * The line chart: x = the history labels then the forecast labels; History, the three engines
 * (dashed; an engine that failed keeps an empty series so each keeps its color), the case's
 * resolved values (solid, from the last actual point on) and the used engine's 90% band as two
 * stacked lines, the upper one filled.
 */
export function engineChartOption(
  view: DriverEnginesOut,
  caseLabel: string,
  scale: Scale,
): EChartsOption {
  const { unit } = view;
  const past = view.history.length;
  const ahead = view.forecast_labels.length;
  const value = (v: string | null | undefined) => chartNumber(v, unit, scale);
  const blanks = (n: number) => Array<null>(n).fill(null);
  const forecast = (values: (string | null)[]) => [...blanks(past), ...values.map(value)];

  const line = (name: string, data: (number | null)[], extra: LineSeriesOption = {}) =>
    ({
      type: "line",
      name,
      data,
      symbol: "none",
      connectNulls: false,
      ...extra,
    }) as LineSeriesOption;

  const series: LineSeriesOption[] = [
    line("History", [...view.history.map(value), ...blanks(ahead)], { symbol: "circle" }),
    ...view.engines.map((engine) =>
      line(engine.label, engine.error ? [] : forecast(engine.values), {
        lineStyle: { type: "dashed" },
      }),
    ),
    line(
      `${caseLabel} case`,
      // From the last actual point on, so the case joins the history (none: the forecast alone).
      past === 0
        ? view.values.map(value)
        : [...blanks(past - 1), value(view.history.at(-1)), ...view.values.map(value)],
      {
        lineStyle: { type: "solid", width: 2 },
      },
    ),
  ];
  const band = bandEngine(view);
  if (band) {
    const low = band.p05.map(value);
    const width = band.p95.map((p95, i) => {
      const top = value(p95);
      const bottom = low[i] ?? null;
      return top === null || bottom === null ? null : top - bottom;
    });
    const hidden = { lineStyle: { opacity: 0 }, stack: "band" };
    series.push(line(BAND_LOW, [...blanks(past), ...low], hidden));
    series.push(
      line(BAND, [...blanks(past), ...width], { ...hidden, areaStyle: { opacity: 0.15 } }),
    );
  }

  const labels = [...view.history_periods.map((period) => period.label), ...view.forecast_labels];
  return {
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    legend: { data: series.map((s) => String(s.name)).filter((name) => name !== BAND_LOW), top: 0 },
    tooltip: {
      trigger: "axis",
      // The band's upper line holds its width: the tooltip names the range from the engine's bounds.
      formatter: (params) => {
        const items = (Array.isArray(params) ? params : [params]) as {
          seriesName?: string;
          value?: unknown;
          dataIndex: number;
          marker?: unknown;
        }[];
        const index = items[0]?.dataIndex ?? 0;
        const lines = [escapeHtml(labels[index] ?? "")];
        for (const item of items) {
          if (item.seriesName === BAND || item.seriesName === BAND_LOW) continue;
          if (typeof item.value !== "number") continue;
          lines.push(
            `${typeof item.marker === "string" ? item.marker : ""}${escapeHtml(item.seriesName ?? "")}: ${chartText(item.value, unit)}`,
          );
        }
        const at = index - past;
        if (band && at >= 0 && band.p05[at] !== undefined && band.p95[at] !== undefined) {
          const range = `${formatDriverValue(band.p05[at]!, unit, scale)}–${formatDriverValue(band.p95[at]!, unit, scale)}`;
          lines.push(`${BAND} (${escapeHtml(band.label)}): ${escapeHtml(range)}`);
        }
        return lines.join("<br/>");
      },
    },
    // Each year sits on its tick (not between two), so the axis pointer, tick and point line up.
    xAxis: { type: "category", data: labels, boundaryGap: false },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { formatter: (number: number) => chartText(number, unit) },
    },
    series,
  };
}

export interface EngineTableRow {
  code: string; // an engine code, or "mean"
  label: string;
  inUse: boolean;
  cells: string[]; // one per forecast year
  error: string | null; // shown across the row in place of its cells
  holdout: string;
}

/** The table under the chart: ARIMA, ETS, Blend (API order), then Mean (3 yr). */
export function engineTableRows(view: DriverEnginesOut, scale: Scale): EngineTableRow[] {
  const { unit } = view;
  const rows: EngineTableRow[] = view.engines.map((engine) => ({
    code: engine.code,
    label: engine.label,
    inUse: engine.code === view.used,
    cells: engine.values.map((v) => formatDriverValue(v, unit, scale)),
    error: engine.error,
    holdout: formatEngineError(engine.holdout_mae, unit, scale),
  }));
  rows.push({
    code: "mean",
    label: "Mean (3 yr)",
    inUse: view.used === "mean",
    cells: view.forecast_labels.map(() => formatDriverValue(view.mean, unit, scale)),
    error: null,
    holdout: formatEngineError(null, unit, scale),
  });
  return rows;
}
