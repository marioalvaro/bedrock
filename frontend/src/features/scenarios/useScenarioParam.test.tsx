import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation, useNavigationType } from "react-router";
import { describe, expect, it } from "vitest";

import type { ScenarioOut } from "@/api/generated/types.gen";
import { scenarios } from "@/test/scenarios";

import { useScenarioParam } from "./useScenarioParam";

function renderAt(path: string, list: ScenarioOut[] | undefined) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
  );
  return renderHook(() => ({ param: useScenarioParam(list), location: useLocation() }), {
    wrapper,
  });
}

const search = (result: { current: { location: { search: string } } }) =>
  new URLSearchParams(result.current.location.search);

describe("useScenarioParam", () => {
  it("picks the default scenario and the base case when the URL names neither", () => {
    const { result } = renderAt("/c/AAPL/scenarios", scenarios());
    expect(result.current.param.selected?.name).toBe("Main");
    expect(result.current.param.scenarioCase).toBe("base");
  });

  it("picks the scenario of ?scenario and the case of ?case", () => {
    const { result } = renderAt("/c/AAPL/scenarios?scenario=2&case=bear", scenarios());
    expect(result.current.param.selected?.name).toBe("Cycle");
    expect(result.current.param.scenarioCase).toBe("bear");
  });

  it("falls back to the default scenario for an unknown or malformed id", () => {
    expect(
      renderAt("/c/AAPL/scenarios?scenario=99", scenarios()).result.current.param.selected?.name,
    ).toBe("Main");
    expect(
      renderAt("/c/AAPL/scenarios?scenario=abc", scenarios()).result.current.param.selected?.name,
    ).toBe("Main");
  });

  it("falls back to the base case for an unknown case", () => {
    for (const value of ["bogus", "Bull", ""]) {
      const { result } = renderAt(`/c/AAPL/scenarios?case=${value}`, scenarios());
      expect(result.current.param.scenarioCase, value).toBe("base");
    }
  });

  it("has no scenario while the list is loading or empty, but still a case", () => {
    const loading = renderAt("/c/AAPL/scenarios?scenario=2&case=bull", undefined).result.current;
    expect(loading.param.selected).toBeUndefined();
    expect(loading.param.scenarioCase).toBe("bull");
    expect(renderAt("/c/AAPL/scenarios", []).result.current.param.selected).toBeUndefined();
  });

  it("select writes ?scenario and keeps the path, ?case and other params", () => {
    const { result } = renderAt("/c/AAPL/scenarios?x=1&case=bull", scenarios());
    act(() => result.current.param.select(2));
    expect(result.current.location.pathname).toBe("/c/AAPL/scenarios");
    expect(search(result).get("scenario")).toBe("2");
    expect(search(result).get("case")).toBe("bull");
    expect(search(result).get("x")).toBe("1");
    expect(result.current.param.selected?.name).toBe("Cycle");
  });

  it("selectCase writes ?case and keeps ?scenario and other params", () => {
    const { result } = renderAt("/c/AAPL/scenarios?x=1&scenario=2", scenarios());
    act(() => result.current.param.selectCase("bear"));
    expect(search(result).get("case")).toBe("bear");
    expect(search(result).get("scenario")).toBe("2");
    expect(search(result).get("x")).toBe("1");
    expect(result.current.param.scenarioCase).toBe("bear");
  });

  it("writes with replace: a pick adds no history entry", () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MemoryRouter initialEntries={["/c/AAPL/scenarios"]}>{children}</MemoryRouter>
    );
    const { result } = renderHook(
      () => ({ param: useScenarioParam(scenarios()), type: useNavigationType() }),
      { wrapper },
    );
    act(() => result.current.param.selectCase("bull"));
    expect(result.current.type).toBe("REPLACE");
    act(() => result.current.param.select(2));
    expect(result.current.type).toBe("REPLACE");
  });
});
