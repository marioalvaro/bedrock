import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, unwrap } from "@/api/errors";
import {
  getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet,
  putEnginesApiV1CompaniesTickerScenariosScenarioIdEnginesPut,
} from "@/api/generated/sdk.gen";
import type { DriverEnginesOut, EngineChoicesOut, EngineRowIn } from "@/api/generated/types.gen";
import { invalidateScenarioViews, scenariosKey, type ScenarioCase } from "@/api/scenarios";

export type EngineCode = EngineRowIn["engine"];

const unexpected = () => new ApiError(200, "Unexpected response");

/**
 * GET …/scenarios/{id}/cases/{case}/driver-engines?code=: one driver's history beside ARIMA, ETS
 * and Blend. Rejects a 200 without its lists (G2/G4); a 422 rejects with its `detail`.
 */
export const driverEnginesQueryOptions = (
  ticker: string,
  id: number,
  scenarioCase: ScenarioCase,
  code: string,
) =>
  queryOptions<DriverEnginesOut>({
    queryKey: [...scenariosKey(ticker), id, scenarioCase, "driver-engines", code],
    queryFn: async () => {
      const view = await unwrap(
        getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet({
          path: { ticker, scenario_id: id, case: scenarioCase },
          query: { code },
        }),
      );
      if (
        !Array.isArray(view?.engines) ||
        !Array.isArray(view?.history) ||
        !Array.isArray(view?.history_periods) ||
        !Array.isArray(view?.values) ||
        !Array.isArray(view?.forecast_labels)
      ) {
        throw unexpected();
      }
      return view;
    },
  });

/**
 * PUT …/scenarios/{id}/engines: the rows' engine choices, shared by Base, Bull and Bear. Not
 * optimistic (the reply has no grid); on success every scenario view of the company is
 * invalidated, since every case's drivers, forecasts, comparison and valuations move.
 */
export function usePutEngines(ticker: string, id: number) {
  const queryClient = useQueryClient();
  return useMutation<EngineChoicesOut, Error, EngineRowIn[]>({
    mutationFn: async (rows) => {
      const reply = await unwrap(
        putEnginesApiV1CompaniesTickerScenariosScenarioIdEnginesPut({
          path: { ticker, scenario_id: id },
          body: { rows },
        }),
      );
      if (!Array.isArray(reply?.rows)) throw unexpected();
      return reply;
    },
    onSuccess: () => invalidateScenarioViews(queryClient, ticker),
  });
}
