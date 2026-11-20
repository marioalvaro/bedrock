import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import { Chart } from "@/components/Chart";

const WIDTH = 80;
const HEIGHT = 20;

/** A trend line with no axes, tooltip or legend (the Overview's key metrics, FR-WS-04). The
 * values are the API's, oldest first; a null is a gap. Nothing is drawn without a value. */
export function Sparkline({ values, label }: { values: (string | null)[]; label: string }) {
  // The values as one string, so a refetch with the same numbers keeps the option (G32).
  const key = values.join("|");
  const option = useMemo<EChartsOption>(() => {
    const data = key.split("|").map((text) => (text === "" ? null : Number(text)));
    // One year is a point, which a line without symbols would not draw.
    const single = data.filter((value) => value !== null).length === 1;
    return {
      grid: { top: 2, bottom: 2, left: 0, right: 0 },
      legend: { show: false },
      xAxis: { type: "category", show: false, data: data.map((_, at) => at) },
      yAxis: { type: "value", show: false, scale: true },
      series: [
        { type: "line", data, connectNulls: false, showSymbol: single, lineStyle: { width: 1.5 } },
      ],
    };
  }, [key]);

  if (!values.some((value) => value !== null)) return null;
  return (
    <div style={{ width: WIDTH }}>
      <Chart option={option} ariaLabel={label} height={HEIGHT} />
    </div>
  );
}
