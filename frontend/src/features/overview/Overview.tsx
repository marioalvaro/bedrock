import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import type {
  CompanyListItem,
  CompanySummaryOut,
  SummaryFlagOut,
  SummaryForecastOut,
  SummaryMetricOut,
  SummaryNoteOut,
  SummaryValuationOut,
} from "@/api/generated/types.gen";
import { summaryQueryOptions } from "@/api/summary";
import { Sparkline } from "@/components/Sparkline";
import { utcDate } from "@/features/backtest/backtestFormat";
import { ImportButton } from "@/features/imports/ImportButton";
import { formatDay } from "@/features/review/reviewFormat";
import {
  formatChange,
  formatCompact,
  formatFiscalPeriod,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatRatio,
  formatRelative,
  formatSignedPercent,
  type RatioUnit,
} from "@/lib/format";
import { useNow } from "@/lib/now";

function Stat({ name, value }: { name: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{name}</dt>
      <dd className="text-base tabular-nums">{value}</dd>
    </div>
  );
}

const linkClassName = "underline-offset-2 hover:underline";

function Block({ name, children }: { name: string; children: ReactNode }) {
  return (
    <section aria-label={name} className="border-border border-b px-4 py-3">
      <h2 className="mb-2 text-sm font-medium">{name}</h2>
      {children}
    </section>
  );
}

const Empty = ({ text }: { text: string }) => (
  <p className="text-muted-foreground text-sm">{text}</p>
);

const signClassName = (value: string | null) =>
  value === null || Number(value) === 0
    ? undefined
    : Number(value) > 0
      ? "text-positive"
      : "text-negative";

function KeyMetrics({ metrics }: { metrics: SummaryMetricOut[] }) {
  // The columns are every fiscal year any metric has, oldest first (the API sends five at most).
  const fiscalYears = [...new Set(metrics.flatMap((m) => m.years.map((y) => y.fiscal_year)))].sort(
    (a, b) => a - b,
  );
  if (fiscalYears.length === 0) return <Empty text="No annual figures yet." />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted-foreground text-xs">
            <th className="py-1 pr-4 text-left font-normal">Metric</th>
            {fiscalYears.map((year) => (
              <th key={year} className="num py-1 pr-4 font-normal">
                {formatFiscalPeriod(year, "FY")}
              </th>
            ))}
            <th className="py-1 pr-4 font-normal">Trend</th>
            <th className="num py-1 pr-4 font-normal">Latest</th>
            <th className="num py-1 font-normal">YoY</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => {
            const unit = metric.unit as RatioUnit;
            const byYear = new Map(metric.years.map((y) => [y.fiscal_year, y.value]));
            return (
              <tr key={metric.code} className="border-border border-b">
                <th scope="row" className="py-1 pr-4 text-left font-normal whitespace-nowrap">
                  {metric.label}
                </th>
                {fiscalYears.map((year) => (
                  <td key={year} className="num py-1 pr-4">
                    {formatRatio(byYear.get(year) ?? null, unit)}
                  </td>
                ))}
                <td className="py-1 pr-4">
                  <Sparkline
                    values={fiscalYears.map((year) => byYear.get(year) ?? null)}
                    label={`${metric.label} trend`}
                  />
                </td>
                <td className="num py-1 pr-4">{formatRatio(metric.latest, unit)}</td>
                <td className="num py-1">
                  <span className={signClassName(metric.yoy)}>
                    {formatChange(metric.yoy, metric.unit)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const SEVERITY: Record<SummaryFlagOut["severity"], { word: string; className: string }> = {
  alert: { word: "Alert", className: "flag-alert" },
  warn: { word: "Warn", className: "flag-warn" },
};

function OpenFlags({ ticker, flags }: { ticker: string; flags: SummaryFlagOut[] }) {
  return (
    <>
      {flags.length === 0 ? (
        <Empty text="No open flags." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              {flags.map((flag) => (
                <tr key={flag.code} className="border-border border-b">
                  <td className="py-1 pr-4">{flag.label}</td>
                  <td className="py-1 pr-4">
                    <span className={`rounded px-1 ${SEVERITY[flag.severity].className}`}>
                      {SEVERITY[flag.severity].word}
                    </span>
                  </td>
                  <td className="num py-1 pr-4">{formatRatio(flag.value, flag.unit)}</td>
                  <td className="text-muted-foreground py-1">{flag.period_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Link to={`/c/${ticker}/quality`} className={`mt-2 inline-block text-xs ${linkClassName}`}>
        All flags on the Quality tab
      </Link>
    </>
  );
}

function valuationText(v: SummaryValuationOut): string {
  const upside = v.upside === null ? "" : ` (${formatSignedPercent(v.upside)})`;
  return (
    `Value ${formatPrice(v.low)}–${formatPrice(v.high)} per share · ` +
    `base ${formatPrice(v.base)} vs price ${formatPrice(v.price)}${upside}`
  );
}

function Valuation({
  ticker,
  valuation,
}: {
  ticker: string;
  valuation: SummaryValuationOut | null;
}) {
  if (valuation === null) return <Empty text="No default scenario valued yet." />;
  return (
    <Link to={`/c/${ticker}/valuation`} className={`num text-sm ${linkClassName}`}>
      {valuationText(valuation)}
    </Link>
  );
}

function Forecast({ ticker, forecast }: { ticker: string; forecast: SummaryForecastOut | null }) {
  const now = useNow();
  if (forecast === null) return <Empty text="No default scenario yet." />;
  return (
    <div className="text-sm">
      <p>
        {forecast.scenario_name} updated {formatRelative(forecast.updated_at, now)}, last snapshot{" "}
        {formatRelative(forecast.last_snapshot_at, now)}
      </p>
      {forecast.stale && forecast.newest_filing_date && (
        <Link to={`/c/${ticker}/scenarios`} className={`text-flag-warn ${linkClassName}`}>
          Not updated since the {formatDay(forecast.newest_filing_date)} filing.
        </Link>
      )}
    </div>
  );
}

const noteDate = (iso: string) => utcDate(iso).toLocaleDateString("en-US", { dateStyle: "medium" });

function LatestNotes({ ticker, notes }: { ticker: string; notes: SummaryNoteOut[] }) {
  return (
    <>
      {notes.length === 0 ? (
        <Empty text="No notes yet." />
      ) : (
        <ul className="flex flex-col gap-1 text-sm">
          {notes.map((note) => (
            <li key={note.id} className="flex gap-3">
              <span className="text-muted-foreground shrink-0 tabular-nums">
                {noteDate(note.created_at)}
              </span>
              <span>{note.excerpt}</span>
            </li>
          ))}
        </ul>
      )}
      <Link to={`/c/${ticker}/notes`} className={`mt-2 inline-block text-xs ${linkClassName}`}>
        All notes
      </Link>
    </>
  );
}

function Summary({ ticker, summary }: { ticker: string; summary: CompanySummaryOut }) {
  return (
    <>
      {summary.warnings.length > 0 && (
        <ul aria-label="Summary warnings" className="border-border border-b px-4 py-2 text-xs">
          {summary.warnings.map((warning) => (
            <li key={warning} className="text-muted-foreground">
              {warning}
            </li>
          ))}
        </ul>
      )}
      <Block name="Key metrics">
        <KeyMetrics metrics={summary.metrics} />
      </Block>
      <Block name="Open flags">
        <OpenFlags ticker={ticker} flags={summary.flags} />
      </Block>
      <Block name="Valuation">
        <Valuation ticker={ticker} valuation={summary.valuation} />
      </Block>
      <Block name="Forecast">
        <Forecast ticker={ticker} forecast={summary.forecast} />
      </Block>
      <Block name="Latest notes">
        <LatestNotes ticker={ticker} notes={summary.notes} />
      </Block>
    </>
  );
}

/** The Overview (FR-WS-04, erd/workspace.md "Overview summary"): the key stats, then the
 * summary's five blocks; the data panels are on the Data tab. */
export function Overview({ company }: { company: CompanyListItem }) {
  const { data, isPending, isError } = useQuery(summaryQueryOptions(company.ticker));
  return (
    <div>
      <section aria-label="Key stats" className="border-border border-b px-4 py-3">
        <div className="flex items-start justify-between gap-4">
          <dl className="grid flex-1 grid-cols-2 gap-4 sm:grid-cols-5">
            <Stat name="Price" value={formatPrice(company.price)} />
            <Stat name="Market cap" value={formatCompact(company.market_cap)} />
            <Stat name="P/E" value={formatMultiple(company.pe)} />
            <Stat name="EV/EBITDA" value={formatMultiple(company.ev_ebitda)} />
            <Stat name="Revenue growth" value={formatPercent(company.revenue_growth)} />
          </dl>
          <ImportButton ticker={company.ticker} />
        </div>
      </section>
      {isPending && <p className="text-muted-foreground px-4 py-3 text-sm">Loading…</p>}
      {isError && <p className="text-destructive px-4 py-3 text-sm">Could not load the summary.</p>}
      {data && <Summary ticker={company.ticker} summary={data} />}
      <p className="px-4 py-3 text-xs">
        <Link to={`/c/${company.ticker}/data`} className={`text-muted-foreground ${linkClassName}`}>
          Data gaps, adjustments and corporate actions are on the Data tab.
        </Link>
      </p>
    </div>
  );
}
