import { useCallback } from "react";
import { useSearchParams } from "react-router";

import type { ScenarioOut } from "@/api/generated/types.gen";

export const SCENARIO_PARAM = "scenario";

/**
 * The scenario picked by `?scenario=<id>`, shared by the Forecast and Scenarios tabs: Base (the
 * list's default) when the param is absent or names no scenario of the list; undefined while the
 * list is loading. `select` writes the param, keeping the path and the other params.
 */
export function useScenarioParam(list: ScenarioOut[] | undefined) {
  const [params, setParams] = useSearchParams();
  const id = Number(params.get(SCENARIO_PARAM));
  const selected =
    list?.find((scenario) => scenario.id === id) ??
    list?.find((scenario) => scenario.is_default) ??
    list?.[0];

  const select = useCallback(
    (next: number) =>
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          updated.set(SCENARIO_PARAM, String(next));
          return updated;
        },
        { replace: true },
      ),
    [setParams],
  );

  return { selected, select };
}
