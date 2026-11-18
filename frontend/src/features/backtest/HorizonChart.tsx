import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import type { ScoreRowOut } from "@/api/generated/types.gen";
import { Chart } from "@/components/Chart";

import { formatStat, methodLabel } from "./backtestFormat";

const FREQS: { freq: ScoreRowOut["freq"]; label: string }[] = [
  { freq: "annual", label: "Annual" },
  { freq: "quarterly", label: "Quarterly" },
];

interface HorizonChartProps {
  /** Snapshot scores (`SnapshotListOut.summary`): there, `method` is the scenario case. */
  summary: ScoreRowOut[];
  code: string;
}

interface Bar {
  value: number | null;
  n: number | null;
}

interface TooltipParams {
  seriesName?: string;
  name?: string;
  data?: Bar;
}

// The base case's rows of the line (else the first case scored), with a MAPE.
function caseRows(summary: ScoreRowOut[], code: string) {
  const rows = summary.filter((row) => row.code === code && row.mape !== null);
  const method = rows.some((row) => row.method === "base") ? "base" : rows[0]?.method;
  return { method, rows: rows.filter((row) => row.method === method) };
}

function horizonOption(rows: ScoreRowOut[]): EChartsOption {
  const horizons = [...new Set(rows.map((row) => row.horizon))].sort((a, b) => a - b);
  const percent = (value: number) => formatStat("mape", String(value));
  const series = FREQS.flatMap(({ freq, label }) => {
    const inFreq = rows.filter((row) => row.freq === freq);
    if (inFreq.length === 0) return [];
    const data: Bar[] = horizons.map((horizon) => {
      const row = inFreq.find((r) => r.horizon === horizon);
      return row ? { value: Number(row.mape), n: row.n } : { value: null, n: null };
    });
    return [{ type: "bar" as const, name: label, barMaxWidth: 32, data }];
  });
  return {
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const { seriesName, name, data } = params as TooltipParams;
        if (!data || data.value === null) return "";
        return `${seriesName}, horizon ${name}<br/>MAPE ${percent(data.value)} · n = ${data.n}`;
      },
    },
    legend: { top: 0 },
    grid: { left: 16, right: 16, top: 32, bottom: 32, containLabel: true },
    xAxis: {
      type: "category",
      name: "Years or quarters ahead",
      nameLocation: "middle",
      nameGap: 28,
      data: horizons.map(String),
    },
    yAxis: { type: "value", axisLabel: { formatter: percent } },
    series,
  };
}

/**
 * Backtest error by horizon (FR-WS-03): the snapshots' MAPE of one line for the base case (else
 * the first case scored), annual and quarterly bars, `n` in the tooltip. The scores are the API's.
 */
export function HorizonChart({ summary, code }: HorizonChartProps) {
  const { method, rows } = useMemo(() => caseRows(summary, code), [summary, code]);
  const option = useMemo(() => (rows.length > 0 ? horizonOption(rows) : null), [rows]);

  return (
    <section aria-label="Error by horizon">
      {option && method ? (
        <Chart
          option={option}
          ariaLabel={`${rows[0]!.label}: MAPE by horizon, ${methodLabel(method)} case`}
          height={240}
        />
      ) : (
        <p className="text-muted-foreground text-sm">No data to chart.</p>
      )}
    </section>
  );
}
