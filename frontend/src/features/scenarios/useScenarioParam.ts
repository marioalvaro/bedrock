import { useCallback } from "react";
import { useSearchParams } from "react-router";

import type { ScenarioOut } from "@/api/generated/types.gen";
import { CASES, type ScenarioCase } from "@/api/scenarios";

export const SCENARIO_PARAM = "scenario";
export const CASE_PARAM = "case";

const isCase = (value: string | null): value is ScenarioCase =>
  CASES.some((candidate) => candidate.value === value);

/**
 * The scenario and case picked by `?scenario=<id>&case=base|bull|bear`, shared by the Forecast and
 * Scenarios tabs. The scenario is the list's default when the param is absent or names none of the
 * list (undefined while the list is loading); the case is `base` when the param is absent or
 * unknown. Each setter writes its param (replacing the history entry), keeping the path and the
 * other params.
 */
export function useScenarioParam(list: ScenarioOut[] | undefined) {
  const [params, setParams] = useSearchParams();
  const id = Number(params.get(SCENARIO_PARAM));
  const selected =
    list?.find((scenario) => scenario.id === id) ??
    list?.find((scenario) => scenario.is_default) ??
    list?.[0];
  const caseParam = params.get(CASE_PARAM);
  const scenarioCase: ScenarioCase = isCase(caseParam) ? caseParam : "base";

  const write = useCallback(
    (name: string, value: string) =>
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          updated.set(name, value);
          return updated;
        },
        { replace: true },
      ),
    [setParams],
  );
  const select = useCallback((next: number) => write(SCENARIO_PARAM, String(next)), [write]);
  const selectCase = useCallback((next: ScenarioCase) => write(CASE_PARAM, next), [write]);

  return { selected, select, scenarioCase, selectCase };
}
