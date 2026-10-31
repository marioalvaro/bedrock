import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  compareScenariosApiV1CompaniesTickerScenariosCompareGet,
  createScenarioApiV1CompaniesTickerScenariosPost,
  deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete,
  getDriversApiV1CompaniesTickerScenariosScenarioIdDriversGet,
  getForecastApiV1CompaniesTickerScenariosScenarioIdForecastGet,
  importDriversApiV1CompaniesTickerScenariosScenarioIdDriversImportPost,
  listScenariosApiV1CompaniesTickerScenariosGet,
  putDriversApiV1CompaniesTickerScenariosScenarioIdDriversPut,
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
} from "@/api/generated/types.gen";
import type { StatementType } from "@/api/statements";

export type ForecastFreq = "annual" | "quarterly";
export type DriverFileFormat = "csv" | "xlsx";

// Every scenario query of a company (list, drivers, forecasts, compare) sits under this key, so
// one invalidation reaches them all.
export const scenariosKey = (ticker: string) => [...companyKey(ticker), "scenarios"] as const;

const unexpected = () => new ApiError(200, "Unexpected response");

/** GET …/scenarios (Base first). Rejects a 200 whose body is not an array (Gotcha G2). */
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

/** GET …/scenarios/{id}/drivers. Rejects a 200 without `rows` and the year lists. */
export const driversQueryOptions = (ticker: string, id: number) =>
  queryOptions<DriverGridOut>({
    queryKey: [...scenariosKey(ticker), id, "drivers"],
    queryFn: async () => {
      const grid = await unwrap(
        getDriversApiV1CompaniesTickerScenariosScenarioIdDriversGet({
          path: { ticker, scenario_id: id },
        }),
      );
      if (
        !Array.isArray(grid?.rows) ||
        !Array.isArray(grid?.history_years) ||
        !Array.isArray(grid?.forecast_years)
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
 * GET …/scenarios/{id}/forecast. A 422 rejects with `ForecastUnavailable(detail)`; a 200 without
 * `periods` and `integrity` with `ApiError(200)`.
 */
export const forecastQueryOptions = (
  ticker: string,
  id: number,
  type: StatementType,
  freq: ForecastFreq,
) =>
  queryOptions<ForecastOut>({
    queryKey: [...scenariosKey(ticker), id, "forecast", type, freq],
    queryFn: async () => {
      const table = await unwrap(
        getForecastApiV1CompaniesTickerScenariosScenarioIdForecastGet({
          path: { ticker, scenario_id: id },
          query: { type, freq },
        }),
      ).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 422) {
          throw new ForecastUnavailable(error.detail);
        }
        throw error;
      });
      if (!Array.isArray(table?.periods) || !Array.isArray(table?.integrity)) throw unexpected();
      return table;
    },
  });

/** GET …/scenarios/compare on the API's default codes. Rejects a 200 of the wrong shape. */
export const compareQueryOptions = (ticker: string, freq: ForecastFreq) =>
  queryOptions<CompareOut>({
    queryKey: [...scenariosKey(ticker), "compare", freq],
    queryFn: async () => {
      const table = await unwrap(
        compareScenariosApiV1CompaniesTickerScenariosCompareGet({
          path: { ticker },
          query: { freq },
        }),
      );
      if (
        !Array.isArray(table?.periods) ||
        !Array.isArray(table?.codes) ||
        !Array.isArray(table?.scenarios)
      ) {
        throw unexpected();
      }
      return table;
    },
  });

/** The download link of GET …/drivers/export: a plain link, so the browser saves the file. */
export function driverExportUrl(ticker: string, id: number, format: DriverFileFormat): string {
  return `/api/v1/companies/${encodeURIComponent(ticker)}/scenarios/${id}/drivers/export?format=${format}`;
}

/**
 * Marks stale every scenario view of `ticker` (the list, drivers, forecasts and the comparison)
 * and starts their refetch without waiting for it: the comparison runs every scenario's
 * forecast, and a mutation (a new scenario to pick) must not wait on that.
 */
export function invalidateScenarioViews(queryClient: QueryClient, ticker: string): void {
  void queryClient.invalidateQueries({ queryKey: scenariosKey(ticker) });
}

/** POST …/scenarios (unset settings copy Base's); on success invalidates the scenario views. */
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

/** DELETE …/scenarios/{id} (Base is a 409); on success invalidates the scenario views. */
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

/**
 * The drivers grid with `rows` written in as the scenario's own rows, for display while their PUT
 * runs. A value-kind year shows the sent value with source `own`; an offset-kind year has source
 * `offset` and no resolved value until the reply (Base + offset is the backend's); a year the row
 * no longer sets keeps its value and source until the reply. Rows of other drivers are unchanged.
 */
export function withDriverRows(grid: DriverGridOut, rows: DriverRowIn[]): DriverGridOut {
  const sent = new Map(rows.map((row) => [row.driver_code, row]));
  return {
    ...grid,
    rows: grid.rows.map((driver) => {
      const row = sent.get(driver.code);
      if (!row) return driver;
      const byYear = new Map(
        row.values.map((v) => [v.fiscal_year, v.value == null ? null : String(v.value)]),
      );
      const own = grid.forecast_years.map((year) => byYear.get(year) ?? null);
      return {
        ...driver,
        kind: own.some((value) => value !== null) ? row.kind : null,
        own,
        // An offset year's resolved value (Base + offset) is the backend's: unknown until the reply.
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
 * PUT …/drivers: each row replaces that driver's rows. The edited grid shows at once
 * (`withDriverRows`) and goes back on an error. When no other save of the company is running,
 * the reply (the saved grid) replaces it with no refetch; a reply that lands while another save
 * runs is not applied but marks the grid stale, and the last save to settle then reloads it
 * instead (replies can arrive out of order). An error also reloads it, after the rollback. The
 * other scenario views (other scenarios' drivers, forecasts, the comparison) are refreshed in the
 * background.
 */
export function usePutDrivers(ticker: string) {
  const queryClient = useQueryClient();
  const driversKey = (id: number) => driversQueryOptions(ticker, id).queryKey;
  // `saved` is the reply, or undefined after an error. This save still counts as running here.
  const settleDrivers = (id: number, saved: DriverGridOut | undefined) => {
    const key = driversKey(id);
    if (queryClient.isMutating({ mutationKey: putDriversKey(ticker) }) > 1) {
      void queryClient.invalidateQueries({ queryKey: key, exact: true, refetchType: "none" });
    } else if (saved && !queryClient.getQueryState(key)?.isInvalidated) {
      queryClient.setQueryData(key, saved);
    } else {
      void queryClient.invalidateQueries({ queryKey: key, exact: true });
    }
  };
  return useMutation<
    DriverGridOut,
    Error,
    { id: number; rows: DriverRowIn[] },
    { previous: DriverGridOut | undefined }
  >({
    mutationKey: putDriversKey(ticker),
    mutationFn: ({ id, rows }) =>
      unwrap(
        putDriversApiV1CompaniesTickerScenariosScenarioIdDriversPut({
          path: { ticker, scenario_id: id },
          body: { rows },
        }),
      ),
    onMutate: async ({ id, rows }) => {
      await queryClient.cancelQueries({ queryKey: driversKey(id) });
      const previous = queryClient.getQueryData<DriverGridOut>(driversKey(id));
      if (Array.isArray(previous?.rows)) {
        queryClient.setQueryData(driversKey(id), withDriverRows(previous, rows));
      }
      return { previous };
    },
    onError: (_error, { id }, context) => {
      if (context?.previous) queryClient.setQueryData(driversKey(id), context.previous);
      settleDrivers(id, undefined);
    },
    onSuccess: (saved, { id }) => {
      settleDrivers(id, saved);
      const own = JSON.stringify(driversKey(id));
      void queryClient.invalidateQueries({
        queryKey: scenariosKey(ticker),
        predicate: (query) => JSON.stringify(query.queryKey) !== own,
      });
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
  file: File;
}

async function sendDriverFile(
  ticker: string,
  { id, file }: DriverImportInput,
  dryRun: boolean,
): Promise<DriverImportOut> {
  const result = await importDriversApiV1CompaniesTickerScenariosScenarioIdDriversImportPost({
    path: { ticker, scenario_id: id },
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

/** POST …/drivers/import with `dry_run`: the changes the file would make; nothing is invalidated. */
export function usePreviewDriverImport(ticker: string) {
  return useMutation<DriverImportOut, Error, DriverImportInput>({
    mutationFn: (input) => sendDriverFile(ticker, input, true),
  });
}

/** POST …/drivers/import for real; on success invalidates the scenario views. */
export function useConfirmDriverImport(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<DriverImportOut, Error, DriverImportInput>({
    mutationFn: (input) => sendDriverFile(ticker, input, false),
    onSuccess: () => invalidateScenarioViews(queryClient, ticker),
  });
}
