import { useQuery } from "@tanstack/react-query";

import type { SummaryCaseOut } from "@/api/generated/types.gen";
import type { ScenarioCase } from "@/api/scenarios";
import { ValuationUnavailable, valuationSummaryQueryOptions } from "@/api/valuation";
import { cn } from "@/lib/utils";

import { formatPerShare, formatUpside, priceText, upsideClass } from "./valuationFormat";

// The comparison's order and colors (features/scenarios/ScenarioCompare.tsx).
const COLUMNS: { case: ScenarioCase; label: string; text: string }[] = [
  { case: "bull", label: "Bull", text: "text-positive" },
  { case: "base", label: "Base", text: "text-chart-1" },
  { case: "bear", label: "Bear", text: "text-negative" },
];

interface ValuationSummaryProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase;
}

function SummaryCell({ entry, method }: { entry: SummaryCaseOut | undefined; method: string }) {
  const error = entry?.error ?? entry?.errors[method];
  if (error) {
    return <td className="text-muted-foreground px-3 py-1 text-xs">{error}</td>;
  }
  const upside = entry?.upside[method] ?? null;
  return (
    <td className="num px-3 py-1 text-right">
      <div>{formatPerShare(entry?.value_per_share[method] ?? null)}</div>
      <div className={cn("text-xs", upsideClass(upside))}>{formatUpside(upside)}</div>
    </td>
  );
}

/** The scenario's Bull, Base and Bear values per share by method, against the latest close. */
export function ValuationSummary({ ticker, scenarioId, scenarioCase }: ValuationSummaryProps) {
  const { data, isPending, error } = useQuery(valuationSummaryQueryOptions(ticker, scenarioId));

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (!data) {
    return (
      <p className="text-destructive p-4 text-sm">
        {error instanceof ValuationUnavailable && error.detail
          ? error.detail
          : "Could not load the valuation summary."}
      </p>
    );
  }

  const byCase = new Map(data.cases.map((entry) => [entry.case, entry]));
  return (
    <section aria-label="Summary" className="space-y-2 px-4 py-3">
      <p className="text-sm">{priceText(data.price, data.price_date)}</p>
      {data.methods.length === 0 ? (
        // No case ran, so there is no method row: each case's reason instead.
        <ul className="text-muted-foreground text-sm">
          {COLUMNS.map((column) => {
            const reason = byCase.get(column.case)?.error;
            return reason && <li key={column.case}>{`${column.label}: ${reason}`}</li>;
          })}
        </ul>
      ) : (
        <table aria-label="Valuation by case" className="text-sm">
          <thead>
            <tr className="border-border border-b">
              <th scope="col" className="text-muted-foreground px-3 py-1 text-left font-normal">
                Method
              </th>
              {COLUMNS.map((column) => (
                <th
                  key={column.case}
                  scope="col"
                  className={cn(
                    "px-3 py-1 text-right",
                    column.text,
                    column.case === scenarioCase ? "font-bold" : "font-normal",
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.methods.map((method) => (
              <tr key={method.key} className="border-border border-b">
                <th scope="row" className="px-3 py-1 text-left font-normal">
                  {method.label}
                </th>
                {COLUMNS.map((column) => (
                  <SummaryCell
                    key={column.case}
                    entry={byCase.get(column.case)}
                    method={method.key}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
