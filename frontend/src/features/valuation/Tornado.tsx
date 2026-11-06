import type { EChartsOption } from "echarts";
import { useMemo, useState } from "react";

import type { TornadoBarOut, TornadoOut } from "@/api/generated/types.gen";
import { Chart } from "@/components/Chart";
import { Button } from "@/components/ui/button";

import { barLabel, formatChange, formatPerShare, tornadoTooltip } from "./valuationFormat";

const TOP = 10;
// The input's direction in two neutral hues: red and green would read as a fall and a rise in
// value, which a bar's side already shows (module constant: Chart memo).
const COLORS = ["--chart-1", "--chart-2"];
const ROW_HEIGHT = 28;
const CHROME_HEIGHT = 96; // legend, axis, its name and the margins

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
// ECharts renders a tooltip formatter's string as HTML.
const escapeHtml = (text: string) => text.replace(/[&<>"]/g, (c) => ESCAPES[c] ?? c);

// One row per input, the largest range at the top (`inverse`: a category axis starts at the
// bottom). Both bars of a row start at 0 and overlap (`barGap: -100%`), so a bar is never drawn
// on top of the other side's when both move the value the same way.
function chartOption(bars: TornadoBarOut[], baseValue: string): EChartsOption {
  const number = (value: string | null) => (value === null ? null : Number(value));
  return {
    legend: { top: 0, data: ["Input lower", "Input higher"] },
    grid: { left: 8, right: 24, top: 32, bottom: 32, containLabel: true },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const [first] = Array.isArray(params) ? params : [params];
        const bar = first ? bars[first.dataIndex] : undefined;
        return bar ? escapeHtml(tornadoTooltip(bar)) : "";
      },
    },
    xAxis: {
      type: "value",
      name: `Change in value per share vs ${formatPerShare(baseValue)}`,
      nameLocation: "middle",
      nameGap: 24,
      axisLabel: { formatter: (value: number) => formatChange(value) },
    },
    yAxis: { type: "category", inverse: true, data: bars.map(barLabel) },
    series: [
      {
        type: "bar",
        name: "Input lower",
        data: bars.map((bar) => number(bar.low_change)),
        markLine: { silent: true, symbol: "none", label: { show: false }, data: [{ xAxis: 0 }] },
      },
      {
        type: "bar",
        name: "Input higher",
        barGap: "-100%",
        data: bars.map((bar) => number(bar.high_change)),
      },
    ],
  };
}

interface TornadoProps {
  tornado: TornadoOut;
}

/**
 * Which inputs move the DCF value per share most at their unit step: a bar per input, the lower
 * input's change to one side and the higher's to the other. The top 10 by default; inputs that
 * could not run are listed under the chart.
 */
export function Tornado({ tornado }: TornadoProps) {
  const [showAll, setShowAll] = useState(false);
  const ran = useMemo(() => tornado.bars.filter((bar) => bar.error === null), [tornado]);
  const failed = tornado.bars.filter((bar) => bar.error !== null);
  const shown = useMemo(() => (showAll ? ran : ran.slice(0, TOP)), [ran, showAll]);
  const option = useMemo(() => chartOption(shown, tornado.base_value), [shown, tornado.base_value]);

  return (
    <div className="space-y-2">
      {ran.length === 0 ? (
        <p className="text-muted-foreground text-sm">No input could be moved.</p>
      ) : (
        <Chart
          option={option}
          ariaLabel="Tornado: change in DCF value per share by input"
          colors={COLORS}
          height={shown.length * ROW_HEIGHT + CHROME_HEIGHT}
        />
      )}
      {ran.length > TOP && (
        <Button variant="outline" size="sm" onClick={() => setShowAll((all) => !all)}>
          {showAll ? `Show top ${TOP}` : `Show all ${ran.length}`}
        </Button>
      )}
      {failed.length > 0 && (
        <ul aria-label="Inputs that could not run" className="text-muted-foreground text-xs">
          {failed.map((bar) => (
            <li key={bar.code}>
              Could not run: {bar.label}: {bar.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
