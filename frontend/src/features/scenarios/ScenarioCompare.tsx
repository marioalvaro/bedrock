import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { Fragment, useMemo, useState } from "react";

import type { CompareOut } from "@/api/generated/types.gen";
import { compareQueryOptions, type ForecastFreq } from "@/api/scenarios";
import { Chart } from "@/components/Chart";
import { Label } from "@/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { formatChartNumber, formatValue, scaleLabel, scaledNumber } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const DEFAULT_METRIC = "revenue";

const FREQS: { value: ForecastFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
];

type CaseKey = CompareOut["cases"][number]["case"];

// Bull, Base, Bear, each in the color it reads as: green up, blue neutral, red down.
const CASE_STYLE: Record<CaseKey, { color: string; text: string }> = {
  bull: { color: "--positive", text: "text-positive" },
  base: { color: "--chart-1", text: "text-chart-1" },
  bear: { color: "--negative", text: "text-negative" },
};
const CASE_ORDER: CaseKey[] = ["bull", "base", "bear"];
const CASE_COLORS = CASE_ORDER.map((key) => CASE_STYLE[key].color);

function inCaseOrder(table: CompareOut): CompareOut {
  const cases = CASE_ORDER.flatMap((key) => table.cases.filter((item) => item.case === key));
  return { ...table, cases };
}

// One line per case (Bull, Base, Bear), x = the forecast periods. A case that cannot run keeps an
// empty series, so each case keeps its color (colors go by series position).
function chartOption(table: CompareOut, code: string, unit: string, scale: Scale): EChartsOption {
  return {
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    legend: { data: table.cases.map((item) => item.label), top: 0 },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => formatChartNumber(typeof value === "number" ? value : null, unit),
    },
    xAxis: { type: "category", data: table.periods.map((period) => period.label) },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { formatter: (value: number) => formatChartNumber(value, unit) },
    },
    series: table.cases.map((item) => ({
      type: "line",
      name: item.label,
      data: (item.values[code] ?? []).map((value) => scaledNumber(value, unit, scale)),
    })),
  };
}

interface ScenarioCompareProps {
  ticker: string;
  scenarioId: number; // the view keys this component by it, so the previous data is its own
}

/**
 * The scenario's Bull, Base and Bear side by side over the forecast periods: a line chart of one
 * metric and a table of every compared metric. A case that cannot run shows its reason instead of
 * values.
 */
export function ScenarioCompare({ ticker, scenarioId }: ScenarioCompareProps) {
  const scale = useScale();
  const [freq, setFreq] = useState<ForecastFreq>("annual");
  const [picked, setPicked] = useState(DEFAULT_METRIC);
  const {
    data: fetched,
    isPending,
    isError,
  } = useQuery({
    ...compareQueryOptions(ticker, scenarioId, freq),
    placeholderData: keepPreviousData, // the chart stays mounted while the other frequency loads
  });

  const table = useMemo(() => (fetched ? inCaseOrder(fetched) : undefined), [fetched]);
  const metric =
    table?.codes.find((code) => code.code === picked) ??
    table?.codes.find((code) => code.code === DEFAULT_METRIC) ??
    table?.codes[0];
  const option = useMemo(
    () => (table && metric ? chartOption(table, metric.code, metric.unit, scale) : null),
    [table, metric, scale],
  );

  return (
    <section aria-label="Compare cases" className="border-border border-t">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2">
        <h2 className="mr-2 text-sm font-medium">Compare</h2>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Comparison frequency"
          value={freq}
          onValueChange={(value) => value && setFreq(value as ForecastFreq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {table && table.codes.length > 0 && (
          <span className="flex items-center gap-2">
            <Label htmlFor="compare-metric">Metric</Label>
            <select
              id="compare-metric"
              className={SELECT}
              value={metric?.code}
              onChange={(e) => setPicked(e.target.value)}
            >
              {table.codes.map((code) => (
                <option key={code.code} value={code.code}>
                  {code.label}
                </option>
              ))}
            </select>
          </span>
        )}
      </div>
      {isPending && (
        <p className="text-muted-foreground px-4 pb-4 text-sm">Loading the comparison…</p>
      )}
      {isError && (
        <p className="text-destructive px-4 pb-4 text-sm">Could not load the comparison.</p>
      )}
      {table && table.periods.length === 0 && (
        <ul
          aria-label="Cases that cannot run"
          className="text-muted-foreground space-y-0.5 px-4 pb-4 text-sm"
        >
          {table.cases.map((item) => (
            <li key={item.case}>
              {item.label}: {item.error ?? "no forecast periods"}
            </li>
          ))}
        </ul>
      )}
      {table && table.periods.length > 0 && (
        <>
          {option && metric && (
            <div className="px-4">
              <Chart option={option} ariaLabel={`${metric.label} by case`} colors={CASE_COLORS} />
            </div>
          )}
          <div className="overflow-x-auto px-4 pb-4">
            <table aria-label="Case comparison" className="w-full text-sm">
              <thead className="text-muted-foreground text-xs">
                <tr>
                  <th className="py-1 pr-3 text-left font-normal" />
                  {table.periods.map((period) => (
                    <th key={period.key} className="cell-forecast py-1 pl-3 text-right font-normal">
                      {period.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.codes.map((code) => (
                  <Fragment key={code.code}>
                    <tr className="border-border border-t">
                      <th
                        colSpan={table.periods.length + 1}
                        className="py-1 text-left text-xs font-medium"
                      >
                        {code.label} · {scaleLabel(code.unit, scale)}
                      </th>
                    </tr>
                    {table.cases.map((item) => (
                      <tr key={item.case}>
                        <td
                          className={`py-0.5 pr-3 pl-3 whitespace-nowrap ${CASE_STYLE[item.case].text}`}
                        >
                          {item.label}
                        </td>
                        {item.error !== null ? (
                          <td
                            colSpan={table.periods.length}
                            className="text-muted-foreground py-0.5 pl-3 text-xs"
                          >
                            {item.error}
                          </td>
                        ) : (
                          table.periods.map((period, index) => (
                            <td key={period.key} className="num py-0.5 pl-3 text-right">
                              {formatValue(
                                item.values[code.code]?.[index] ?? null,
                                code.unit,
                                scale,
                              )}
                            </td>
                          ))
                        )}
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
