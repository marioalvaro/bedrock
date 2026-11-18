import type { EChartsOption } from "echarts";
import { useMemo, useState } from "react";

import type { ForecastOut } from "@/api/generated/types.gen";
import { Chart } from "@/components/Chart";
import { formatValue } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const DEFAULT_LINE = "revenue";
// One line in one color, actual then forecast: the dash tells them apart (a module constant:
// `Chart` memoizes on it). The forecast tint is a background token, too pale for a line.
const COLORS = ["--chart-1", "--chart-1"];

type Row = ForecastOut["rows"][number];

function historyOption(data: ForecastOut, row: Row, scale: Scale): EChartsOption {
  const numbers = row.values.map((value) => (value === null ? null : Number(value)));
  const forecast = data.periods.map((period) => period.is_forecast);
  const firstForecast = forecast.indexOf(true);
  const format = (value: number) => formatValue(String(value), row.unit, scale);
  return {
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => (typeof value === "number" ? format(value) : "—"),
    },
    legend: { top: 0 },
    grid: { left: 16, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: data.periods.map((period) => period.label) },
    yAxis: { type: "value", scale: true, axisLabel: { formatter: format } },
    series: [
      {
        type: "line",
        name: "Actual",
        showSymbol: true,
        lineStyle: { type: "solid" },
        data: numbers.map((value, at) => (forecast[at] ? null : value)),
      },
      // From the last actual, so the two lines join; none when no period is a forecast.
      ...(firstForecast === -1
        ? []
        : [
            {
              type: "line" as const,
              name: "Forecast",
              showSymbol: true,
              lineStyle: { type: "dashed" as const },
              data: numbers.map((value, at) =>
                forecast[at] || (firstForecast > 0 && at === firstForecast - 1) ? value : null,
              ),
            },
          ]),
    ],
  };
}

/**
 * Forecast against history (FR-WS-03): one statement line of the forecast payload over its
 * periods, the actuals solid and the forecast periods dashed. Revenue unless another is chosen.
 */
export function ForecastHistoryChart({ data }: { data: ForecastOut }) {
  const scale = useScale();
  const [picked, setPicked] = useState<string | null>(null);

  const lines = useMemo(
    () => data.rows.filter((row) => row.values.some((value) => value !== null)),
    [data],
  );
  const row =
    lines.find((r) => r.code === picked) ?? lines.find((r) => r.code === DEFAULT_LINE) ?? lines[0];
  const option = useMemo(() => (row ? historyOption(data, row, scale) : null), [data, row, scale]);

  return (
    <section aria-label="Forecast against history" className="space-y-1 py-2">
      {row && option ? (
        <>
          <div className="flex items-center gap-2 px-4 text-sm">
            <span className="text-muted-foreground">Line</span>
            <select
              aria-label="Chart line"
              className={SELECT}
              value={row.code}
              onChange={(e) => setPicked(e.target.value)}
            >
              {lines.map((line) => (
                <option key={line.code} value={line.code}>
                  {line.label}
                </option>
              ))}
            </select>
          </div>
          <div className="px-2">
            <Chart
              option={option}
              colors={COLORS}
              ariaLabel={`${row.label}: actuals and forecast`}
              height={240}
            />
          </div>
        </>
      ) : (
        <p className="text-muted-foreground px-4 text-sm">No data to chart.</p>
      )}
    </section>
  );
}
