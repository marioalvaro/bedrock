import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import { companiesQueryOptions } from "@/api/companies";
import type { CompanyListItem, CompanySummaryOut } from "@/api/generated/types.gen";
import { summaryQueryOptions } from "@/api/summary";
import { Chart } from "@/components/Chart";
import {
  formatCompact,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatRatio,
  type RatioUnit,
} from "@/lib/format";

const TICKERS_PARAM = "t";
const MIN_COMPARED = 2;
const MAX_COMPARED = 6;
const DEFAULT_METRIC = "revenue";
const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const HEAD = "px-2 py-1 text-right font-medium whitespace-nowrap";
const ROW_HEAD = "px-2 py-1 text-left font-normal whitespace-nowrap";
const CELL = "num px-2 py-1 text-right whitespace-nowrap";
const LOADING = "…";

interface SummaryResults {
  summaries: (CompanySummaryOut | undefined)[];
  failed: boolean[];
}

// A module-level `combine`: TanStack re-runs it only when a result changes, so its value is
// stable across renders and can key the memos below.
function combineSummaries(results: UseQueryResult<CompanySummaryOut>[]): SummaryResults {
  return {
    summaries: results.map((result) => result.data),
    failed: results.map((result) => result.isError),
  };
}

/** The `?t=` tickers: upper-cased, distinct, in the order given. */
function askedTickers(params: URLSearchParams): string[] {
  const asked = (params.get(TICKERS_PARAM) ?? "").split(",").map((t) => t.trim().toUpperCase());
  return [...new Set(asked.filter((ticker) => ticker !== ""))];
}

// The home list's key stats, formatted as the home list formats them.
const KEY_STATS: { label: string; text: (company: CompanyListItem) => string }[] = [
  { label: "Price", text: (c) => formatPrice(c.price) },
  { label: "Market cap", text: (c) => formatCompact(c.market_cap) },
  { label: "P/E", text: (c) => formatMultiple(c.pe) },
  { label: "EV/EBITDA", text: (c) => formatMultiple(c.ev_ebitda) },
  { label: "Revenue growth", text: (c) => formatPercent(c.revenue_growth) },
];

interface MetricChoice {
  code: string;
  label: string;
  unit: RatioUnit;
}

// The summary metrics in the API's fixed order, from the first summary that has each.
function metricChoices(summaries: (CompanySummaryOut | undefined)[]): MetricChoice[] {
  const byCode = new Map<string, MetricChoice>();
  for (const summary of summaries) {
    for (const metric of summary?.metrics ?? []) {
      if (!byCode.has(metric.code)) {
        byCode.set(metric.code, {
          code: metric.code,
          label: metric.label,
          unit: metric.unit as RatioUnit,
        });
      }
    }
  }
  return [...byCode.values()];
}

// One line per ticker over the union of fiscal years, labeled "FY<year>" (each company's own
// fiscal year: they are not calendar-aligned).
function metricOption(
  metric: MetricChoice,
  tickers: string[],
  summaries: (CompanySummaryOut | undefined)[],
): EChartsOption {
  const yearsOf = (summary: CompanySummaryOut | undefined) =>
    summary?.metrics.find((m) => m.code === metric.code)?.years ?? [];
  const years = [...new Set(summaries.flatMap((s) => yearsOf(s).map((y) => y.fiscal_year)))].sort(
    (a, b) => a - b,
  );
  const format = (value: number) => formatRatio(String(value), metric.unit);
  return {
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => (typeof value === "number" ? format(value) : "—"),
    },
    legend: { top: 0 },
    grid: { left: 16, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: years.map((year) => `FY${year}`) },
    yAxis: { type: "value", scale: true, axisLabel: { formatter: format } },
    series: tickers.map((ticker, at) => {
      const own = yearsOf(summaries[at]);
      return {
        type: "line" as const,
        name: ticker,
        showSymbol: true,
        connectNulls: false,
        data: years.map((year) => {
          const value = own.find((y) => y.fiscal_year === year)?.value ?? null;
          return value === null ? null : Number(value);
        }),
      };
    }),
  };
}

/**
 * The comparison view (FR-WS-02): two to six followed companies side by side, chosen with chips
 * and kept in `?t=`. The key stats and each summary metric's latest value, then one metric's
 * years per ticker. Every number is the API's.
 */
export function Compare() {
  const [params, setParams] = useSearchParams();
  const { data: companies, isPending, isError } = useQuery(companiesQueryOptions);
  const [picked, setPicked] = useState<string | null>(null);

  const followed = useMemo(() => new Map((companies ?? []).map((c) => [c.ticker, c])), [companies]);
  const tickerParam = params.get(TICKERS_PARAM);
  const tickers = useMemo(
    () =>
      askedTickers(new URLSearchParams(tickerParam ? { [TICKERS_PARAM]: tickerParam } : {}))
        .filter((ticker) => followed.has(ticker))
        .slice(0, MAX_COMPARED),
    [tickerParam, followed],
  );

  const { summaries, failed: failedAt } = useQueries({
    queries: tickers.map((ticker) => ({
      ...summaryQueryOptions(ticker),
      enabled: tickers.length >= MIN_COMPARED,
    })),
    combine: combineSummaries,
  });
  const choices = useMemo(() => metricChoices(summaries), [summaries]);
  const metric =
    choices.find((c) => c.code === picked) ??
    choices.find((c) => c.code === DEFAULT_METRIC) ??
    choices[0];
  const option = useMemo(
    () => (metric ? metricOption(metric, tickers, summaries) : null),
    [metric, tickers, summaries],
  );

  function toggle(ticker: string) {
    setParams(
      (current) => {
        const now = askedTickers(current).filter((t) => followed.has(t));
        const next = now.includes(ticker) ? now.filter((t) => t !== ticker) : [...now, ticker];
        const updated = new URLSearchParams(current);
        if (next.length === 0) updated.delete(TICKERS_PARAM);
        else updated.set(TICKERS_PARAM, next.slice(0, MAX_COMPARED).join(","));
        return updated;
      },
      { replace: true },
    );
  }

  const heading = <h1 className="text-lg font-medium">Compare</h1>;
  if (isPending || isError || !companies || companies.length === 0) {
    return (
      <div className="space-y-4 p-4">
        {heading}
        {isPending ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : isError || !companies ? (
          <p className="text-destructive text-sm">Could not load the companies.</p>
        ) : (
          <p className="text-muted-foreground text-sm">
            No companies yet. Add some on the Companies page.
          </p>
        )}
      </div>
    );
  }

  const failed = tickers.filter((_, at) => failedAt[at]);
  // Every summary has loaded or failed: only then is "nothing to chart" known.
  const settled = tickers.every((_, at) => summaries[at] !== undefined || failedAt[at]);
  const latestText = (at: number, choice: MetricChoice) => {
    const summary = summaries[at];
    if (!summary) return failedAt[at] ? "—" : LOADING;
    const found = summary.metrics.find((m) => m.code === choice.code);
    return formatRatio(found?.latest ?? null, choice.unit);
  };

  return (
    <div className="space-y-4 p-4">
      {heading}
      <div role="group" aria-label="Companies to compare" className="flex flex-wrap gap-1.5">
        {companies.map((company) => {
          const pressed = tickers.includes(company.ticker);
          return (
            <button
              key={company.ticker}
              type="button"
              aria-pressed={pressed}
              title={company.name}
              disabled={!pressed && tickers.length >= MAX_COMPARED}
              onClick={() => toggle(company.ticker)}
              className={`rounded-full border px-2.5 py-0.5 text-sm disabled:opacity-40 ${
                pressed
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {company.ticker}
            </button>
          );
        })}
      </div>
      {tickers.length < MIN_COMPARED ? (
        <p className="text-muted-foreground text-sm">Choose two to six companies to compare.</p>
      ) : (
        <>
          {failed.length > 0 && (
            <ul aria-label="Comparison warnings" className="text-muted-foreground text-sm">
              {failed.map((ticker) => (
                <li key={ticker}>Could not load the summary of {ticker}.</li>
              ))}
            </ul>
          )}
          <div className="overflow-x-auto">
            <table aria-label="Comparison" className="text-sm">
              <thead className="text-muted-foreground">
                <tr>
                  <th className={HEAD} />
                  {tickers.map((ticker) => (
                    <th key={ticker} scope="col" className={HEAD}>
                      {ticker}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {KEY_STATS.map(({ label, text }) => (
                  <tr key={label} className="border-border border-t">
                    <th scope="row" className={ROW_HEAD}>
                      {label}
                    </th>
                    {tickers.map((ticker) => (
                      <td key={ticker} className={CELL}>
                        {text(followed.get(ticker)!)}
                      </td>
                    ))}
                  </tr>
                ))}
                {choices.map((choice) => (
                  <tr key={choice.code} className="border-border border-t">
                    <th scope="row" className={ROW_HEAD}>
                      {choice.label}
                    </th>
                    {tickers.map((ticker, at) => (
                      <td key={ticker} className={CELL}>
                        {latestText(at, choice)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {metric && option ? (
            <section aria-label="Metric by fiscal year" className="space-y-1">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Metric</span>
                <select
                  aria-label="Chart metric"
                  className={SELECT}
                  value={metric.code}
                  onChange={(e) => setPicked(e.target.value)}
                >
                  {choices.map((choice) => (
                    <option key={choice.code} value={choice.code}>
                      {choice.label}
                    </option>
                  ))}
                </select>
              </div>
              <Chart option={option} ariaLabel={`${metric.label} by fiscal year`} />
              <p className="text-muted-foreground text-xs">
                Fiscal years as each company reports them.
              </p>
            </section>
          ) : (
            settled && <p className="text-muted-foreground text-sm">No data to chart.</p>
          )}
        </>
      )}
    </div>
  );
}
