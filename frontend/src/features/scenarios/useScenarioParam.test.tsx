import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
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

describe("useScenarioParam", () => {
  it("picks Base when the URL names no scenario", () => {
    const { result } = renderAt("/c/AAPL/scenarios", scenarios());
    expect(result.current.param.selected?.name).toBe("Base");
  });

  it("picks the scenario of ?scenario", () => {
    const { result } = renderAt("/c/AAPL/scenarios?scenario=3", scenarios());
    expect(result.current.param.selected?.name).toBe("Bear");
  });

  it("falls back to Base for an unknown or malformed id", () => {
    expect(
      renderAt("/c/AAPL/scenarios?scenario=99", scenarios()).result.current.param.selected?.name,
    ).toBe("Base");
    expect(
      renderAt("/c/AAPL/scenarios?scenario=abc", scenarios()).result.current.param.selected?.name,
    ).toBe("Base");
  });

  it("has no scenario while the list is loading or empty", () => {
    expect(
      renderAt("/c/AAPL/scenarios?scenario=2", undefined).result.current.param.selected,
    ).toBeUndefined();
    expect(renderAt("/c/AAPL/scenarios", []).result.current.param.selected).toBeUndefined();
  });

  it("select writes ?scenario and keeps the path and other params", () => {
    const { result } = renderAt("/c/AAPL/scenarios?x=1", scenarios());
    act(() => result.current.param.select(2));
    expect(result.current.location.pathname).toBe("/c/AAPL/scenarios");
    expect(new URLSearchParams(result.current.location.search).get("scenario")).toBe("2");
    expect(new URLSearchParams(result.current.location.search).get("x")).toBe("1");
    expect(result.current.param.selected?.name).toBe("Bull");
  });
});
