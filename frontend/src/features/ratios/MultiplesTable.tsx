import { useQuery } from "@tanstack/react-query";

import { multiplesQueryOptions } from "@/api/analysis";
import type { Basis } from "@/api/statements";
import { formatRatio, type RatioUnit } from "@/lib/format";

function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10 > 3 ? 0 : n % 10]}`;
}

interface MultiplesTableProps {
  ticker: string;
  basis: Basis;
}

/**
 * The valuation block of the Ratios tab: each multiple's current value (latest close, TTM
 * figures) against the range of its own annual history, with the percentile of the current value.
 * Formatting only; see erd/analysis.md "Valuation ratios (M2, S9)".
 */
export function MultiplesTable({ ticker, basis }: MultiplesTableProps) {
  const { data, isPending, isError } = useQuery(multiplesQueryOptions(ticker, basis));

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (isError) {
    return <p className="text-destructive p-4 text-sm">Could not load the valuation multiples.</p>;
  }

  const notes = data.rows.filter((row) => row.caveat !== null);
  return (
    <section aria-label="Valuation multiples" className="border-border border-b px-4 py-3">
      <h3 className="text-sm font-medium">Valuation</h3>
      <p className="text-muted-foreground mb-2 text-xs">
        {data.price === null
          ? "No price stored for this company, so the multiples are empty."
          : `Price ${formatRatio(data.price, "USD/shares")} on ${data.price_date}; own annual history.`}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground text-xs">
              <th className="py-1 text-left font-normal">Multiple</th>
              {["Current", "Min", "Median", "Max", "Percentile"].map((heading) => (
                <th key={heading} className="num px-2 py-1 text-right font-normal">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => {
              const unit = row.unit as RatioUnit;
              const percent =
                row.percentile === null ? null : Math.round(Number(row.percentile) * 100);
              return (
                <tr key={row.code} className="border-border border-t">
                  <td className="py-1">{row.caveat === null ? row.label : `${row.label} †`}</td>
                  {[row.current, row.min, row.median, row.max].map((value, i) => (
                    <td key={i} className="num px-2 py-1 text-right">
                      {formatRatio(value, unit)}
                    </td>
                  ))}
                  <td className="num px-2 py-1 text-right">
                    {percent !== null ? (
                      <span className="inline-flex items-center justify-end gap-2">
                        <span
                          role="meter"
                          aria-label={`${row.label} percentile`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={percent}
                          className="bg-muted relative inline-block h-1.5 w-16 rounded"
                        >
                          <span
                            className="bg-primary absolute inset-y-0 left-0 rounded"
                            style={{ width: `${percent}%` }}
                          />
                        </span>
                        {ordinal(percent)}
                      </span>
                    ) : row.n < 3 ? (
                      `${row.n} yrs`
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {notes.map((row) => (
        <p key={row.code} className="text-muted-foreground mt-1 text-xs">
          † {row.label}: {row.caveat}
        </p>
      ))}
    </section>
  );
}
