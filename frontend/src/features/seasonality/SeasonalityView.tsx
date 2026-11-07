import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useSearchParams } from "react-router";

import { ApiError } from "@/api/errors";
import { seasonalityQueryOptions } from "@/api/seasonality";
import { Chart } from "@/components/Chart";
import { UnitToggle } from "@/components/UnitToggle";
import { scaleLabel } from "@/lib/format";
import { useScale } from "@/lib/scale";

import {
  OBSERVED_COLORS,
  QUARTERS,
  RESIDUAL_COLORS,
  SEASONAL_COLORS,
  factorRows,
  formatStrength,
  seasonalityCharts,
} from "./seasonalityFormat";

export const LINE_PARAM = "line";
const DEFAULT_LINE = "revenue";
const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const CELL = "px-2 py-1 text-right";

const is422 = (error: unknown) => error instanceof ApiError && error.status === 422;

interface SeasonalityViewProps {
  ticker: string;
}

/**
 * The Seasonality tab: the STL decomposition of one quarterly IS or CF line (`?line`, default
 * Revenue) as observed and trend, seasonal and residual charts, with its seasonal factors and
 * strength. A line the company cannot decompose (the API's 422 for any line but Revenue) falls
 * back to Revenue. The page computes nothing: it formats the backend's payload.
 */
export function SeasonalityView({ ticker }: SeasonalityViewProps) {
  const scale = useScale();
  const [params, setParams] = useSearchParams();
  const asked = params.get(LINE_PARAM) || DEFAULT_LINE;

  const askedQuery = useQuery(seasonalityQueryOptions(ticker, asked));
  const fallsBack = asked !== DEFAULT_LINE && is422(askedQuery.error);
  const fallbackQuery = useQuery({
    ...seasonalityQueryOptions(ticker, DEFAULT_LINE),
    enabled: fallsBack,
  });
  const { data, isPending, error } = fallsBack ? fallbackQuery : askedQuery;
  const code = fallsBack ? DEFAULT_LINE : asked;

  const charts = useMemo(() => data && seasonalityCharts(data, scale), [data, scale]);
  const rows = useMemo(() => data && factorRows(data, scale), [data, scale]);

  const pick = (next: string) =>
    setParams(
      (current) => {
        const updated = new URLSearchParams(current);
        updated.set(LINE_PARAM, next);
        return updated;
      },
      { replace: true },
    );

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        {data && (
          <select
            aria-label="Line"
            className={SELECT}
            value={code}
            onChange={(e) => pick(e.target.value)}
          >
            {data.lines.map((line) => (
              <option key={line.code} value={line.code}>
                {line.label}
              </option>
            ))}
          </select>
        )}
        <UnitToggle />
      </div>
      {!data && isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {!data && !isPending && (
        <p className="text-destructive p-4 text-sm">
          {error instanceof ApiError && error.status === 422 && error.detail
            ? error.detail
            : "Could not load the seasonality."}
        </p>
      )}
      {data && charts && rows && (
        <div className="space-y-4 p-4">
          <p className="text-muted-foreground text-sm">{formatStrength(data.strength)}</p>
          {(
            [
              ["Observed and trend", "observed and trend", charts.observed, OBSERVED_COLORS],
              ["Seasonal", "seasonal", charts.seasonal, SEASONAL_COLORS],
              ["Residual", "residual", charts.residual, RESIDUAL_COLORS],
            ] as const
          ).map(([title, part, option, colors]) => (
            <section key={part}>
              <h2 className="text-sm font-medium">{title}</h2>
              <Chart
                option={option}
                ariaLabel={`${data.label}: ${part}`}
                height={200}
                colors={colors}
              />
            </section>
          ))}
          <div className="overflow-x-auto">
            <table aria-label="Seasonal factors" className="num text-sm">
              <caption className="mb-1 text-left text-sm font-medium">
                Seasonal factors{" "}
                <span className="text-muted-foreground font-normal">
                  · {scaleLabel(data.unit, scale)}
                </span>
              </caption>
              <thead className="text-muted-foreground">
                <tr>
                  <th className="px-2 py-1" />
                  {QUARTERS.map((q) => (
                    <th key={q} className={`${CELL} font-medium`}>
                      {q}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.label} className="border-border border-t">
                    <th scope="row" className="px-2 py-1 text-left font-medium whitespace-nowrap">
                      {row.label}
                    </th>
                    {row.cells.map((cell, i) => (
                      <td key={QUARTERS[i]} className={CELL}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
