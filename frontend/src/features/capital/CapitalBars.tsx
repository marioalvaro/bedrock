import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import type { CapitalAllocationOut } from "@/api/generated/types.gen";
import { Chart } from "@/components/Chart";
import { formatValue } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

// The uses of cash, stacked (outflows are negative as the API returns them), then CFO as a line.
const BARS = ["capex", "acquisitions", "buybacks", "dividends_paid"];
const LINE = "cfo";

function barsOption(data: CapitalAllocationOut, scale: Scale): EChartsOption | null {
  const byCode = new Map(data.rows.map((row) => [row.code, row]));
  const numbers = (values: (string | null)[]) =>
    values.map((value) => (value === null ? null : Number(value)));
  const bars = BARS.flatMap((code) => byCode.get(code) ?? []);
  const line = byCode.get(LINE);
  const charted = line ? [...bars, line] : bars;
  if (!charted.some((row) => row.values.some((value) => value !== null))) return null;

  const format = (value: number) => formatValue(String(value), "USD", scale);
  return {
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => (typeof value === "number" ? format(value) : "—"),
    },
    legend: { top: 0 },
    grid: { left: 16, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: data.periods.map((period) => period.label) },
    yAxis: { type: "value", axisLabel: { formatter: format } },
    series: [
      ...bars.map((row) => ({
        type: "bar" as const,
        name: row.label,
        stack: "uses",
        barMaxWidth: 40,
        data: numbers(row.values),
      })),
      ...(line
        ? [
            {
              type: "line" as const,
              name: line.label,
              showSymbol: true,
              data: numbers(line.values),
            },
          ]
        : []),
    ],
  };
}

/** Capital-allocation bars (FR-WS-03): the uses of cash per period, stacked, against CFO. */
export function CapitalBars({ data }: { data: CapitalAllocationOut }) {
  const scale = useScale();
  const option = useMemo(() => barsOption(data, scale), [data, scale]);

  return (
    <section aria-label="Capital allocation chart" className="px-2 py-2">
      {option ? (
        <Chart option={option} ariaLabel="Capital allocation by period" />
      ) : (
        <p className="text-muted-foreground px-2 text-sm">No data to chart.</p>
      )}
    </section>
  );
}
