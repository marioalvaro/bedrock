import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { ApiError, unwrap } from "@/api/errors";
import {
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet,
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet,
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet,
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
  putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut,
  resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost,
} from "@/api/generated/sdk.gen";
import type {
  SensitivityGridOut,
  TornadoOut,
  ValuationInputIn,
  ValuationInputsOut,
  ValuationOut,
  ValuationSummaryOut,
} from "@/api/generated/types.gen";
import { scenariosKey, type ScenarioCase } from "@/api/scenarios";

// Every valuation query sits under the scenario's key (`[company, "scenarios", id, …]`), so the M4
// invalidations of the scenario views (drivers, adjustments, imports, segments, refresh) reach it.
const scenarioKey = (ticker: string, id: number) => [...scenariosKey(ticker), id] as const;

const unexpected = () => new ApiError(200, "Unexpected response");

/** A valuation the API cannot run (422): drivers to set, an input it refuses. */
export class ValuationUnavailable extends ApiError {
  constructor(detail: string | undefined) {
    super(422, detail);
    this.name = "ValuationUnavailable";
  }
}

// Unwraps a call, a 422 becoming `ValuationUnavailable(detail)`.
const fetchValuation = <T>(call: Promise<{ data?: T; error?: unknown; response?: Response }>) =>
  unwrap(call).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 422) {
      throw new ValuationUnavailable(error.detail);
    }
    throw error;
  });

// The inputs view's shape (Gotcha G2): its rows, the forecast years (the year selects) and warnings.
function checkInputs(view: ValuationInputsOut | undefined): ValuationInputsOut {
  if (
    !Array.isArray(view?.rows) ||
    !Array.isArray(view?.forecast_years) ||
    !Array.isArray(view?.warnings)
  ) {
    throw unexpected();
  }
  return view;
}

/** GET …/cases/{case}/valuation-inputs: the case's inputs with their sources, in catalog order. */
export const valuationInputsQueryOptions = (
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
) =>
  queryOptions<ValuationInputsOut>({
    queryKey: [...scenarioKey(ticker, id), scenarioCase, "valuation-inputs"],
    queryFn: async () =>
      checkInputs(
        await fetchValuation(
          getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet({
            path: { ticker, scenario_id: id, case: scenarioCase },
          }),
        ),
      ),
  });

/**
 * GET …/cases/{case}/valuation: the case's DCF and multiple-target results against the price.
 * Rejects a 200 without `results`, `warnings` and `bridge`.
 */
export const valuationQueryOptions = (ticker: string, id: number, scenarioCase: ScenarioCase) =>
  queryOptions<ValuationOut>({
    queryKey: [...scenarioKey(ticker, id), scenarioCase, "valuation"],
    queryFn: async () => {
      const view = await fetchValuation(
        getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet({
          path: { ticker, scenario_id: id, case: scenarioCase },
        }),
      );
      if (
        !Array.isArray(view?.results) ||
        !Array.isArray(view?.warnings) ||
        typeof view?.bridge !== "object" ||
        view.bridge === null
      ) {
        throw unexpected();
      }
      return view;
    },
  });

/** GET …/scenarios/{id}/valuation: the scenario's three cases. Rejects a 200 without `methods` and `cases`. */
export const valuationSummaryQueryOptions = (ticker: string, id: number) =>
  queryOptions<ValuationSummaryOut>({
    queryKey: [...scenarioKey(ticker, id), "valuation-summary"],
    queryFn: async () => {
      const view = await fetchValuation(
        getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet({
          path: { ticker, scenario_id: id },
        }),
      );
      if (!Array.isArray(view?.methods) || !Array.isArray(view?.cases)) throw unexpected();
      return view;
    },
  });

/**
 * GET …/cases/{case}/sensitivity/tornado: the DCF value per share's change per input at its unit
 * step, bars sorted by range. Rejects a 200 without `bars` and `base_value`.
 */
export const tornadoQueryOptions = (ticker: string, id: number, scenarioCase: ScenarioCase) =>
  queryOptions<TornadoOut>({
    queryKey: [...scenarioKey(ticker, id), scenarioCase, "tornado"],
    queryFn: async () => {
      const view = await fetchValuation(
        getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet({
          path: { ticker, scenario_id: id, case: scenarioCase },
        }),
      );
      if (!Array.isArray(view?.bars) || typeof view?.base_value !== "string") throw unexpected();
      return view;
    },
  });

const isAxis = (axis: unknown) =>
  typeof axis === "object" &&
  axis !== null &&
  Array.isArray((axis as { shifts?: unknown }).shifts) &&
  Array.isArray((axis as { points?: unknown }).points);

/**
 * GET …/cases/{case}/sensitivity/grid?x&y: the 5 × 5 DCF value per share over two inputs (rows
 * are y). Rejects a 200 without both axes, `values`, `upside` and `errors`.
 */
export const sensitivityGridQueryOptions = (
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  x: string,
  y: string,
) =>
  queryOptions<SensitivityGridOut>({
    queryKey: [...scenarioKey(ticker, id), scenarioCase, "sensitivity-grid", x, y],
    queryFn: async () => {
      const view = await fetchValuation(
        getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet({
          path: { ticker, scenario_id: id, case: scenarioCase },
          query: { x, y },
        }),
      );
      if (
        !isAxis(view?.x) ||
        !isAxis(view?.y) ||
        !Array.isArray(view?.values) ||
        !Array.isArray(view?.upside) ||
        !Array.isArray(view?.errors)
      ) {
        throw unexpected();
      }
      return view;
    },
  });

// The input writes of a company (PUT and reset) share one in-flight count.
const writeInputsKey = (ticker: string) => [...scenariosKey(ticker), "write-valuation-inputs"];

/**
 * Where an input write ends. When no other input write of the company runs, the reply replaces
 * the case's inputs with no refetch; a reply that lands while another runs is not applied but
 * marks the inputs stale, and the last write to settle reloads them (replies can arrive out of
 * order). Every other view of the scenario (the other cases' inputs, which may inherit from
 * Base, the valuations, the summary) is refreshed in the background, not awaited.
 */
function settleInputs(
  queryClient: QueryClient,
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  saved: ValuationInputsOut,
) {
  const { queryKey } = valuationInputsQueryOptions(ticker, id, scenarioCase);
  if (queryClient.isMutating({ mutationKey: writeInputsKey(ticker) }) > 1) {
    void queryClient.invalidateQueries({ queryKey, exact: true, refetchType: "none" });
  } else if (!queryClient.getQueryState(queryKey)?.isInvalidated) {
    queryClient.setQueryData(queryKey, saved);
  } else {
    void queryClient.invalidateQueries({ queryKey, exact: true });
  }
  const own = JSON.stringify(queryKey);
  void queryClient.invalidateQueries({
    queryKey: scenarioKey(ticker, id),
    predicate: (query) => JSON.stringify(query.queryKey) !== own,
  });
}

/**
 * PUT …/cases/{case}/valuation-inputs: each row sets the case's own value, or with `null` drops it
 * (inherit Base, or the default). Not optimistic: the reply is settled by `settleInputs`; a refused
 * write (422) changed nothing.
 */
export function usePutValuationInputs(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<
    ValuationInputsOut,
    Error,
    { id: number; case: ScenarioCase; rows: ValuationInputIn[] }
  >({
    mutationKey: writeInputsKey(ticker),
    mutationFn: async ({ id, case: scenarioCase, rows }) =>
      checkInputs(
        await unwrap(
          putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut({
            path: { ticker, scenario_id: id, case: scenarioCase },
            body: { rows },
          }),
        ),
      ),
    onSuccess: (saved, { id, case: scenarioCase }) =>
      settleInputs(queryClient, ticker, id, scenarioCase, saved),
  });
}

/** POST …/cases/{case}/valuation-inputs/reset: every own input of the case is removed; settled as a PUT. */
export function useResetValuationInputs(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<ValuationInputsOut, Error, { id: number; case: ScenarioCase }>({
    mutationKey: writeInputsKey(ticker),
    mutationFn: async ({ id, case: scenarioCase }) =>
      checkInputs(
        await unwrap(
          resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost(
            { path: { ticker, scenario_id: id, case: scenarioCase } },
          ),
        ),
      ),
    onSuccess: (saved, { id, case: scenarioCase }) =>
      settleInputs(queryClient, ticker, id, scenarioCase, saved),
  });
}
