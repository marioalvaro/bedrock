import { useQuery } from "@tanstack/react-query";

import type { CompanyListItem } from "@/api/generated/types.gen";
import { mappingGapsQueryOptions } from "@/api/statements";
import {
  formatCompact,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatValue,
  scaleLabel,
} from "@/lib/format";
import { useScale } from "@/lib/scale";

function Stat({ name, value }: { name: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{name}</dt>
      <dd className="text-base tabular-nums">{value}</dd>
    </div>
  );
}

function DataGaps({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(mappingGapsQueryOptions(ticker));
  const scale = useScale();

  return (
    <section aria-label="Data gaps" className="px-4 py-3">
      <h2 className="mb-2 text-sm font-medium">Data gaps</h2>
      {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && <p className="text-destructive text-sm">Could not load the data gaps.</p>}
      {data && (
        <div className="flex flex-col gap-4">
          <div>
            <h3 className="text-muted-foreground mb-1 text-xs">
              Missing items ({data.missing_items.length})
            </h3>
            {data.missing_items.length === 0 ? (
              <p className="text-sm">No missing items.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <tbody>
                    {data.missing_items.map((item) => (
                      <tr key={item.code} className="border-border border-b align-top">
                        <td className="py-1 pr-4">{item.label}</td>
                        <td className="text-muted-foreground py-1 pr-4">{item.statement}</td>
                        <td className="text-muted-foreground py-1">
                          {item.missing_periods.join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div>
            <h3 className="text-muted-foreground mb-1 text-xs">
              Unmapped concepts in the latest 10-K ({data.unmapped_concepts.length}),{" "}
              {scaleLabel("USD", scale)}
            </h3>
            {data.unmapped_concepts.length === 0 ? (
              <p className="text-sm">No unmapped concepts.</p>
            ) : (
              <div className="max-h-96 overflow-auto">
                <table className="w-full text-sm">
                  <tbody>
                    {data.unmapped_concepts.map((concept) => (
                      <tr
                        key={`${concept.taxonomy}:${concept.concept}:${concept.unit}`}
                        className="border-border border-b"
                      >
                        <td className="py-1 pr-4 whitespace-nowrap">
                          {concept.taxonomy}:{concept.concept}
                        </td>
                        <td className="num py-1 pr-4">
                          {concept.unit === "USD"
                            ? formatValue(concept.latest_value, concept.unit, scale)
                            : concept.latest_value}
                        </td>
                        <td className="text-muted-foreground py-1 pr-4">{concept.unit}</td>
                        <td className="text-muted-foreground py-1 pr-4">
                          {concept.latest_period_end}
                        </td>
                        <td className="num text-muted-foreground py-1">{concept.facts}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export function Overview({ company }: { company: CompanyListItem }) {
  return (
    <div>
      <section aria-label="Key stats" className="border-border border-b px-4 py-3">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Stat name="Price" value={formatPrice(company.price)} />
          <Stat name="Market cap" value={formatCompact(company.market_cap)} />
          <Stat name="P/E" value={formatMultiple(company.pe)} />
          <Stat name="EV/EBITDA" value={formatMultiple(company.ev_ebitda)} />
          <Stat name="Revenue growth" value={formatPercent(company.revenue_growth)} />
        </dl>
      </section>
      <DataGaps ticker={company.ticker} />
    </div>
  );
}
