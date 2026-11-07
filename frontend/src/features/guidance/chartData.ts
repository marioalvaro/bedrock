import type { CustomSeriesRenderItem, EChartsOption } from "echarts";

import type { CompareOut, GuidanceEntryOut, HistoryPointOut } from "@/api/generated/types.gen";
import { formatFiscalPeriod, formatGuidanceValue } from "@/lib/format";
import type { Scale } from "@/lib/scale";

export type GuidanceFreq = "annual" | "quarterly";
type Verdict = GuidanceEntryOut["verdict"];

/** The (metric, basis) of a chart key. */
export function splitKey(key: string): { metric: string; basis: GuidanceEntryOut["basis"] } {
  const at = key.lastIndexOf("|");
  return { metric: key.slice(0, at), basis: key.slice(at + 1) as GuidanceEntryOut["basis"] };
}

/** A metric the chart can draw: one (metric, basis), keyed `metric|basis`. */
export interface ChartMetric {
  key: string;
  label: string;
  unit: string | null;
}

export interface PredictionRange {
  low: number;
  high: number;
  mid: number; // the bar's height; a point estimate has low = high = mid
  verdict: Verdict;
}

/** One period of the chart: the actual, the latest management and consensus ranges, the forecast. */
export interface ChartPoint {
  label: string;
  actual: number | null;
  management: PredictionRange | null;
  consensus: PredictionRange | null;
  forecast: number | null; // the user's forecast (the default scenario's Base case)
}

/** One forecast value of the metric. */
export interface ForecastValue {
  fiscal_year: number;
  fiscal_period: string;
  value: number;
}

// How many periods the chart shows before the current one (the latest with an actual).
const HISTORY_PERIODS: Record<GuidanceFreq, number> = { annual: 2, quarterly: 4 };
const PERIOD_ORDER: Record<string, number> = { Q1: 1, Q2: 2, Q3: 3, Q4: 4, FY: 5 };
// The tooltip is HTML, so a verdict takes its color from the CSS token directly.
const VERDICT_HTML: Record<Verdict, string> = {
  beat: '<span style="color:var(--positive)">Beat</span>',
  in_range: "In range",
  miss: '<span style="color:var(--negative)">Miss</span>',
  pending: "Pending",
};

const keyOf = (entry: GuidanceEntryOut) => `${entry.metric}|${entry.basis}`;
const inFreq = (entry: GuidanceEntryOut, freq: GuidanceFreq) =>
  (entry.fiscal_period === "FY") === (freq === "annual");
// Only the latest revision of each (metric, period, basis, source) is drawn; revisions stay in the log.
const drawn = (entries: GuidanceEntryOut[], freq: GuidanceFreq) =>
  entries.filter((entry) => entry.latest && inFreq(entry, freq));

/** The metrics with latest entries in `freq`, by label; the basis is named only when both exist. */
export function chartMetrics(entries: GuidanceEntryOut[], freq: GuidanceFreq): ChartMetric[] {
  const byKey = new Map<string, GuidanceEntryOut>();
  for (const entry of drawn(entries, freq))
    if (!byKey.has(keyOf(entry))) byKey.set(keyOf(entry), entry);
  const bases = new Map<string, number>();
  for (const entry of byKey.values()) bases.set(entry.metric, (bases.get(entry.metric) ?? 0) + 1);
  return [...byKey.entries()]
    .map(([key, entry]) => ({
      key,
      label: (bases.get(entry.metric) ?? 0) > 1 ? `${entry.label} (${entry.basis})` : entry.label,
      unit: entry.unit,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Annual when any year is guided, else quarterly. */
export function defaultFreq(entries: GuidanceEntryOut[]): GuidanceFreq {
  return entries.some((entry) => inFreq(entry, "annual")) ? "annual" : "quarterly";
}

/** Reported revenue when listed, else the first metric. */
export function defaultChartMetric(metrics: ChartMetric[]): string | undefined {
  return (metrics.find((metric) => metric.key === "revenue|reported") ?? metrics[0])?.key;
}

function range(entry: GuidanceEntryOut | undefined): PredictionRange | null {
  if (!entry) return null;
  const low = Number(entry.low);
  const high = Number(entry.high);
  return { low, high, mid: (low + high) / 2, verdict: entry.verdict };
}

/**
 * One point per period of the metric `key` in `freq`, oldest first, over the guided periods, the
 * periods of `history` (the metric's actuals) and those of `forecast`, starting `HISTORY_PERIODS`
 * before the current period (the latest with an actual; user 2026-11-07) so older periods,
 * guided or not, are left to the log. Without any actual every period is kept. The actual is
 * the history's, else the entries'.
 */
export function chartPoints(
  entries: GuidanceEntryOut[],
  key: string,
  freq: GuidanceFreq,
  history: HistoryPointOut[] = [],
  forecast: ForecastValue[] = [],
): ChartPoint[] {
  const periodKey = (year: number, period: string) => `${year}|${period}`;
  const periods = new Map<string, { year: number; period: string; entries: GuidanceEntryOut[] }>();
  const slot = (year: number, period: string) => {
    const k = periodKey(year, period);
    if (!periods.has(k)) periods.set(k, { year, period, entries: [] });
    return periods.get(k)!;
  };
  for (const entry of drawn(entries, freq).filter((e) => keyOf(e) === key)) {
    slot(entry.fiscal_year, entry.fiscal_period).entries.push(entry);
  }
  const actuals = new Map<string, string>();
  for (const point of history.filter((p) => (p.fiscal_period === "FY") === (freq === "annual"))) {
    slot(point.fiscal_year, point.fiscal_period);
    actuals.set(periodKey(point.fiscal_year, point.fiscal_period), point.value);
  }
  const forecasts = new Map<string, number>();
  for (const point of forecast.filter((p) => (p.fiscal_period === "FY") === (freq === "annual"))) {
    slot(point.fiscal_year, point.fiscal_period);
    forecasts.set(periodKey(point.fiscal_year, point.fiscal_period), point.value);
  }
  const ordered = [...periods.values()].sort(
    (a, b) => a.year - b.year || (PERIOD_ORDER[a.period] ?? 0) - (PERIOD_ORDER[b.period] ?? 0),
  );
  const points = ordered.map(({ year, period, entries: group }) => {
    const actual =
      actuals.get(periodKey(year, period)) ??
      group.find((entry) => entry.actual !== null)?.actual ??
      null;
    return {
      label: formatFiscalPeriod(year, period),
      actual: actual === null ? null : Number(actual),
      management: range(group.find((entry) => entry.source === "management")),
      consensus: range(group.find((entry) => entry.source === "consensus")),
      forecast: forecasts.get(periodKey(year, period)) ?? null,
    };
  });
  const current = points.findLastIndex((point) => point.actual !== null);
  return current < 0 ? points : points.slice(Math.max(0, current - HISTORY_PERIODS[freq]));
}

/** The Base case's forecast periods of `code` in a scenario comparison; empty without one. */
export function forecastValues(compare: CompareOut | undefined, code: string): ForecastValue[] {
  const values = compare?.cases.find((c) => c.case === "base")?.values[code];
  if (!compare || !values) return [];
  return compare.periods.flatMap((period, i) => {
    const value = values[i];
    return period.is_forecast && value !== null && value !== undefined
      ? [
          {
            fiscal_year: period.fiscal_year,
            fiscal_period: period.fiscal_period,
            value: Number(value),
          },
        ]
      : [];
  });
}

// 1, 2, 2.5, 5 or 10 times a power of ten, at least `x` (x > 0).
function niceStep(x: number): number {
  const power = 10 ** Math.floor(Math.log10(x));
  const fraction = x / power;
  const nice = [1, 2, 2.5, 5].find((n) => fraction <= n) ?? 10;
  return nice * power;
}

/**
 * The y axis of `values`: from zero (or below it for negatives), 10% of the span past each
 * extreme, rounded out to a clean step of about a fifth of the range. ECharts' own `boundaryGap`
 * pads the data's span, not the zero-based axis, so the tallest bar still touched the top.
 */
function axisBounds(values: number[]): { min: number; max: number; interval: number } | null {
  if (values.length === 0) return null;
  const high = Math.max(0, ...values);
  const low = Math.min(0, ...values);
  const span = high - low;
  if (span === 0) return null;
  const top = high > 0 ? high + span * 0.1 : 0;
  const bottom = low < 0 ? low - span * 0.1 : 0;
  const interval = niceStep((top - bottom) / 5);
  return {
    min: Math.floor(bottom / interval) * interval,
    max: Math.ceil(top / interval) * interval,
    interval,
  };
}

// The bars of one period touch (no gap); the whiskers use the same layout to find the consensus bar.
const BAR_GAP = "0%";
const BAR_MAX_WIDTH = 16;
const WHISKER_TOKEN = "--foreground";

/**
 * The chart of `points`: per period, touching bars of the actual, the consensus midpoint (next to
 * the actual, its low–high range as whiskers), the guidance midpoint and the user's forecast.
 * Only the series with data are drawn, and `colors` gives each one's token, so a series keeps
 * its color whatever else is drawn. Values stay in the metric's units; the axis and tooltip
 * format them like the log (`formatGuidanceValue`, USD in the page scale). The y axis keeps zero
 * (bars do not exaggerate a miss) and leaves headroom past the extremes (`axisBounds`).
 */
export function guidanceChart(
  points: ChartPoint[],
  unit: string | null,
  scale: Scale,
): { option: EChartsOption; colors: string[] } {
  const format = (value: number | null) =>
    formatGuidanceValue(value === null ? null : String(value), unit, scale);
  const rangeText = (r: PredictionRange) =>
    `${r.low === r.high ? format(r.low) : `${format(r.low)} – ${format(r.high)}`} · ${VERDICT_HTML[r.verdict]}`;
  const tooltip = (params: { dataIndex: number }[] | { dataIndex: number }) => {
    const first = Array.isArray(params) ? params[0] : params;
    const point = first ? points[first.dataIndex] : undefined;
    if (!point) return "";
    const lines = [`<b>${point.label}</b>`, `Actual: ${format(point.actual)}`];
    if (point.consensus) lines.push(`Consensus: ${rangeText(point.consensus)}`);
    if (point.management) lines.push(`Guidance: ${rangeText(point.management)}`);
    if (point.forecast !== null) lines.push(`Forecast: ${format(point.forecast)}`);
    return lines.join("<br/>");
  };

  const bars = [
    { name: "Actual", token: "--chart-1", data: points.map((p) => p.actual) },
    { name: "Consensus", token: "--chart-2", data: points.map((p) => p.consensus?.mid ?? null) },
    { name: "Guidance", token: "--chart-3", data: points.map((p) => p.management?.mid ?? null) },
    { name: "Forecast", token: "--chart-4", data: points.map((p) => p.forecast) },
  ].filter((bar) => bar.data.some((value) => value !== null));
  const consensusSlot = bars.findIndex((bar) => bar.name === "Consensus");

  const whiskers: CustomSeriesRenderItem = (_params, api) => {
    const low = api.value(1);
    const high = api.value(2);
    if (typeof low !== "number" || typeof high !== "number" || Number.isNaN(low + high))
      return null;
    const layout = api.barLayout({
      count: bars.length,
      barGap: BAR_GAP,
      barMaxWidth: BAR_MAX_WIDTH,
    })?.[consensusSlot];
    const index = api.value(0);
    const [center = 0, top = 0] = api.coord([index, high]);
    const [, bottom = 0] = api.coord([index, low]);
    const x = center + (layout?.offsetCenter ?? 0);
    const cap = Math.max(3, (layout?.width ?? 8) * 0.3);
    const style = { stroke: api.visual("color") as string, lineWidth: 1.5 };
    const line = (x1: number, y1: number, x2: number, y2: number) => ({
      type: "line" as const,
      shape: { x1, y1, x2, y2 },
      style,
    });
    return {
      type: "group",
      children: [
        line(x, top, x, bottom),
        line(x - cap, top, x + cap, top),
        line(x - cap, bottom, x + cap, bottom),
      ],
    };
  };

  const series: EChartsOption["series"] = bars.map((bar) => ({
    type: "bar" as const,
    name: bar.name,
    data: bar.data,
    barGap: BAR_GAP,
    barMaxWidth: BAR_MAX_WIDTH,
  }));
  const colors = bars.map((bar) => bar.token);
  if (consensusSlot >= 0) {
    series.push({
      type: "custom",
      name: "Consensus range",
      renderItem: whiskers,
      encode: { x: 0, y: [1, 2] },
      z: 3,
      silent: true,
      data: points.map((p, i) =>
        p.consensus && p.consensus.low !== p.consensus.high
          ? [i, p.consensus.low, p.consensus.high]
          : [i, "-", "-"],
      ),
    });
    colors.push(WHISKER_TOKEN);
  }

  return {
    colors,
    option: {
      grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
      legend: { data: bars.map((bar) => bar.name), top: 0 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: tooltip as never },
      xAxis: { type: "category", data: points.map((p) => p.label) },
      yAxis: {
        type: "value",
        ...axisBounds([
          ...bars.flatMap((bar) => bar.data.filter((value): value is number => value !== null)),
          ...points.flatMap((p) => (p.consensus ? [p.consensus.low, p.consensus.high] : [])),
        ]),
        axisLabel: { formatter: (value: number) => format(value) },
      },
      series,
    },
  };
}
