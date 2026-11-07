import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { driverEnginesQueryOptions } from "@/api/engines";
import { ApiError } from "@/api/errors";
import { CASES, type ScenarioCase } from "@/api/scenarios";
import { Chart } from "@/components/Chart";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { Scale } from "@/lib/scale";

import { formatSeasonalIndex } from "./driverCells";
import { ENGINE_CHART_COLORS, engineChartOption, engineTableRows } from "./driverEngines";

interface DriverEnginesSheetProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase;
  driver: { code: string; label: string }; // the grid keys the sheet by scenario, case and driver
  scale: Scale;
  onClose: () => void;
}

const CELL = "px-2 py-1 text-right";

/**
 * One driver's engines: its whole history beside the ARIMA, ETS and Blend forecasts, the case's
 * resolved values and the used engine's 90% band; a table of each engine's forecast and holdout
 * error, and the seasonal index of a seasonal driver. Everything shown is the backend's.
 */
export function DriverEnginesSheet({
  ticker,
  scenarioId,
  scenarioCase,
  driver,
  scale,
  onClose,
}: DriverEnginesSheetProps) {
  const {
    data: view,
    isPending,
    error,
  } = useQuery(driverEnginesQueryOptions(ticker, scenarioId, scenarioCase, driver.code));
  const caseLabel = CASES.find((c) => c.value === scenarioCase)?.label ?? scenarioCase;
  const option = useMemo(
    () => (view ? engineChartOption(view, caseLabel, scale) : null),
    [view, caseLabel, scale],
  );
  const rows = view ? engineTableRows(view, scale) : [];

  return (
    <Sheet open onOpenChange={(next) => !next && onClose()}>
      <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>{driver.label} · engines</SheetTitle>
          <SheetDescription>
            {view?.note ?? "Its history beside each engine's forecast."}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-4">
          {isPending && <p className="text-muted-foreground text-sm">Loading engines…</p>}
          {!view && !isPending && (
            <p className="text-destructive text-sm">
              {error instanceof ApiError && error.status === 422 && error.detail
                ? error.detail
                : "Could not load the engines."}
            </p>
          )}
          {view && option && (
            <>
              <Chart
                option={option}
                ariaLabel={`${driver.label}: history and engine forecasts`}
                height={260}
                colors={ENGINE_CHART_COLORS}
              />
              <div className="overflow-x-auto">
                <table aria-label="Engine forecasts" className="num w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="px-2 py-1 text-left font-medium">Engine</th>
                      {view.forecast_labels.map((label) => (
                        <th key={label} className={`${CELL} font-medium`}>
                          {label}
                        </th>
                      ))}
                      <th className={`${CELL} font-medium`}>Holdout error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr
                        key={row.code}
                        className={`border-border border-t ${row.inUse ? "font-semibold" : ""}`}
                      >
                        <th
                          scope="row"
                          className="px-2 py-1 text-left font-[inherit] whitespace-nowrap"
                        >
                          {row.label}
                          {row.inUse && (
                            <span className="text-muted-foreground ml-2 text-[10px] uppercase">
                              In use
                            </span>
                          )}
                        </th>
                        {row.error ? (
                          <td
                            colSpan={view.forecast_labels.length + 1}
                            className="text-muted-foreground px-2 py-1"
                          >
                            {row.error}
                          </td>
                        ) : (
                          <>
                            {row.cells.map((text, i) => (
                              <td key={view.forecast_labels[i]} className={CELL}>
                                {text}
                              </td>
                            ))}
                            <td className={CELL}>{row.holdout}</td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {view.seasonal && (
                <table aria-label="Seasonal index" className="num w-full text-xs">
                  <caption className="text-muted-foreground mb-1 text-left text-xs font-medium">
                    Seasonal index
                  </caption>
                  <thead className="text-muted-foreground">
                    <tr>
                      {view.seasonal.map((q) => (
                        <th key={q.fiscal_period} className={`${CELL} font-medium`}>
                          {q.fiscal_period}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-border border-t">
                      {view.seasonal.map((q) => (
                        <td key={q.fiscal_period} className={CELL}>
                          {formatSeasonalIndex(q.value, view.unit, scale)}
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
