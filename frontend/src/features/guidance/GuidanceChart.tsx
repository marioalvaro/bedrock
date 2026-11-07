import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { guidanceHistoryQueryOptions, guidanceMetricsQueryOptions } from "@/api/context";
import { forecastCompareQueryOptions, scenariosQueryOptions } from "@/api/scenarios";
import type { GuidanceEntryOut } from "@/api/generated/types.gen";
import { Chart } from "@/components/Chart";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useScale } from "@/lib/scale";

import {
  chartMetrics,
  chartPoints,
  defaultChartMetric,
  defaultFreq,
  forecastValues,
  guidanceChart,
  splitKey,
  type GuidanceFreq,
} from "./chartData";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const FREQS: { value: GuidanceFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
];

interface GuidanceChartProps {
  ticker: string;
  entries: GuidanceEntryOut[];
}

/**
 * Actual vs predictions for one metric at a time, annual or quarterly: touching bars of the actual
 * (with the earlier periods from the metric's history), the latest analyst consensus (its range
 * as whiskers), the latest management guidance and, for a statement line, the default scenario's
 * Base forecast. Revisions are left to the log.
 */
export function GuidanceChart({ ticker, entries }: GuidanceChartProps) {
  const scale = useScale();
  const [freq, setFreq] = useState<GuidanceFreq>(() => defaultFreq(entries));
  const [picked, setPicked] = useState<string | undefined>(undefined);

  const metrics = useMemo(() => chartMetrics(entries, freq), [entries, freq]);
  const metric =
    metrics.find((m) => m.key === picked) ??
    metrics.find((m) => m.key === defaultChartMetric(metrics));
  const target = metric ? splitKey(metric.key) : undefined;
  // The earlier actuals; while loading or on an error the guided periods chart alone.
  const history = useQuery({
    ...guidanceHistoryQueryOptions(ticker, target?.metric ?? "", target?.basis ?? "reported", freq),
    enabled: target !== undefined,
  });
  // The user's forecast: the default scenario's Base case, for a statement line only (a scenario
  // forecasts lines, not ratios or KPIs). Without one the chart goes without it.
  const choices = useQuery(guidanceMetricsQueryOptions(ticker));
  const isLine = choices.data?.find((c) => c.metric === target?.metric)?.group === "line";
  const scenarios = useQuery({ ...scenariosQueryOptions(ticker), enabled: isLine });
  const scenarioId = (scenarios.data?.find((s) => s.is_default) ?? scenarios.data?.[0])?.id;
  const forecast = useQuery({
    ...forecastCompareQueryOptions(ticker, scenarioId ?? 0, freq, target?.metric ?? ""),
    enabled: isLine && scenarioId !== undefined,
  });
  const forecastData = isLine && scenarioId !== undefined ? forecast.data : undefined;

  const chart = useMemo(
    () =>
      metric
        ? guidanceChart(
            chartPoints(
              entries,
              metric.key,
              freq,
              history.data?.points,
              forecastValues(forecastData, splitKey(metric.key).metric),
            ),
            metric.unit,
            scale,
          )
        : null,
    [entries, metric, freq, scale, history.data, forecastData],
  );

  return (
    <section aria-label="Actual vs predictions" className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 px-4">
        <h2 className="mr-2 text-sm font-medium">Actual vs predictions</h2>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Chart frequency"
          value={freq}
          onValueChange={(value) => value && setFreq(value as GuidanceFreq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {metric && (
          <span className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Metric</span>
            <select
              aria-label="Chart metric"
              className={SELECT}
              value={metric.key}
              onChange={(e) => setPicked(e.target.value)}
            >
              {metrics.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </span>
        )}
      </div>
      {metric && chart ? (
        <div className="px-2">
          <Chart
            option={chart.option}
            colors={chart.colors}
            ariaLabel={`${metric.label}: actual vs predictions, ${freq}`}
          />
        </div>
      ) : (
        <p className="text-muted-foreground px-4 py-2 text-sm">No {freq} guidance to chart.</p>
      )}
    </section>
  );
}
