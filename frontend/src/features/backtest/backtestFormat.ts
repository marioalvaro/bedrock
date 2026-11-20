import type { EChartsOption, LineSeriesOption } from "echarts";

import type { BacktestOut, ScoreRowOut, SnapshotOut } from "@/api/generated/types.gen";
import {
  formatCompact,
  formatHitRate,
  formatPercent,
  formatRelative,
  formatSignedPercent,
  DASH,
  utcDate,
} from "@/lib/format";

// The Backtest tab's texts, tables and chart options. Everything here only lays out and formats
// the backend's scores: errors, MAPE, bias and hit rates are computed there.

const MINUS = "−";
const OFFSET = "offset:";

export type Stat = "mape" | "bias" | "hit_rate";
export type Freq = ScoreRowOut["freq"];

export const STATS: { value: Stat; label: string }[] = [
  { value: "mape", label: "MAPE" },
  { value: "bias", label: "Bias" },
  { value: "hit_rate", label: "Hit rate" },
];

const METHODS: [code: string, label: string][] = [
  ["auto", "Auto"],
  ["mean", "Mean (3 yr)"],
  ["arima", "ARIMA"],
  ["ets", "ETS"],
  ["blend", "Blend"],
  ["stl", "STL"],
  ["base", "Base"],
  ["bull", "Bull"],
  ["bear", "Bear"],
];
const METHOD_LABELS = new Map(METHODS);
const METHOD_ORDER = METHODS.map(([code]) => code);

/** Color tokens by series position: six engines against the palette's five (a module constant: `Chart` memoizes on it). */
export const METHOD_CHART_COLORS = [
  "--chart-1",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-5",
  "--muted-foreground",
];

export const methodLabel = (code: string) => METHOD_LABELS.get(code) ?? code;

const methodRank = (code: string) => {
  const rank = METHOD_ORDER.indexOf(code);
  return rank === -1 ? METHOD_ORDER.length : rank;
};

/** An API timestamp in the browser's time zone ("Nov 10, 2026, 1:30 PM"). */
export function formatLocalTime(iso: string): string {
  return utcDate(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

const magnitude = (number: number, minDecimals: number) =>
  Math.abs(number).toLocaleString("en-US", {
    minimumFractionDigits: minDecimals,
    maximumFractionDigits: 2,
  });

// Up to 2 decimals, so an audited 7.25% does not read as 7.3%.
function auditMagnitude(number: number, unit: string | null): string {
  if (unit === "pct") return `${magnitude(number * 100, 1)} pts`;
  if (unit === "days") return `${magnitude(number, 0)} days`;
  if (unit === "USD") return formatCompact(String(Math.abs(number)));
  return magnitude(number, 0);
}

function formatOffset(text: string, value: string, unit: string | null): string {
  const number = Number(text);
  if (text === "" || !Number.isFinite(number)) return value;
  const body = auditMagnitude(number, unit);
  if (number === 0) return body;
  return `${number < 0 ? MINUS : "+"}${body}`;
}

/**
 * A logged value: null "—", an `offset:` value as a signed offset ("+1.0 pts"), `pct` as a
 * percent, `days`, USD compact, negatives in parentheses; any other text as it is.
 */
export function formatAuditValue(value: string | null, unit: string | null): string {
  if (value === null) return DASH;
  if (value.startsWith(OFFSET)) return formatOffset(value.slice(OFFSET.length), value, unit);
  const number = Number(value);
  if (!Number.isFinite(number) || value === "") return value;
  if (unit === "USD") return formatCompact(value);
  if (unit !== "pct" && unit !== "days") return value;
  const body = unit === "pct" ? `${magnitude(number * 100, 1)}%` : `${magnitude(number, 0)} days`;
  return number < 0 ? `(${body})` : body;
}

/** A score: MAPE as a percent, bias signed, the hit rate whole; null "—". */
export function formatStat(stat: Stat, value: string | null): string {
  if (stat === "mape") return formatPercent(value);
  return stat === "bias" ? formatSignedPercent(value) : formatHitRate(value);
}

export interface MetricOption {
  code: string;
  label: string;
}

function distinctMetrics(rows: ScoreRowOut[]): MetricOption[] {
  const byCode = new Map(rows.map((row) => [row.code, row.label]));
  return [...byCode].map(([code, label]) => ({ code, label }));
}

/** The metric select's options: each scored line, then each scored driver. */
export function metricOptions(summary: ScoreRowOut[]): {
  lines: MetricOption[];
  drivers: MetricOption[];
} {
  return {
    lines: distinctMetrics(summary.filter((row) => row.kind === "line")),
    drivers: distinctMetrics(summary.filter((row) => row.kind === "driver")),
  };
}

export interface AskedSelection {
  metric: string | null;
  freq: string | null;
  stat: string | null;
}

export interface Selection {
  code: string;
  label: string;
  kind: ScoreRowOut["kind"];
  freq: Freq;
  stat: Stat;
  hitRateAvailable: boolean;
}

/**
 * What the toolbar shows, from what the URL asks: an unknown metric falls back to Revenue (then
 * to the first scored metric), a driver is annual only, and a hit rate the selection has no
 * ranges for falls back to MAPE. Null when nothing is scored.
 */
export function resolveSelection(summary: ScoreRowOut[], asked: AskedSelection): Selection | null {
  const row =
    summary.find((r) => r.code === asked.metric) ??
    summary.find((r) => r.code === "revenue") ??
    summary[0];
  if (!row) return null;
  const freq: Freq = row.kind === "line" && asked.freq === "quarterly" ? "quarterly" : "annual";
  const hitRateAvailable = summary.some(
    (r) => r.code === row.code && r.freq === freq && r.n_range > 0,
  );
  const known = STATS.some(({ value }) => value === asked.stat);
  const stat: Stat =
    known && (asked.stat !== "hit_rate" || hitRateAvailable) ? (asked.stat as Stat) : "mape";
  return { code: row.code, label: row.label, kind: row.kind, freq, stat, hitRateAvailable };
}

export interface ScoreCell {
  horizon: number;
  text: string;
  title: string | undefined;
}

export interface ScoreTableRow {
  method: string;
  label: string;
  cells: ScoreCell[];
}

export interface ScoreTableData {
  horizons: number[];
  rows: ScoreTableRow[];
}

// The selection's rows as sorted horizons and method codes in display order.
function selected(summary: ScoreRowOut[], selection: Selection) {
  const rows = summary.filter((r) => r.code === selection.code && r.freq === selection.freq);
  return {
    rows,
    horizons: [...new Set(rows.map((r) => r.horizon))].sort((a, b) => a - b),
    methods: [...new Set(rows.map((r) => r.method))].sort((a, b) => methodRank(a) - methodRank(b)),
  };
}

/** Methods × horizons for the selection, with each cell's `n` in its title. */
export function scoreTableRows(summary: ScoreRowOut[], selection: Selection): ScoreTableData {
  const { rows, horizons, methods } = selected(summary, selection);
  return {
    horizons,
    rows: methods.map((method) => ({
      method,
      label: methodLabel(method),
      cells: horizons.map((horizon) => {
        const row = rows.find((r) => r.method === method && r.horizon === horizon);
        return {
          horizon,
          text: row ? formatStat(selection.stat, row[selection.stat]) : DASH,
          title: row ? `n = ${row.n}` : undefined,
        };
      }),
    })),
  };
}

/** The stat by horizon, one line per method, in percent. A horizon with no score leaves a gap. */
export function horizonChartOption(summary: ScoreRowOut[], selection: Selection): EChartsOption {
  const { rows, horizons, methods } = selected(summary, selection);
  const series: LineSeriesOption[] = methods.map((method) => ({
    name: methodLabel(method),
    type: "line",
    showSymbol: true,
    data: horizons.map((horizon) => {
      const row = rows.find((r) => r.method === method && r.horizon === horizon);
      const value = row?.[selection.stat] ?? null;
      return value === null ? null : Number(value) * 100;
    }),
  }));
  return {
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) =>
        typeof value === "number" ? formatStat(selection.stat, String(value / 100)) : DASH,
    },
    legend: { top: 0 },
    grid: { left: 16, right: 16, top: 32, bottom: 32, containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: false,
      name: selection.freq === "annual" ? "Years ahead" : "Quarters ahead",
      nameLocation: "middle",
      nameGap: 28,
      data: horizons.map(String),
    },
    yAxis: { type: "value", axisLabel: { formatter: "{value}%" } },
    series,
  };
}

const counted = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "Last run 2h ago · 10 origins, 3 method runs could not run". */
export function backtestStatus(view: BacktestOut, now: Date): string {
  const when = view.ran_at === null ? null : utcDate(view.ran_at).toISOString();
  const failed = view.origins.flatMap((origin) => origin.runs).filter((run) => run.error !== null);
  const origins = counted(view.origins.length, "origin", "origins");
  const runs = counted(failed.length, "method run", "method runs");
  return `Last run ${formatRelative(when, now)} · ${origins}, ${runs} could not run`;
}

/** Each run that could not run: "2024-11-01 · ARIMA: Set these drivers: gross_margin". */
export function failedRuns(view: BacktestOut): string[] {
  return view.origins.flatMap((origin) =>
    origin.runs
      .filter((run) => run.error !== null)
      .map((run) => `${origin.as_of_date} · ${methodLabel(run.method)}: ${run.error}`),
  );
}

/** The score selectors' URL parameters. */
export const METRIC_PARAM = "metric";
export const FREQ_PARAM = "freq";
export const STAT_PARAM = "stat";

/** What the URL asks the score selectors to show. */
export function askedSelection(params: URLSearchParams): AskedSelection {
  return {
    metric: params.get(METRIC_PARAM),
    freq: params.get(FREQ_PARAM),
    stat: params.get(STAT_PARAM),
  };
}

type ClassificationMode = NonNullable<SnapshotOut["classification_mode"]>;
const MODE_NAMES: Record<ClassificationMode, string> = {
  off: "Off",
  accepted: "Accepted only",
  all: "All",
};

/**
 * The company's line-classification mode when the snapshot was taken (M7d S5), and whether it has
 * changed since: the actuals it is scored against are read under the current mode. Shared by the
 * Snapshot sheet and the Review tab.
 */
export function classificationText(
  mode: SnapshotOut["classification_mode"],
  current?: string,
): string {
  if (mode === null) return "Line classification: not recorded";
  const text = `Line classification: ${MODE_NAMES[mode]}`;
  return current !== undefined && current !== mode
    ? `${text} · differs from the current setting`
    : text;
}
