import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import type { RatiosOut } from "@/api/generated/types.gen";
import { Chart } from "@/components/Chart";
import { formatRatio, type RatioUnit } from "@/lib/format";

const UNIT_NAMES: Record<RatioUnit, string> = {
  pct: "percent",
  x: "multiple",
  days: "days",
  "USD/shares": "USD per share",
  USD: "USD",
};

interface RatioTrendChartProps {
  payload: RatiosOut;
  /** The chosen ratio codes (the `?chart=` list), in the order they were picked. */
  codes: string[];
}

interface UnitChart {
  unit: RatioUnit;
  option: EChartsOption;
}

// One line chart per unit present among the chosen rows (their order of first appearance), each
// row's API values as they are: the axis and tooltip format them, nothing is computed.
function unitCharts(payload: RatiosOut, codes: string[]): UnitChart[] {
  const rows = codes.flatMap((code) => payload.rows.filter((row) => row.code === code));
  const units = [...new Set(rows.map((row) => row.unit))];
  const labels = payload.periods.map((period) => period.label);
  return units
    .map((unit) => ({ unit, rows: rows.filter((row) => row.unit === unit) }))
    .filter(({ rows: inUnit }) => inUnit.some((row) => row.values.some((v) => v !== null)))
    .map(({ unit, rows: inUnit }) => {
      const format = (value: number) => formatRatio(String(value), unit);
      return {
        unit,
        option: {
          tooltip: {
            trigger: "axis",
            valueFormatter: (value) => (typeof value === "number" ? format(value) : "—"),
          },
          legend: { top: 0 },
          grid: { left: 16, right: 16, top: 32, bottom: 8, containLabel: true },
          xAxis: { type: "category", data: labels },
          yAxis: { type: "value", scale: true, axisLabel: { formatter: format } },
          series: inUnit.map((row) => ({
            type: "line",
            name: row.label,
            showSymbol: true,
            connectNulls: false,
            data: row.values.map((value) => (value === null ? null : Number(value))),
          })),
        } satisfies EChartsOption,
      };
    });
}

/** Ratio trend lines (FR-WS-03): the chosen ratios over the table's periods, one chart per unit. */
export function RatioTrendChart({ payload, codes }: RatioTrendChartProps) {
  const charts = useMemo(() => unitCharts(payload, codes), [payload, codes]);

  if (codes.length === 0) return null;
  if (charts.length === 0) {
    return <p className="text-muted-foreground px-4 py-2 text-sm">No data to chart.</p>;
  }
  return (
    <section aria-label="Ratio trends" className="space-y-2 px-2 py-2">
      {charts.map(({ unit, option }) => (
        <Chart
          key={unit}
          option={option}
          ariaLabel={`Ratio trends, ${UNIT_NAMES[unit]}`}
          height={220}
        />
      ))}
    </section>
  );
}
