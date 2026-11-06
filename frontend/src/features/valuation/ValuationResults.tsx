import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import type {
  DcfOut,
  DcfPeriodOut,
  ValuationOut,
  ValuationResultOut,
} from "@/api/generated/types.gen";
import type { ScenarioCase } from "@/api/scenarios";
import { ValuationUnavailable, valuationQueryOptions } from "@/api/valuation";
import { Button } from "@/components/ui/button";
import { CASE_PARAM, SCENARIO_PARAM } from "@/features/scenarios/useScenarioParam";
import { formatValue, scaleLabel } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";
import { cn } from "@/lib/utils";

import {
  discountText,
  formatPerShare,
  formatTimes,
  formatUpside,
  midYearText,
  periodLabel,
  sourceText,
  terminalTexts,
  upsideClass,
} from "./valuationFormat";

// A valuation the user can unblock by setting drivers in the Scenarios tab.
const MISSING_DRIVERS = "Set these drivers";
const DCF_KEY = "dcf_fcff";

const usd = (value: string | null, scale: Scale) => formatValue(value, "USD", scale);
const label = (result: ValuationResultOut) => (result.caveat ? `${result.label} †` : result.label);
const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

const PERIOD_ROWS: {
  name: string;
  text: (period: DcfPeriodOut, scale: Scale) => string;
  bold?: boolean;
}[] = [
  { name: "NOPAT", text: (p, s) => usd(p.nopat, s) },
  { name: "D&A", text: (p, s) => usd(p.d_and_a, s) },
  { name: "Change in working capital", text: (p, s) => usd(p.change_working_capital, s) },
  { name: "Capex", text: (p, s) => usd(p.capex, s) },
  { name: "FCFF", text: (p, s) => usd(p.fcff, s), bold: true },
  { name: "Discount years", text: (p) => Number(p.years).toFixed(2) },
  { name: "Discount factor", text: (p) => Number(p.discount_factor).toFixed(4) },
  { name: "Present value", text: (p, s) => usd(p.present_value, s) },
];

const CELL = "num px-3 py-1 text-right";
const ROW_HEADER = "px-3 py-1 text-left font-normal";

function CashFlows({ details, scale }: { details: DcfOut; scale: Scale }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label="Cash flows" className="text-sm">
        <thead>
          <tr className="border-border border-b">
            <th scope="col" className="text-muted-foreground px-3 py-1 text-left font-normal">
              {scaleLabel("USD", scale)}
            </th>
            {details.periods.map((period) => (
              <th
                key={period.period_key}
                scope="col"
                className="cell-forecast px-3 py-1 text-right font-normal"
              >
                {periodLabel(period)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {PERIOD_ROWS.map((row) => (
            <tr
              key={row.name}
              className={cn("border-border border-b", row.bold && "font-semibold")}
            >
              <th scope="row" className={cn(ROW_HEADER, row.bold && "font-semibold")}>
                {row.name}
              </th>
              {details.periods.map((period) => (
                <td key={period.period_key} className={CELL}>
                  {row.text(period, scale)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Terminal({ details, scale }: { details: DcfOut; scale: Scale }) {
  const texts = terminalTexts(details);
  return (
    <section aria-label="Terminal value" className="space-y-0.5 text-sm">
      <p>
        {texts.method} · Terminal value {usd(details.terminal.value, scale)} · Present value{" "}
        {usd(details.terminal.present_value, scale)}
      </p>
      {texts.implied && <p className="text-muted-foreground">{texts.implied}</p>}
      {texts.share && <p className="text-muted-foreground">{texts.share}</p>}
    </section>
  );
}

function Bridge({
  view,
  dcf,
  scale,
}: {
  view: ValuationOut;
  dcf: ValuationResultOut;
  scale: Scale;
}) {
  const { bridge } = view;
  const rows: [string, string, string?][] = [
    ["Enterprise value", usd(dcf.enterprise_value, scale)],
    ["− Debt", usd(bridge.total_debt, scale)],
    ["+ Cash", usd(bridge.cash, scale)],
    ["+ Short-term investments", usd(bridge.short_term_investments, scale)],
    ["− Minority interest", usd(bridge.minority_interest, scale)],
    ["− Temporary equity", usd(bridge.temporary_equity, scale)],
    ["= Equity value", usd(dcf.equity_value, scale)],
    ["÷ Shares", formatValue(view.shares, "shares", scale)],
    ["= Value per share", formatPerShare(dcf.value_per_share)],
    ["Upside vs price", formatUpside(dcf.upside), upsideClass(dcf.upside)],
  ];
  return (
    <table aria-label="Bridge" className="text-sm">
      <tbody>
        {rows.map(([name, text, color]) => (
          <tr key={name} className="border-border border-b">
            <th scope="row" className={ROW_HEADER}>
              {name}
            </th>
            <td className={cn(CELL, color)}>{text}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Dcf({ view, scale }: { view: ValuationOut; scale: Scale }) {
  const dcf = view.results.find((result) => result.key === DCF_KEY);
  if (!dcf) return null;
  return (
    <section aria-label="DCF" className="space-y-2">
      <h3 className="text-sm font-medium">{label(dcf)}</h3>
      {dcf.error || !dcf.dcf ? (
        <p className="text-destructive text-sm">{dcf.error ?? "No DCF result."}</p>
      ) : (
        <>
          <p className="text-sm">{discountText(dcf.dcf.discount)}</p>
          <p className="text-muted-foreground text-xs">{midYearText(dcf.dcf.mid_year)}</p>
          <CashFlows details={dcf.dcf} scale={scale} />
          <Terminal details={dcf.dcf} scale={scale} />
          <Bridge view={view} dcf={dcf} scale={scale} />
        </>
      )}
    </section>
  );
}

function Multiples({ view, scale }: { view: ValuationOut; scale: Scale }) {
  const targets = view.results.filter((result) => result.key !== DCF_KEY);
  return (
    <section aria-label="Multiples" className="space-y-2">
      <h3 className="text-sm font-medium">Multiples</h3>
      {targets.length === 0 ? (
        <p className="text-muted-foreground text-sm">No multiple target is on.</p>
      ) : (
        <>
          <table aria-label="Multiple targets" className="text-sm">
            <thead>
              <tr className="border-border text-muted-foreground border-b">
                {[
                  "Target",
                  "Year",
                  scaleLabel("USD", scale),
                  "Multiple",
                  "Value per share",
                  "Upside",
                ].map((name) => (
                  <th key={name} scope="col" className="px-3 py-1 text-left font-normal">
                    {name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {targets.map((result) => (
                <tr key={result.key} className="border-border border-b">
                  <th scope="row" className={ROW_HEADER}>
                    {label(result)}
                  </th>
                  {result.error || !result.multiple ? (
                    <td colSpan={5} className="text-muted-foreground px-3 py-1">
                      {result.error}
                    </td>
                  ) : (
                    <>
                      <td className="px-3 py-1">{result.multiple.period_label}</td>
                      <td className={CELL}>
                        <span title={capitalized(result.multiple.metric_label)}>
                          {usd(result.multiple.metric_value, scale)}
                        </span>
                      </td>
                      <td className="px-3 py-1">
                        <div className="num">{formatTimes(result.multiple.multiple)}</div>
                        <div className="text-muted-foreground text-xs">
                          {sourceText(result.multiple)}
                        </div>
                      </td>
                      <td className={CELL}>{formatPerShare(result.value_per_share)}</td>
                      <td className={cn(CELL, upsideClass(result.upside))}>
                        {formatUpside(result.upside)}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-muted-foreground text-xs">
            Own-history and peer multiples are trailing multiples applied to a forecast year.
          </p>
        </>
      )}
    </section>
  );
}

interface ValuationResultsProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase;
}

/** The picked case's DCF (discount, cash flows, terminal value, bridge) and multiple targets. */
export function ValuationResults({ ticker, scenarioId, scenarioCase }: ValuationResultsProps) {
  const scale = useScale();
  const { data, isPending, error } = useQuery(
    valuationQueryOptions(ticker, scenarioId, scenarioCase),
  );

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (!data) {
    if (error instanceof ValuationUnavailable && error.detail) {
      const params = new URLSearchParams({
        [SCENARIO_PARAM]: String(scenarioId),
        [CASE_PARAM]: scenarioCase,
      });
      return (
        <div className="space-y-2 p-4 text-sm">
          <p>{error.detail}</p>
          {error.detail.startsWith(MISSING_DRIVERS) && (
            <Button asChild size="sm" variant="outline">
              <Link to={`/c/${ticker}/scenarios?${params}`}>Open Scenarios</Link>
            </Button>
          )}
        </div>
      );
    }
    return <p className="text-destructive p-4 text-sm">Could not load the valuation.</p>;
  }

  const caveats = data.results.filter((result) => result.caveat);
  return (
    <section aria-label="Results" className="space-y-4 px-4 py-3">
      <Dcf view={data} scale={scale} />
      <Multiples view={data} scale={scale} />
      {caveats.map((result) => (
        <p key={result.key} className="text-muted-foreground text-xs">
          † {result.caveat}
        </p>
      ))}
      {data.warnings.map((warning) => (
        <p key={warning} className="text-muted-foreground text-sm">
          {warning}
        </p>
      ))}
    </section>
  );
}
