import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet,
  createScenarioApiV1CompaniesTickerScenariosPost,
  deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete,
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet,
  getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet,
  importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost,
  listScenariosApiV1CompaniesTickerScenariosGet,
  putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut,
  resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost,
  setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut,
  updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut,
} from "@/api/generated/sdk.gen";
import type {
  CompareOut,
  DriverFileIssueOut,
  DriverGridOut,
  DriverImportOut,
  DriverRowIn,
  ForecastOut,
  ScenarioIn,
  ScenarioOut,
  ScenarioSettingsIn,
  YearModeIn,
  YearModesOut,
} from "@/api/generated/types.gen";
import type { StatementType } from "@/api/statements";

export type ScenarioCase = DriverGridOut["case"];
export type ForecastFreq = "annual" | "quarterly";
export type DriverFileFormat = "csv" | "xlsx";

/** The three cases of every scenario, in display order. */
export const CASES: { value: ScenarioCase; label: string }[] = [
  { value: "base", label: "Base" },
  { value: "bull", label: "Bull" },
  { value: "bear", label: "Bear" },
];

// Every scenario query of a company (list, drivers and forecasts per case, compare) sits under
// this key, so one invalidation reaches them all.
export const scenariosKey = (ticker: string) => [...companyKey(ticker), "scenarios"] as const;

const unexpected = () => new ApiError(200, "Unexpected response");

/** GET …/scenarios (the default scenario first). Rejects a 200 whose body is not an array (Gotcha G2). */
export const scenariosQueryOptions = (ticker: string) =>
  queryOptions<ScenarioOut[]>({
    queryKey: scenariosKey(ticker),
    queryFn: async () => {
      const list = await unwrap(
        listScenariosApiV1CompaniesTickerScenariosGet({ path: { ticker } }),
      );
      if (!Array.isArray(list)) throw unexpected();
      return list;
    },
  });

// Every driver grid of a case (both frequencies) sits under this key.
const driversPrefix = (ticker: string, id: number, scenarioCase: ScenarioCase) =>
  [...scenariosKey(ticker), id, scenarioCase, "drivers"] as const;

/**
 * GET …/scenarios/{id}/cases/{case}/drivers?freq=. Rejects a 200 without `rows`, the year lists and
 * the period lists (the columns of the grid).
 */
export const driversQueryOptions = (
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  freq: ForecastFreq = "annual",
) =>
  queryOptions<DriverGridOut>({
    queryKey: [...driversPrefix(ticker, id, scenarioCase), freq],
    queryFn: async () => {
      const grid = await unwrap(
        getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet({
          path: { ticker, scenario_id: id, case: scenarioCase },
          query: { freq },
        }),
      );
      if (
        !Array.isArray(grid?.rows) ||
        !Array.isArray(grid?.history_years) ||
        !Array.isArray(grid?.forecast_years) ||
        !Array.isArray(grid?.history_periods) ||
        !Array.isArray(grid?.forecast_periods) ||
        !Array.isArray(grid?.year_modes)
      ) {
        throw unexpected();
      }
      return grid;
    },
  });

/** A forecast the API cannot build (422): a driver to set, a missing value, a bound. */
export class ForecastUnavailable extends ApiError {
  constructor(detail: string | undefined) {
    super(422, detail);
    this.name = "ForecastUnavailable";
  }
}

/**
 * GET …/scenarios/{id}/cases/{case}/forecast. A 422 rejects with `ForecastUnavailable(detail)`; a 200 without
 * `periods`, `integrity` and `built_from_quarters` with `ApiError(200)`.
 */
export const forecastQueryOptions = (
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  type: StatementType,
  freq: ForecastFreq,
) =>
  queryOptions<ForecastOut>({
    queryKey: [...scenariosKey(ticker), id, scenarioCase, "forecast", type, freq],
    queryFn: async () => {
      const table = await unwrap(
        getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet({
          path: { ticker, scenario_id: id, case: scenarioCase },
          query: { type, freq },
        }),
      ).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 422) {
          throw new ForecastUnavailable(error.detail);
        }
        throw error;
      });
      if (
        !Array.isArray(table?.periods) ||
        !Array.isArray(table?.integrity) ||
        !Array.isArray(table?.built_from_quarters)
      ) {
        throw unexpected();
      }
      return table;
    },
  });

/**
 * GET …/scenarios/{id}/compare on the API's default codes: the scenario's Base, Bull and Bear.
 * Rejects a 200 of the wrong shape.
 */
export const compareQueryOptions = (ticker: string, id: number, freq: ForecastFreq) =>
  queryOptions<CompareOut>({
    queryKey: [...scenariosKey(ticker), id, "compare", freq],
    queryFn: async () => {
      const table = await unwrap(
        compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet({
          path: { ticker, scenario_id: id },
          query: { freq },
        }),
      );
      if (
        !Array.isArray(table?.periods) ||
        !Array.isArray(table?.codes) ||
        !Array.isArray(table?.cases) ||
        !Array.isArray(table?.built_from_quarters)
      ) {
        throw unexpected();
      }
      return table;
    },
  });

/** The download link of GET …/cases/{case}/drivers/export: a plain link, the browser saves the file. */
export function driverExportUrl(
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  format: DriverFileFormat,
): string {
  return `/api/v1/companies/${encodeURIComponent(ticker)}/scenarios/${id}/cases/${scenarioCase}/drivers/export?format=${format}`;
}

/**
 * Marks stale every scenario view of `ticker` (the list, every case's drivers and forecasts, and
 * the comparisons) and starts their refetch without waiting for it: a comparison runs a
 * scenario's three cases, and a mutation (a new scenario to pick) must not wait on that.
 */
export function invalidateScenarioViews(queryClient: QueryClient, ticker: string): void {
  void queryClient.invalidateQueries({ queryKey: scenariosKey(ticker) });
}

/** POST …/scenarios (unset settings are the default scenario's); on success invalidates the scenario views. */
export function useCreateScenario(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<ScenarioOut, Error, ScenarioIn>({
    mutationFn: (body) =>
      unwrap(createScenarioApiV1CompaniesTickerScenariosPost({ path: { ticker }, body })),
    onSuccess: () => invalidateScenarioViews(queryClient, ticker),
  });
}

/** PUT …/scenarios/{id} (absent fields are kept); on success invalidates the scenario views. */
export function useUpdateScenario(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<ScenarioOut, Error, { id: number; body: ScenarioSettingsIn }>({
    mutationFn: ({ id, body }) =>
      unwrap(
        updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut({
          path: { ticker, scenario_id: id },
          body,
        }),
      ),
    onSuccess: () => invalidateScenarioViews(queryClient, ticker),
  });
}

/** DELETE …/scenarios/{id} (the default scenario is a 409); on success invalidates the scenario views. */
export function useDeleteScenario(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(
        deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete({
          path: { ticker, scenario_id: id },
        }),
      ),
    onSuccess: () => invalidateScenarioViews(queryClient, ticker),
  });
}

const periodId = (year: number, period: string) => `${year}:${period}`;

/**
 * The drivers grid with `rows` written in as the case's own rows, for display while their PUT
 * runs. Only the rows of the grid's frequency apply, matched to its columns by year and quarter. A
 * value-kind period shows the sent value with source `own`; an offset-kind period has source
 * `offset` and no resolved value until the reply (Base + offset is the backend's); a period the row
 * no longer sets keeps its value and source until the reply. Rows of other drivers are unchanged.
 */
export function withDriverRows(grid: DriverGridOut, rows: DriverRowIn[]): DriverGridOut {
  const sent = new Map(
    rows.filter((row) => (row.freq ?? "annual") === grid.freq).map((row) => [row.driver_code, row]),
  );
  return {
    ...grid,
    rows: grid.rows.map((driver) => {
      const row = sent.get(driver.code);
      if (!row) return driver;
      const byPeriod = new Map(
        row.values.map((v) => [
          periodId(v.fiscal_year, v.fiscal_period ?? "FY"),
          v.value == null ? null : String(v.value),
        ]),
      );
      const own = grid.forecast_periods.map(
        (p) => byPeriod.get(periodId(p.fiscal_year, p.fiscal_period)) ?? null,
      );
      return {
        ...driver,
        kind: own.some((value) => value !== null) ? row.kind : null,
        own,
        // An offset period's resolved value (Base + offset) is the backend's: unknown until the reply.
        values: driver.values.map((value, i) =>
          own[i] === null ? value : row.kind === "value" ? (own[i] ?? null) : null,
        ),
        sources: driver.sources.map((source, i) =>
          own[i] === null ? source : row.kind === "value" ? "own" : "offset",
        ),
      };
    }),
  };
}

const putDriversKey = (ticker: string) => [...scenariosKey(ticker), "put-drivers"] as const;

/**
 * Where a driver write of a case ends (a PUT or a reset share one in-flight count, so their replies
 * cannot overwrite each other). `saved` is the reply (the grid of the frequency the backend picked),
 * or undefined after an error. When no other write of the company is running, the reply replaces
 * its own grid with no refetch; a reply that lands while another write runs is not applied but
 * marks the case's grids stale, and the last write to settle then reloads them instead (replies can
 * arrive out of order). An error reloads both frequencies too. This write still counts as running
 * here.
 */
function settleDrivers(
  queryClient: QueryClient,
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  saved: DriverGridOut | undefined,
) {
  const prefix = driversPrefix(ticker, id, scenarioCase);
  const key = saved && driversQueryOptions(ticker, id, scenarioCase, saved.freq).queryKey;
  if (queryClient.isMutating({ mutationKey: putDriversKey(ticker) }) > 1) {
    void queryClient.invalidateQueries({ queryKey: prefix, refetchType: "none" });
  } else if (saved && key && !queryClient.getQueryState(key)?.isInvalidated) {
    queryClient.setQueryData(key, saved);
  } else {
    void queryClient.invalidateQueries({ queryKey: prefix });
  }
}

// Marks every scenario view but the reply's own grid stale, and refreshes them in the background
// (the case's grid of the other frequency included: a write can move its `year` values and kinds).
function refreshOtherViews(
  queryClient: QueryClient,
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  saved: DriverGridOut,
) {
  const own = JSON.stringify(driversQueryOptions(ticker, id, scenarioCase, saved.freq).queryKey);
  void queryClient.invalidateQueries({
    queryKey: scenariosKey(ticker),
    predicate: (query) => JSON.stringify(query.queryKey) !== own,
  });
}

/**
 * PUT …/cases/{case}/drivers: each row replaces that driver's rows of its frequency. The edit shows
 * at once (`withDriverRows`, in each cached grid of the case) and goes back on an error; the reply
 * is settled as `settleDrivers` says. The other scenario views (the other cases' drivers, the
 * other frequency's grid, forecasts, the comparison) are refreshed in the background.
 */
export function usePutDrivers(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<
    DriverGridOut,
    Error,
    { id: number; case: ScenarioCase; rows: DriverRowIn[] },
    { previous: [readonly unknown[], DriverGridOut][] }
  >({
    mutationKey: putDriversKey(ticker),
    mutationFn: ({ id, case: scenarioCase, rows }) =>
      unwrap(
        putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut({
          path: { ticker, scenario_id: id, case: scenarioCase },
          body: { rows },
        }),
      ),
    onMutate: async ({ id, case: scenarioCase, rows }) => {
      const queryKey = driversPrefix(ticker, id, scenarioCase);
      await queryClient.cancelQueries({ queryKey });
      const previous: [readonly unknown[], DriverGridOut][] = [];
      for (const [key, grid] of queryClient.getQueriesData<DriverGridOut>({ queryKey })) {
        if (!Array.isArray(grid?.rows)) continue;
        previous.push([key, grid]);
        queryClient.setQueryData(key, withDriverRows(grid, rows));
      }
      return { previous };
    },
    onError: (_error, { id, case: scenarioCase }, context) => {
      for (const [key, grid] of context?.previous ?? []) queryClient.setQueryData(key, grid);
      settleDrivers(queryClient, ticker, id, scenarioCase, undefined);
    },
    onSuccess: (saved, { id, case: scenarioCase }) => {
      settleDrivers(queryClient, ticker, id, scenarioCase, saved);
      refreshOtherViews(queryClient, ticker, id, scenarioCase, saved);
    },
  });
}

/**
 * POST …/cases/{case}/reset: the case's own values are removed and its defaults come back. The
 * reply (the case's drivers) is settled like a PUT's, the other scenario views are refreshed. A
 * failed reset changed nothing, so the grid on screen is left as it is.
 */
export function useResetCase(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<DriverGridOut, Error, { id: number; case: ScenarioCase }>({
    mutationKey: putDriversKey(ticker),
    mutationFn: ({ id, case: scenarioCase }) =>
      unwrap(
        resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost({
          path: { ticker, scenario_id: id, case: scenarioCase },
        }),
      ),
    onSuccess: (saved, { id, case: scenarioCase }) => {
      settleDrivers(queryClient, ticker, id, scenarioCase, saved);
      refreshOtherViews(queryClient, ticker, id, scenarioCase, saved);
    },
  });
}

/**
 * PUT …/scenarios/{id}/years/{fiscal_year}/mode: a forecast year of the quarterly span is set
 * annually or by quarter, for the scenario's three cases. The switch moves values (a fill of the
 * quarters, or their removal), so every grid, forecast and comparison of the scenario is
 * invalidated. The mutation settles once the driver grids on screen have reloaded, so the switch
 * and the cells never show the old mode; the other views refetch in the background.
 */
export function useSetYearMode(ticker: string, id: number) {
  const queryClient = useQueryClient();
  return useMutation<YearModesOut, Error, { fiscalYear: number; mode: YearModeIn["mode"] }>({
    mutationFn: ({ fiscalYear, mode }) =>
      unwrap(
        setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut({
          path: { ticker, scenario_id: id, fiscal_year: fiscalYear },
          body: { mode },
        }),
      ),
    onSuccess: async () => {
      const queryKey = [...scenariosKey(ticker), id];
      const isGrid = (key: readonly unknown[]) => key.includes("drivers");
      void queryClient.invalidateQueries({ queryKey, predicate: (q) => !isGrid(q.queryKey) });
      await queryClient.invalidateQueries({ queryKey, predicate: (q) => isGrid(q.queryKey) });
    },
  });
}

/** A driver file the API refused: the 422's every error, located by row and column letter. */
export class DriverFileFailed extends ApiError {
  readonly issues: DriverFileIssueOut[];

  constructor(detail: string | undefined, issues: DriverFileIssueOut[]) {
    super(422, detail);
    this.name = "DriverFileFailed";
    this.issues = issues;
  }
}

export interface DriverImportInput {
  id: number;
  case: ScenarioCase;
  file: File;
}

async function sendDriverFile(
  ticker: string,
  { id, case: scenarioCase, file }: DriverImportInput,
  dryRun: boolean,
): Promise<DriverImportOut> {
  const result =
    await importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost({
      path: { ticker, scenario_id: id, case: scenarioCase },
      body: { file, dry_run: dryRun },
    }).catch(() => undefined);
  if (result?.response?.status === 422 && typeof result.error === "object" && result.error) {
    const { detail, errors } = result.error as { detail?: unknown; errors?: unknown };
    if (Array.isArray(errors)) {
      throw new DriverFileFailed(typeof detail === "string" ? detail : undefined, errors);
    }
  }
  return unwrap(Promise.resolve(result ?? {}));
}

/** POST …/cases/{case}/drivers/import with `dry_run`: the changes the file would make; nothing is invalidated. */
export function usePreviewDriverImport(ticker: string) {
  return useMutation<DriverImportOut, Error, DriverImportInput>({
    mutationFn: (input) => sendDriverFile(ticker, input, true),
  });
}

/** POST …/cases/{case}/drivers/import for real; on success invalidates the scenario views. */
export function useConfirmDriverImport(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<DriverImportOut, Error, DriverImportInput>({
    mutationFn: (input) => sendDriverFile(ticker, input, false),
    onSuccess: () => invalidateScenarioViews(queryClient, ticker),
  });
}
