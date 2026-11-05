import type { IntegrityOut, PeriodOut } from "@/api/generated/types.gen";
import { formatValue } from "@/lib/format";
import type { Scale } from "@/lib/scale";

type DiffField = "balance_diff" | "cash_diff" | "re_diff" | "quarters_diff";

const CHECKS: { field: DiffField; label: string }[] = [
  { field: "balance_diff", label: "Balance sheet" },
  { field: "cash_diff", label: "Cash roll-forward" },
  { field: "re_diff", label: "Retained earnings roll-forward" },
  { field: "quarters_diff", label: "Quarters = FY" },
];

// The backend decides whether a period passes (`ok`, within its tolerance). A passing period
// marks every check; in a failing one, a check fails unless its difference is exactly zero.
function fails(check: IntegrityOut, field: DiffField): boolean {
  const diff = check[field];
  return !check.ok && diff !== null && Number(diff) !== 0;
}

interface IntegrityPanelProps {
  integrity: IntegrityOut[];
  periods: PeriodOut[];
  warnings: string[];
  scale: Scale;
}

/**
 * The forecast's integrity checks (FR-FCST-06), one row per forecast period: balance sheet, cash
 * and retained earnings roll-forwards and, for a year built from its quarters, Quarters = FY;
 * each ✓ or its difference in the page scale. Then the engine's warnings.
 */
export function IntegrityPanel({ integrity, periods, warnings, scale }: IntegrityPanelProps) {
  const labels = new Map(periods.map((period) => [period.key, period.label]));
  const shown = CHECKS.filter(
    ({ field }) => field !== "quarters_diff" || integrity.some((c) => c.quarters_diff !== null),
  );
  const failing = integrity.reduce(
    (count, check) => count + shown.filter(({ field }) => fails(check, field)).length,
    0,
  );

  return (
    <section aria-label="Integrity" className="space-y-2 px-4 py-3 text-sm">
      <h2 className="font-medium">Integrity</h2>
      {integrity.length === 0 ? (
        <p className="text-muted-foreground">No forecast periods to check.</p>
      ) : (
        <>
          <p className={failing === 0 ? "text-positive" : "text-negative"}>
            {failing === 0
              ? "All checks pass"
              : `${failing} ${failing === 1 ? "check fails" : "checks fail"}`}
          </p>
          <div className="overflow-x-auto">
            <table className="text-xs">
              <thead>
                <tr className="text-muted-foreground">
                  <th scope="col" className="py-1 pr-4 text-left font-normal">
                    Period
                  </th>
                  {shown.map(({ field, label }) => (
                    <th key={field} scope="col" className="py-1 pr-4 text-right font-normal">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {integrity.map((check) => (
                  <tr key={check.period_key}>
                    <th scope="row" className="py-1 pr-4 text-left font-normal">
                      {labels.get(check.period_key) ?? check.period_key}
                    </th>
                    {shown.map(({ field }) => (
                      <td key={field} className="num py-1 pr-4">
                        {check[field] === null ? (
                          ""
                        ) : fails(check, field) ? (
                          <span className="text-negative">
                            {formatValue(check[field], "USD", scale)}
                          </span>
                        ) : (
                          "✓"
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {warnings.length > 0 && (
        <ul className="text-muted-foreground list-disc pl-5 text-xs">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
