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

// One line per scenario, x = the forecast periods. A scenario that cannot run keeps an empty
// series, so each scenario keeps its color (colors go by series position).
function chartOption(table: CompareOut, code: string, unit: string, scale: Scale): EChartsOption {
  return {
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    legend: { data: table.scenarios.map((scenario) => scenario.name), top: 0 },
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
    series: table.scenarios.map((scenario) => ({
      type: "line",
      name: scenario.name,
      data: (scenario.values[code] ?? []).map((value) => scaledNumber(value, unit, scale)),
    })),
  };
}

interface ScenarioCompareProps {
  ticker: string;
}

/**
 * Every scenario side by side over the forecast periods: a line chart of one metric and a table
 * of every compared metric. A scenario that cannot run shows its reason instead of values.
 */
export function ScenarioCompare({ ticker }: ScenarioCompareProps) {
  const scale = useScale();
  const [freq, setFreq] = useState<ForecastFreq>("annual");
  const [picked, setPicked] = useState(DEFAULT_METRIC);
  const {
    data: table,
    isPending,
    isError,
  } = useQuery({
    ...compareQueryOptions(ticker, freq),
    placeholderData: keepPreviousData, // the chart stays mounted while the other frequency loads
  });

  const metric =
    table?.codes.find((code) => code.code === picked) ??
    table?.codes.find((code) => code.code === DEFAULT_METRIC) ??
    table?.codes[0];
  const option = useMemo(
    () => (table && metric ? chartOption(table, metric.code, metric.unit, scale) : null),
    [table, metric, scale],
  );

  return (
    <section aria-label="Compare scenarios" className="border-border border-t">
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
          aria-label="Scenarios that cannot run"
          className="text-muted-foreground space-y-0.5 px-4 pb-4 text-sm"
        >
          {table.scenarios.map((scenario) => (
            <li key={scenario.id}>
              {scenario.name}: {scenario.error ?? "no forecast periods"}
            </li>
          ))}
        </ul>
      )}
      {table && table.periods.length > 0 && (
        <>
          {option && metric && (
            <div className="px-4">
              <Chart option={option} ariaLabel={`${metric.label} by scenario`} />
            </div>
          )}
          <div className="overflow-x-auto px-4 pb-4">
            <table aria-label="Scenario comparison" className="w-full text-sm">
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
                    {table.scenarios.map((scenario) => (
                      <tr key={scenario.id}>
                        <td className="py-0.5 pr-3 pl-3 whitespace-nowrap">{scenario.name}</td>
                        {scenario.error !== null ? (
                          <td
                            colSpan={table.periods.length}
                            className="text-muted-foreground py-0.5 pl-3 text-xs"
                          >
                            {scenario.error}
                          </td>
                        ) : (
                          table.periods.map((period, index) => (
                            <td key={period.key} className="num py-0.5 pl-3 text-right">
                              {formatValue(
                                scenario.values[code.code]?.[index] ?? null,
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
