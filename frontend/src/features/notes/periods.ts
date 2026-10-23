import { useQuery } from "@tanstack/react-query";

import type { FiscalPeriod } from "@/api/context";
import { statementQueryOptions } from "@/api/statements";

import { PERIODS } from "./constants";

// The fiscal years a company has statements for (newest first) and the periods of each.
export interface PeriodOptions {
  loaded: boolean;
  years: number[];
  periodsOf: (year: number) => FiscalPeriod[];
}

/**
 * The company's real periods, from the annual and quarterly income statement payloads (the
 * statement tabs usually have them cached). A year offers FY if it has an annual column and
 * each quarter it has; forecast and TTM columns are not periods a note can link to.
 */
export function usePeriodOptions(ticker: string): PeriodOptions {
  const annual = useQuery(statementQueryOptions(ticker, "IS", "annual"));
  const quarterly = useQuery(statementQueryOptions(ticker, "IS", "quarterly"));
  const byYear = new Map<number, Set<string>>();
  for (const payload of [annual.data, quarterly.data]) {
    for (const period of payload?.periods ?? []) {
      if (period.is_forecast || !PERIODS.includes(period.fiscal_period as FiscalPeriod)) continue;
      byYear.set(
        period.fiscal_year,
        (byYear.get(period.fiscal_year) ?? new Set()).add(period.fiscal_period),
      );
    }
  }
  return {
    loaded: annual.isSuccess && quarterly.isSuccess,
    years: [...byYear.keys()].sort((a, b) => b - a),
    periodsOf: (year) => PERIODS.filter((period) => byYear.get(year)?.has(period)),
  };
}
