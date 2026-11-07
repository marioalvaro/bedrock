import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import { driverEnginesQueryOptions, usePutEngines } from "@/api/engines";
import { ApiError } from "@/api/errors";
import {
  getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet,
  putEnginesApiV1CompaniesTickerScenariosScenarioIdEnginesPut,
} from "@/api/generated/sdk.gen";
import { scenariosKey } from "@/api/scenarios";
import { driverEngines, engineChoices } from "@/test/engines";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet: vi.fn(),
  putEnginesApiV1CompaniesTickerScenariosScenarioIdEnginesPut: vi.fn(),
}));

const getEngines = vi.mocked(
  getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet,
);
const putEngines = vi.mocked(putEnginesApiV1CompaniesTickerScenariosScenarioIdEnginesPut);

afterEach(() => vi.clearAllMocks());

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

const aapl = companyKey("AAPL");
const options = () => driverEnginesQueryOptions("AAPL", 1, "base", "gross_margin");

describe("driverEnginesQueryOptions", () => {
  it("sits under the company's scenarios key, by scenario, case and driver", () => {
    expect(options().queryKey).toEqual([
      ...aapl,
      "scenarios",
      1,
      "base",
      "driver-engines",
      "gross_margin",
    ]);
  });

  it("sends the driver code as a query parameter", async () => {
    getEngines.mockResolvedValue(okResult(driverEngines()) as never);
    const { queryClient } = setup();
    const data = await queryClient.fetchQuery(options());
    expect(getEngines).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      query: { code: "gross_margin" },
    });
    expect(data.used).toBe("arima");
  });

  it("rejects a 200 of the wrong shape (an HTML shell, G2)", async () => {
    getEngines.mockResolvedValue(okResult("<!doctype html><html></html>") as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(options())).rejects.toMatchObject({ status: 200 });
  });

  it("rejects a 200 without the engines list", async () => {
    const { engines: _engines, ...rest } = driverEngines();
    getEngines.mockResolvedValue(okResult(rest) as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(options())).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects a 422 with its detail", async () => {
    getEngines.mockResolvedValue(
      errorResult(422, { detail: "nope is not a driver of the growth method" }) as never,
    );
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(options())).rejects.toMatchObject({
      status: 422,
      detail: "nope is not a driver of the growth method",
    });
  });
});

describe("usePutEngines", () => {
  const moved = [
    scenariosKey("AAPL"),
    [...aapl, "scenarios", 1, "bull", "drivers", "annual"],
    [...aapl, "scenarios", 1, "base", "driver-engines", "gross_margin"],
    [...aapl, "scenarios", 1, "bear", "valuation"],
  ];
  const untouched = [
    [...aapl, "statements", "IS", "annual", "total", "reported"],
    [...companyKey("MSFT"), "scenarios"],
  ];

  it("sends the rows and invalidates every scenario view of the company", async () => {
    putEngines.mockResolvedValue(okResult(engineChoices()) as never);
    const { queryClient, wrapper } = setup();
    for (const key of [...moved, ...untouched]) queryClient.setQueryData(key, {});
    const { result } = renderHook(() => usePutEngines("AAPL", 1), { wrapper });
    result.current.mutate([{ driver_code: "gross_margin", engine: "ets" }]);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(putEngines).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1 },
      body: { rows: [{ driver_code: "gross_margin", engine: "ets" }] },
    });
    for (const key of moved) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    for (const key of untouched) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });

  it("rejects a 200 reply without rows", async () => {
    putEngines.mockResolvedValue(okResult("<!doctype html><html></html>") as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => usePutEngines("AAPL", 1), { wrapper });
    result.current.mutate([{ driver_code: "gross_margin", engine: "ets" }]);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 200 });
  });

  it("rejects a 422 with its detail and invalidates nothing", async () => {
    putEngines.mockResolvedValue(
      errorResult(422, { detail: "STL applies to ratio and days drivers only: buybacks" }) as never,
    );
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(scenariosKey("AAPL"), {});
    const { result } = renderHook(() => usePutEngines("AAPL", 1), { wrapper });
    result.current.mutate([{ driver_code: "buybacks", engine: "stl" }]);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({
      status: 422,
      detail: "STL applies to ratio and days drivers only: buybacks",
    });
    expect(queryClient.getQueryState(scenariosKey("AAPL"))?.isInvalidated).toBe(false);
  });
});
