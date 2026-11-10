import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useSearchParams } from "react-router";

import { backtestQueryOptions, useRunBacktest } from "@/api/accountability";
import { companyErrorMessage } from "@/api/companies";
import { Chart } from "@/components/Chart";
import { Button } from "@/components/ui/button";
import { useNow } from "@/lib/now";

import { ScoreControls, ScoreTable } from "./ScoreTable";
import {
  METHOD_CHART_COLORS,
  STATS,
  askedSelection,
  backtestStatus,
  failedRuns,
  horizonChartOption,
  resolveSelection,
} from "./backtestFormat";

interface BacktestPanelProps {
  ticker: string;
}

/**
 * The point-in-time backtest: how far each engine's forecasts from past 10-K dates landed from
 * the actuals, by metric and horizon. Run on request; the page only formats the backend's scores.
 */
export function BacktestPanel({ ticker }: BacktestPanelProps) {
  const { data: view, isPending } = useQuery(backtestQueryOptions(ticker));
  const run = useRunBacktest(ticker);
  const now = useNow();
  const [params] = useSearchParams();

  const summary = view?.summary;
  const { metric, freq, stat } = askedSelection(params);
  const selection = useMemo(
    () => (summary ? resolveSelection(summary, { metric, freq, stat }) : null),
    [summary, metric, freq, stat],
  );
  const option = useMemo(
    () => (summary && selection ? horizonChartOption(summary, selection) : null),
    [summary, selection],
  );

  if (!view) {
    return isPending ? (
      <p className="text-muted-foreground p-4 text-sm">Loading…</p>
    ) : (
      <p className="text-destructive p-4 text-sm">Could not load the backtest.</p>
    );
  }

  const button = (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={run.isPending}
      title="Takes about 15 seconds"
      onClick={() => run.mutate()}
    >
      {run.isPending ? "Running…" : "Run backtest"}
    </Button>
  );
  const failure = run.isError && (
    <p role="alert" className="text-destructive text-sm">
      {companyErrorMessage(run.error, "Could not run the backtest.")}
    </p>
  );

  if (view.ran_at === null) {
    return (
      <div className="space-y-2 p-4">
        <p className="text-sm">No backtest yet</p>
        {button}
        {failure}
      </div>
    );
  }

  const failed = failedRuns(view);
  const statLabel = STATS.find(({ value }) => value === selection?.stat)?.label;
  const hasRows = view.summary.some(
    (row) => row.code === selection?.code && row.freq === selection?.freq,
  );

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        {selection && <ScoreControls summary={view.summary} selection={selection} />}
        <div className="ml-auto">{button}</div>
      </div>
      <div className="space-y-4 p-4">
        {failure}
        <p className="text-muted-foreground text-sm">
          <span>{backtestStatus(view, now)}</span>
          {view.stale && <span className="ml-2">A newer 10-K is filed: run again</span>}
        </p>
        {!selection && <p className="text-muted-foreground text-sm">Nothing could be scored.</p>}
        {selection && option && (
          <>
            {hasRows && (
              <Chart
                option={option}
                ariaLabel={`${selection.label}: ${statLabel} by horizon`}
                height={260}
                colors={METHOD_CHART_COLORS}
              />
            )}
            <ScoreTable summary={view.summary} selection={selection} />
          </>
        )}
        {failed.length > 0 && (
          <details className="text-sm">
            <summary className="text-muted-foreground cursor-pointer">
              Runs that could not run
            </summary>
            <ul className="mt-1 space-y-0.5">
              {failed.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
