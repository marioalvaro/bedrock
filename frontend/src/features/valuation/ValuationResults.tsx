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
import { formatPercent, formatValue, scaleLabel } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";
import { cn } from "@/lib/utils";

import { CARD } from "./card";
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
  type LabelValue,
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
// The heading of a step inside a method's card.
const SUBHEAD = "text-muted-foreground text-xs font-medium tracking-wide uppercase";
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
  const rows: LabelValue[] = [
    texts.method,
    ["Terminal value", usd(details.terminal.value, scale)],
    ["Present value", usd(details.terminal.present_value, scale)],
    ...(texts.implied ? [texts.implied] : []),
    ...(texts.share ? [texts.share] : []),
  ];
  return (
    <table aria-label="Terminal value" className="text-sm">
      <tbody>
        {rows.map(([name, text]) => (
          <tr key={name} className="border-border border-b">
            <th scope="row" className={ROW_HEADER}>
              {name}
            </th>
            <td className={CELL}>{text}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
  const rows: { name: string; text: string; color?: string; bold?: boolean }[] = [
    { name: "Enterprise value", text: usd(dcf.enterprise_value, scale) },
    { name: "− Debt", text: usd(bridge.total_debt, scale) },
    { name: "+ Cash", text: usd(bridge.cash, scale) },
    { name: "+ Short-term investments", text: usd(bridge.short_term_investments, scale) },
    { name: "− Minority interest", text: usd(bridge.minority_interest, scale) },
    { name: "− Temporary equity", text: usd(bridge.temporary_equity, scale) },
    { name: "= Equity value", text: usd(dcf.equity_value, scale) },
    { name: "÷ Shares", text: formatValue(view.shares, "shares", scale) },
    { name: "= Value per share", text: formatPerShare(dcf.value_per_share), bold: true },
    { name: "Upside vs price", text: formatUpside(dcf.upside), color: upsideClass(dcf.upside) },
  ];
  return (
    <table aria-label="Bridge" className="text-sm">
      <tbody>
        {rows.map(({ name, text, color, bold }) => (
          <tr key={name} className={cn("border-border border-b", bold && "font-semibold")}>
            <th scope="row" className={cn(ROW_HEADER, bold && "font-semibold")}>
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
    <section aria-label="DCF" className={CARD}>
      <h3 className="text-base font-semibold">{label(dcf)}</h3>
      {dcf.error || !dcf.dcf ? (
        <p className="text-destructive text-sm">{dcf.error ?? "No DCF result."}</p>
      ) : (
        <>
          <div className="space-y-1">
            <h4 className={SUBHEAD}>Discount rate</h4>
            <p className="text-sm">{discountText(dcf.dcf.discount)}</p>
            <p className="text-muted-foreground text-xs">{midYearText(dcf.dcf.mid_year)}</p>
          </div>
          <div className="space-y-1">
            <h4 className={SUBHEAD}>Free cash flow to firm</h4>
            <CashFlows details={dcf.dcf} scale={scale} />
          </div>
          {/* The two last steps side by side, each at its own width: terminal value, then EV to
              equity; they wrap on a narrow screen. */}
          <div className="flex flex-wrap items-start gap-x-12 gap-y-4">
            <div className="space-y-1">
              <h4 className={SUBHEAD}>Terminal value</h4>
              <Terminal details={dcf.dcf} scale={scale} />
            </div>
            <div className="space-y-1">
              <h4 className={SUBHEAD}>Equity bridge</h4>
              <Bridge view={view} dcf={dcf} scale={scale} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function Multiples({ view, scale }: { view: ValuationOut; scale: Scale }) {
  const targets = view.results.filter((result) => result.key !== DCF_KEY);
  return (
    <section aria-label="Multiples" className={CARD}>
      <h3 className="text-base font-semibold">Multiples</h3>
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

// What a method's target price rests on: the discount rate, or the multiple and its year.
function basis(result: ValuationResultOut): string | null {
  if (result.dcf) {
    const { method, rate } = result.dcf.discount;
    return `${method === "wacc" ? "WACC" : "Discount rate"} ${formatPercent(rate)}`;
  }
  if (result.multiple) {
    return `${formatTimes(result.multiple.multiple)} ${result.multiple.period_label}`;
  }
  return null;
}

/** A tile per method: its target price (value per share) up front, then its upside vs the price. */
function TargetPrices({ view }: { view: ValuationOut }) {
  return (
    <ul aria-label="Target prices" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {view.results.map((result) => {
        const failed = result.error !== null || result.value_per_share === null;
        const context = basis(result);
        return (
          <li key={result.key} aria-label={result.label} className={cn(CARD, "space-y-1 p-3")}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold">{label(result)}</span>
              {context && !failed && (
                <span className="text-muted-foreground text-xs">{context}</span>
              )}
            </div>
            <div className="text-muted-foreground text-xs">Target price</div>
            {failed ? (
              <>
                <div className="text-muted-foreground text-2xl">—</div>
                <p className="text-muted-foreground text-xs">{result.error}</p>
              </>
            ) : (
              <>
                <div className="text-2xl font-semibold tabular-nums">
                  {formatPerShare(result.value_per_share)}
                </div>
                <p className="text-muted-foreground text-xs">
                  {view.price === null ? (
                    "No price to compare with"
                  ) : (
                    <>
                      <span className={cn("font-medium", upsideClass(result.upside))}>
                        {formatUpside(result.upside)}
                      </span>{" "}
                      vs price {formatPerShare(view.price)}
                    </>
                  )}
                </p>
              </>
            )}
          </li>
        );
      })}
    </ul>
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
    <section aria-label="Results" className="space-y-4">
      <TargetPrices view={data} />
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
