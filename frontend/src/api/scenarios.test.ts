import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import { ApiError } from "@/api/errors";
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
import type { DriverGridOut } from "@/api/generated/types.gen";
import {
  DriverFileFailed,
  ForecastUnavailable,
  compareQueryOptions,
  driverExportUrl,
  driversQueryOptions,
  forecastQueryOptions,
  scenariosKey,
  scenariosQueryOptions,
  useConfirmDriverImport,
  useCreateScenario,
  useDeleteScenario,
  usePreviewDriverImport,
  usePutDrivers,
  useResetCase,
  useSetYearMode,
  withDriverRows,
  useUpdateScenario,
} from "@/api/scenarios";
import {
  comparison,
  driverGrid,
  driverImport,
  forecast,
  quarterlyGrid,
  scenario,
  scenarios,
} from "@/test/scenarios";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  listScenariosApiV1CompaniesTickerScenariosGet: vi.fn(),
  createScenarioApiV1CompaniesTickerScenariosPost: vi.fn(),
  updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut: vi.fn(),
  deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete: vi.fn(),
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet: vi.fn(),
  putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut: vi.fn(),
  resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost: vi.fn(),
  importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost: vi.fn(),
  getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet: vi.fn(),
  compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet: vi.fn(),
  setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut: vi.fn(),
}));

const list = vi.mocked(listScenariosApiV1CompaniesTickerScenariosGet);
const create = vi.mocked(createScenarioApiV1CompaniesTickerScenariosPost);
const update = vi.mocked(updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut);
const remove = vi.mocked(deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete);
const getDrivers = vi.mocked(getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet);
const putDrivers = vi.mocked(putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut);
const importDrivers = vi.mocked(
  importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost,
);
const getForecast = vi.mocked(
  getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet,
);
const resetCase = vi.mocked(resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost);
const compare = vi.mocked(compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet);
const setYearMode = vi.mocked(
  setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut,
);

afterEach(() => vi.clearAllMocks());

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

// A 200 with the Vite fallback's HTML shell, as the client hands it back (Gotcha G2).
const html = () => okResult("<!doctype html><html></html>") as never;

const file = new File(["driver_code,label,unit,kind,FY2026\n"], "AAPL-Main-Bull-drivers.csv");

// Keys a scenario or driver write moves, and keys it leaves alone.
const aapl = companyKey("AAPL");
const moved = [
  scenariosKey("AAPL"),
  [...aapl, "scenarios", 2, "bull", "drivers", "annual"],
  [...aapl, "scenarios", 2, "bull", "drivers", "quarterly"],
  [...aapl, "scenarios", 2, "bear", "forecast", "BS", "quarterly"],
  [...aapl, "scenarios", 2, "compare", "annual"],
];
const untouched = [
  [...aapl, "statements", "IS", "annual", "total", "reported"],
  [...aapl, "segments", "annual"],
  [...companyKey("MSFT"), "scenarios"],
];

function seed(queryClient: QueryClient) {
  for (const key of [...moved, ...untouched]) queryClient.setQueryData(key, {});
}

function expectInvalidated(queryClient: QueryClient, invalidated: boolean) {
  for (const key of moved) {
    expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(invalidated);
  }
  for (const key of untouched) {
    expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
  }
}

describe("keys", () => {
  it("nests every scenario query under [company, 'scenarios']", () => {
    expect(scenariosQueryOptions("AAPL").queryKey).toEqual([...aapl, "scenarios"]);
    expect(driversQueryOptions("AAPL", 2, "bull").queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "bull",
      "drivers",
      "annual",
    ]);
    expect(driversQueryOptions("AAPL", 2, "bull", "quarterly").queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "bull",
      "drivers",
      "quarterly",
    ]);
    expect(forecastQueryOptions("AAPL", 2, "bear", "BS", "quarterly").queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "bear",
      "forecast",
      "BS",
      "quarterly",
    ]);
    expect(compareQueryOptions("AAPL", 2, "annual").queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "compare",
      "annual",
    ]);
  });

  it("keeps the cases of a scenario apart", () => {
    const keys = (["base", "bull", "bear"] as const).map((c) =>
      JSON.stringify(driversQueryOptions("AAPL", 2, c).queryKey),
    );
    expect(new Set(keys).size).toBe(3);
  });
});

describe("driverExportUrl", () => {
  it("names the scenario, the case and the format", () => {
    expect(driverExportUrl("AAPL", 2, "bull", "xlsx")).toBe(
      "/api/v1/companies/AAPL/scenarios/2/cases/bull/drivers/export?format=xlsx",
    );
    expect(driverExportUrl("BRK/B", 7, "base", "csv")).toBe(
      "/api/v1/companies/BRK%2FB/scenarios/7/cases/base/drivers/export?format=csv",
    );
  });
});

describe("scenariosQueryOptions", () => {
  it("returns the list", async () => {
    list.mockResolvedValue(okResult(scenarios()) as never);
    const { queryClient } = setup();
    const result = await queryClient.fetchQuery(scenariosQueryOptions("AAPL"));
    expect(result.map((s) => s.name)).toEqual(["Main", "Cycle"]);
    expect(list).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
  });

  it("rejects a 200 whose body is not a list", async () => {
    list.mockResolvedValue(html());
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(scenariosQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 200,
    });
  });
});

describe("driversQueryOptions", () => {
  it("returns the grid", async () => {
    getDrivers.mockResolvedValue(okResult(driverGrid()) as never);
    const { queryClient } = setup();
    const grid = await queryClient.fetchQuery(driversQueryOptions("AAPL", 1, "bear"));
    expect(grid.forecast_years).toEqual([2026, 2027]);
    expect(getDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "bear" },
      query: { freq: "annual" },
    });
  });

  it("asks for the quarterly grid when told to", async () => {
    getDrivers.mockResolvedValue(okResult(quarterlyGrid()) as never);
    const { queryClient } = setup();
    const grid = await queryClient.fetchQuery(driversQueryOptions("AAPL", 1, "base", "quarterly"));
    expect(grid.forecast_periods.map((p) => p.label)).toEqual(["Q1 FY26E", "Q2 FY26E"]);
    expect(getDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      query: { freq: "quarterly" },
    });
  });

  it("rejects a 200 without the period lists (an older backend, or an HTML shell)", async () => {
    const { history_periods: _history, forecast_periods: _forecast, ...bare } = quarterlyGrid();
    getDrivers.mockResolvedValue(okResult(bare) as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(driversQueryOptions("AAPL", 1, "base", "quarterly")),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects a 200 without the year modes (an older backend)", async () => {
    const { year_modes: _modes, ...bare } = driverGrid();
    getDrivers.mockResolvedValue(okResult(bare) as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(driversQueryOptions("AAPL", 1, "base")),
    ).rejects.toMatchObject({ status: 200 });
  });

  it("rejects a 200 without has_quarters (an older backend)", async () => {
    const { has_quarters: _quarters, ...bare } = driverGrid();
    getDrivers.mockResolvedValue(okResult(bare) as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(driversQueryOptions("AAPL", 1, "base")),
    ).rejects.toMatchObject({ status: 200 });
  });

  it("rejects a 200 without rows and years", async () => {
    getDrivers.mockResolvedValue(html());
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(driversQueryOptions("AAPL", 1, "base")),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("keeps the API's 422 reason (no opening balance sheet)", async () => {
    getDrivers.mockResolvedValue(
      errorResult(422, { detail: "No fiscal year to start from" }) as never,
    );
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(driversQueryOptions("AAPL", 1, "base")),
    ).rejects.toMatchObject({
      status: 422,
      detail: "No fiscal year to start from",
    });
  });
});

describe("forecastQueryOptions", () => {
  it("asks for the statement and frequency", async () => {
    getForecast.mockResolvedValue(okResult(forecast()) as never);
    const { queryClient } = setup();
    const result = await queryClient.fetchQuery(
      forecastQueryOptions("AAPL", 1, "bull", "IS", "annual"),
    );
    expect(result.integrity).toHaveLength(1);
    expect(getForecast).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "bull" },
      query: { type: "IS", freq: "annual" },
    });
  });

  it("rejects a 422 with ForecastUnavailable carrying the detail", async () => {
    getForecast.mockResolvedValue(
      errorResult(422, { detail: "Set these drivers: gross_margin" }) as never,
    );
    const { queryClient } = setup();
    const error = await queryClient
      .fetchQuery(forecastQueryOptions("DE", 1, "base", "IS", "annual"))
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ForecastUnavailable);
    expect(error).toMatchObject({ status: 422, detail: "Set these drivers: gross_margin" });
  });

  it("rejects another failure with a plain ApiError", async () => {
    getForecast.mockResolvedValue(errorResult(500) as never);
    const { queryClient } = setup();
    const error = await queryClient
      .fetchQuery(forecastQueryOptions("AAPL", 1, "base", "IS", "annual"))
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(ForecastUnavailable);
  });

  it("rejects a 200 without periods and integrity", async () => {
    getForecast.mockResolvedValue(html());
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(forecastQueryOptions("AAPL", 1, "base", "IS", "annual")),
    ).rejects.toMatchObject({ status: 200 });
  });
});

describe("built_from_quarters", () => {
  it("is read from a forecast", async () => {
    getForecast.mockResolvedValue(okResult(forecast({ built_from_quarters: [2026] })) as never);
    const { queryClient } = setup();
    const table = await queryClient.fetchQuery(
      forecastQueryOptions("AAPL", 1, "base", "IS", "annual"),
    );
    expect(table.built_from_quarters).toEqual([2026]);
  });

  it("is required in a forecast", async () => {
    const { built_from_quarters: _years, ...bare } = forecast();
    getForecast.mockResolvedValue(okResult(bare) as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(forecastQueryOptions("AAPL", 1, "base", "IS", "annual")),
    ).rejects.toMatchObject({ status: 200 });
  });

  it("is required in a comparison", async () => {
    const { built_from_quarters: _years, ...bare } = comparison();
    compare.mockResolvedValue(okResult(bare) as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(compareQueryOptions("AAPL", 1, "annual")),
    ).rejects.toMatchObject({ status: 200 });
  });
});

describe("compareQueryOptions", () => {
  it("asks for the scenario's frequency with the API's default codes", async () => {
    compare.mockResolvedValue(okResult(comparison()) as never);
    const { queryClient } = setup();
    const result = await queryClient.fetchQuery(compareQueryOptions("AAPL", 2, "quarterly"));
    expect(result.cases.map((c) => c.label)).toEqual(["Base", "Bull", "Bear"]);
    expect(compare).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2 },
      query: { freq: "quarterly" },
    });
  });

  it("rejects a 200 without periods, codes and cases", async () => {
    compare.mockResolvedValue(html());
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(compareQueryOptions("AAPL", 1, "annual")),
    ).rejects.toMatchObject({ status: 200 });
  });
});

describe("mutations", () => {
  it("useCreateScenario posts the body and invalidates the scenario views", async () => {
    create.mockResolvedValue(okResult(scenario({ id: 4, name: "Recession" }), 201) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useCreateScenario("AAPL"), { wrapper });
    result.current.mutate({ name: "Recession" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(create).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, body: { name: "Recession" } });
    expect(result.current.data?.id).toBe(4);
    expectInvalidated(queryClient, true);
  });

  it("settles without waiting for the scenario views to refetch", async () => {
    // The comparison runs every scenario's forecast: a new scenario is picked before it returns.
    create.mockResolvedValue(okResult(scenario({ id: 4, name: "Recession" }), 201) as never);
    const { queryClient, wrapper } = setup();
    const observer = new QueryObserver(queryClient, {
      queryKey: [...aapl, "scenarios", "compare", "annual"],
      queryFn: () => new Promise(() => {}), // a refetch that never returns
    });
    const stop = observer.subscribe(() => {});
    const { result } = renderHook(() => useCreateScenario("AAPL"), { wrapper });
    result.current.mutate({ name: "Recession" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    stop();
  });

  it("useUpdateScenario puts the settings and invalidates", async () => {
    update.mockResolvedValue(okResult(scenario({ name: "Bullish" })) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useUpdateScenario("AAPL"), { wrapper });
    result.current.mutate({ id: 2, body: { name: "Bullish" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2 },
      body: { name: "Bullish" },
    });
    expectInvalidated(queryClient, true);
  });

  describe("useSetYearMode", () => {
    const modes = {
      years: [{ fiscal_year: 2026, label: "FY26E", mode: "quarterly", in_span: true }],
    };

    it("puts the mode of the year and invalidates the grids, forecasts and comparisons of that scenario", async () => {
      setYearMode.mockResolvedValue(okResult(modes) as never);
      const { queryClient, wrapper } = setup();
      seed(queryClient);
      const { result } = renderHook(() => useSetYearMode("AAPL", 2), { wrapper });
      result.current.mutate({ fiscalYear: 2026, mode: "quarterly" });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(setYearMode).toHaveBeenCalledWith({
        path: { ticker: "AAPL", scenario_id: 2, fiscal_year: 2026 },
        body: { mode: "quarterly" },
      });
      for (const key of moved.slice(1)) {
        expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
      }
      for (const key of [scenariosKey("AAPL"), ...untouched]) {
        expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
      }
    });

    it("leaves another scenario's views alone", async () => {
      setYearMode.mockResolvedValue(okResult(modes) as never);
      const { queryClient, wrapper } = setup();
      const other = [...aapl, "scenarios", 3, "base", "drivers", "annual"];
      queryClient.setQueryData(other, {});
      const { result } = renderHook(() => useSetYearMode("AAPL", 2), { wrapper });
      result.current.mutate({ fiscalYear: 2026, mode: "annual" });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(queryClient.getQueryState(other)?.isInvalidated).toBe(false);
    });

    it("settles only once the driver grid on screen has reloaded, not the comparison", async () => {
      setYearMode.mockResolvedValue(okResult(modes) as never);
      const { queryClient, wrapper } = setup();
      let reload: (grid: object) => void = () => {};
      const grid = new QueryObserver(queryClient, {
        queryKey: [...aapl, "scenarios", 2, "base", "drivers", "annual"],
        queryFn: () => new Promise((resolve) => (reload = resolve)),
      });
      const compareView = new QueryObserver(queryClient, {
        queryKey: [...aapl, "scenarios", 2, "compare", "annual"],
        queryFn: () => new Promise(() => {}), // never returns
      });
      const stops = [grid.subscribe(() => {}), compareView.subscribe(() => {})];
      const { result } = renderHook(() => useSetYearMode("AAPL", 2), { wrapper });
      result.current.mutate({ fiscalYear: 2026, mode: "quarterly" });
      await waitFor(() => expect(setYearMode).toHaveBeenCalled());
      await new Promise((r) => setTimeout(r, 20));
      expect(result.current.isPending).toBe(true);
      reload({});
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      stops.forEach((stop) => stop());
    });

    it("keeps the API's reason on a 422 and invalidates nothing", async () => {
      setYearMode.mockResolvedValue(
        errorResult(422, { detail: "FY2030 is not in the quarterly span" }) as never,
      );
      const { queryClient, wrapper } = setup();
      seed(queryClient);
      const { result } = renderHook(() => useSetYearMode("AAPL", 2), { wrapper });
      result.current.mutate({ fiscalYear: 2030, mode: "quarterly" });
      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(result.current.error).toMatchObject({
        status: 422,
        detail: "FY2030 is not in the quarterly span",
      });
      expectInvalidated(queryClient, false);
    });
  });

  it("useDeleteScenario deletes and invalidates", async () => {
    remove.mockResolvedValue(okResult(null, 204) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useDeleteScenario("AAPL"), { wrapper });
    result.current.mutate(3);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", scenario_id: 3 } });
    expectInvalidated(queryClient, true);
  });

  it("a failed delete keeps the API's reason and invalidates nothing", async () => {
    remove.mockResolvedValue(
      errorResult(409, { detail: "The default scenario cannot be deleted" }) as never,
    );
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useDeleteScenario("AAPL"), { wrapper });
    result.current.mutate(1);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({
      status: 409,
      detail: "The default scenario cannot be deleted",
    });
    expectInvalidated(queryClient, false);
  });

  it("usePutDrivers puts the rows and invalidates", async () => {
    putDrivers.mockResolvedValue(okResult(driverGrid()) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => usePutDrivers("AAPL"), { wrapper });
    const rows = [
      {
        driver_code: "revenue_growth",
        kind: "offset" as const,
        values: [{ fiscal_year: 2026, value: "0.04" }],
      },
    ];
    result.current.mutate({ id: 2, case: "bull", rows });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      body: { rows },
    });
    // The edited case's drivers take the reply (no refetch); every other view is refreshed.
    const edited = [...aapl, "scenarios", 2, "bull", "drivers", "annual"];
    expect(queryClient.getQueryData(edited)).toEqual(driverGrid());
    expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(false);
    for (const key of moved.filter((key) => JSON.stringify(key) !== JSON.stringify(edited))) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    for (const key of untouched) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });

  describe("usePutDrivers with saves in flight", () => {
    const edited = [...aapl, "scenarios", 2, "bull", "drivers", "annual"];
    const row = (value: string) => [
      {
        driver_code: "gross_margin",
        kind: "value" as const,
        values: [{ fiscal_year: 2026, value }],
      },
    ];

    // Each PUT settles when the test says so, in any order.
    function controlled() {
      const settle: ((result: unknown) => void)[] = [];
      putDrivers.mockImplementation(
        (() => new Promise((resolve) => settle.push(resolve))) as never,
      );
      return settle;
    }

    function start() {
      const { queryClient, wrapper } = setup();
      queryClient.setQueryData(edited, driverGrid());
      const { result } = renderHook(() => usePutDrivers("AAPL"), { wrapper });
      return { queryClient, result };
    }

    it("reloads the drivers when a save fails", async () => {
      const settle = controlled();
      const { queryClient, result } = start();
      result.current.mutate({ id: 2, case: "bull", rows: row("0.5") });
      await waitFor(() => expect(settle).toHaveLength(1));

      settle[0]!(errorResult(422, { detail: "out of bounds" }));

      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(queryClient.getQueryData(edited)).toEqual(driverGrid()); // rolled back
      expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(true);
    });

    it("reloads the drivers when a held-back reply is followed by a failed save", async () => {
      const settle = controlled();
      const { queryClient, result } = start();
      result.current.mutate({ id: 2, case: "bull", rows: row("0.5") });
      result.current.mutate({ id: 2, case: "bull", rows: row("0.6") });
      await waitFor(() => expect(settle).toHaveLength(2));

      settle[0]!(okResult(driverGrid()));
      settle[1]!(errorResult(422, { detail: "out of bounds" }));

      await waitFor(() => expect(queryClient.isMutating()).toBe(0));
      expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(true);
    });

    it("reloads the drivers, not the older reply, when the replies arrive out of order", async () => {
      const settle = controlled();
      const { queryClient, result } = start();
      const older = driverGrid({ warnings: ["older"] });
      result.current.mutate({ id: 2, case: "bull", rows: row("0.5") });
      result.current.mutate({ id: 2, case: "bull", rows: row("0.6") });
      await waitFor(() => expect(settle).toHaveLength(2));

      settle[1]!(okResult(driverGrid({ warnings: ["newer"] })));
      await waitFor(() => expect(queryClient.isMutating()).toBe(1));
      settle[0]!(okResult(older));

      await waitFor(() => expect(queryClient.isMutating()).toBe(0));
      expect(queryClient.getQueryData(edited)).not.toEqual(older);
      expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(true);
    });
  });

  it("usePutDrivers shows the edit in its own case only", async () => {
    let settle: (result: unknown) => void = () => {};
    putDrivers.mockImplementation((() => new Promise((resolve) => (settle = resolve))) as never);
    const { queryClient, wrapper } = setup();
    const bull = [...aapl, "scenarios", 2, "bull", "drivers", "annual"];
    const bear = [...aapl, "scenarios", 2, "bear", "drivers", "annual"];
    queryClient.setQueryData(bull, driverGrid({ case: "bull" }));
    queryClient.setQueryData(bear, driverGrid({ case: "bear" }));
    const { result } = renderHook(() => usePutDrivers("AAPL"), { wrapper });

    result.current.mutate({
      id: 2,
      case: "bull",
      rows: [
        {
          driver_code: "revenue_growth",
          kind: "value",
          values: [{ fiscal_year: 2027, value: "0.08" }],
        },
      ],
    });

    await waitFor(() =>
      expect(queryClient.getQueryData<DriverGridOut>(bull)?.rows[0]?.own).toEqual([null, "0.08"]),
    );
    expect(queryClient.getQueryData<DriverGridOut>(bear)?.rows[0]?.own).toEqual([null, null]);
    settle(okResult(driverGrid({ case: "bull" })));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  describe("useResetCase", () => {
    const edited = [...aapl, "scenarios", 2, "bear", "drivers", "annual"];

    it("posts the reset of the case and takes its reply as the case's drivers", async () => {
      const reset = driverGrid({ case: "bear", warnings: ["reset"] });
      resetCase.mockResolvedValue(okResult(reset) as never);
      const { queryClient, wrapper } = setup();
      seed(queryClient);
      queryClient.setQueryData(edited, driverGrid({ case: "bear" }));
      const { result } = renderHook(() => useResetCase("AAPL"), { wrapper });

      result.current.mutate({ id: 2, case: "bear" });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(resetCase).toHaveBeenCalledWith({
        path: { ticker: "AAPL", scenario_id: 2, case: "bear" },
      });
      expect(queryClient.getQueryData(edited)).toEqual(reset);
      expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(false);
      // The rest of the scenario views (the other cases, forecasts, the comparison) are stale.
      for (const key of moved) {
        expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
      }
      for (const key of untouched) {
        expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
      }
    });

    it("keeps the API's reason when the case cannot be reset", async () => {
      resetCase.mockResolvedValue(
        errorResult(422, { detail: "No fiscal year to start from" }) as never,
      );
      const { queryClient, wrapper } = setup();
      queryClient.setQueryData(edited, driverGrid({ case: "bear" }));
      const { result } = renderHook(() => useResetCase("AAPL"), { wrapper });

      result.current.mutate({ id: 2, case: "bear" });
      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(result.current.error).toMatchObject({
        status: 422,
        detail: "No fiscal year to start from",
      });
      expect(queryClient.getQueryData(edited)).toEqual(driverGrid({ case: "bear" }));
    });

    it("does not apply its reply while a driver save runs: it reloads the grid instead", async () => {
      const settle: ((result: unknown) => void)[] = [];
      putDrivers.mockImplementation(
        (() => new Promise((resolve) => settle.push(resolve))) as never,
      );
      resetCase.mockResolvedValue(okResult(driverGrid({ case: "bear" })) as never);
      const { queryClient, wrapper } = setup();
      queryClient.setQueryData(edited, driverGrid({ case: "bear" }));
      const { result: put } = renderHook(() => usePutDrivers("AAPL"), { wrapper });
      const { result } = renderHook(() => useResetCase("AAPL"), { wrapper });
      put.current.mutate({ id: 2, case: "bear", rows: [] });
      await waitFor(() => expect(settle).toHaveLength(1));

      result.current.mutate({ id: 2, case: "bear" });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(true);
      settle[0]!(okResult(driverGrid({ case: "bear" })));
      await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    });
  });

  it("withDriverRows writes the sent rows in for display, leaving other drivers alone", () => {
    const grid = driverGrid();
    const shown = withDriverRows(grid, [
      {
        driver_code: "revenue_growth",
        kind: "value",
        values: [{ fiscal_year: 2027, value: "0.08" }],
      },
      { driver_code: "gross_margin", kind: "value", values: [] },
    ]);

    expect(shown.rows[0]).toMatchObject({
      own: [null, "0.08"],
      kind: "value",
      values: ["0.0234", "0.08"],
      sources: ["default", "own"],
    });
    // A cleared row: no own value and no kind; the value and source wait for the reply.
    expect(shown.rows[1]).toMatchObject({
      own: [null, null],
      kind: null,
      values: ["0.47", "0.4573"],
      sources: ["own", "default"],
    });
    expect(shown.rows.slice(2)).toEqual(grid.rows.slice(2));
    expect(grid.rows[0]?.own).toEqual([null, null]); // the cached grid is not mutated
  });

  it("withDriverRows leaves an offset year's resolved value unknown: the backend computes it", () => {
    const shown = withDriverRows(driverGrid(), [
      {
        driver_code: "revenue_growth",
        kind: "offset",
        values: [{ fiscal_year: 2026, value: "0.03" }],
      },
    ]);

    expect(shown.rows[0]).toMatchObject({
      own: ["0.03", null],
      kind: "offset",
      values: [null, "0.0234"],
      sources: ["offset", "default"],
    });
  });

  describe("quarterly drivers", () => {
    const annualKey = [...aapl, "scenarios", 2, "bull", "drivers", "annual"];
    const quarterlyKey = [...aapl, "scenarios", 2, "bull", "drivers", "quarterly"];
    const quarterRow = {
      driver_code: "gross_margin",
      kind: "value" as const,
      freq: "quarterly" as const,
      // A PUT row is the driver's whole row: Q1 kept, Q2 new.
      values: [
        { fiscal_year: 2026, fiscal_period: "Q1" as const, value: "0.48" },
        { fiscal_year: 2026, fiscal_period: "Q2" as const, value: "0.5" },
      ],
    };

    it("withDriverRows writes quarterly rows into a quarterly grid by quarter", () => {
      const shown = withDriverRows(quarterlyGrid(), [quarterRow]);
      expect(shown.rows[1]).toMatchObject({
        own: ["0.48", "0.5"],
        kind: "value",
        values: ["0.48", "0.5"],
        sources: ["own", "own"],
      });
    });

    it("withDriverRows drops a quarter the quarterly row no longer sets", () => {
      const shown = withDriverRows(quarterlyGrid(), [
        { ...quarterRow, values: [{ fiscal_year: 2026, fiscal_period: "Q1", value: "0.49" }] },
      ]);
      // Q1 is replaced; Q2 had no own value and keeps its value and source until the reply.
      expect(shown.rows[1]).toMatchObject({ own: ["0.49", null], values: ["0.49", "0.47"] });
      expect(shown.rows[1]?.sources).toEqual(["own", "year"]);
    });

    it("withDriverRows ignores the rows of the other frequency", () => {
      const annual = driverGrid();
      expect(withDriverRows(annual, [quarterRow])).toEqual(annual);
      const quarterly = quarterlyGrid();
      const yearRow = {
        driver_code: "gross_margin",
        kind: "value" as const,
        values: [{ fiscal_year: 2026, value: "0.5" }],
      };
      expect(withDriverRows(quarterly, [yearRow])).toEqual(quarterly);
    });

    it("usePutDrivers shows a quarterly edit in the quarterly grid only", async () => {
      let settle: (result: unknown) => void = () => {};
      putDrivers.mockImplementation((() => new Promise((resolve) => (settle = resolve))) as never);
      const { queryClient, wrapper } = setup();
      queryClient.setQueryData(annualKey, driverGrid({ case: "bull" }));
      queryClient.setQueryData(quarterlyKey, quarterlyGrid({ case: "bull" }));
      const { result } = renderHook(() => usePutDrivers("AAPL"), { wrapper });

      result.current.mutate({ id: 2, case: "bull", rows: [quarterRow] });

      await waitFor(() =>
        expect(queryClient.getQueryData<DriverGridOut>(quarterlyKey)?.rows[1]?.own).toEqual([
          "0.48",
          "0.5",
        ]),
      );
      expect(queryClient.getQueryData(annualKey)).toEqual(driverGrid({ case: "bull" }));
      settle(okResult(quarterlyGrid({ case: "bull" })));
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(putDrivers).toHaveBeenCalledWith({
        path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
        body: { rows: [quarterRow] },
      });
    });

    it("takes a quarterly reply as the quarterly grid and refreshes the annual one", async () => {
      const reply = quarterlyGrid({ case: "bull", warnings: ["saved"] });
      putDrivers.mockResolvedValue(okResult(reply) as never);
      const { queryClient, wrapper } = setup();
      queryClient.setQueryData(annualKey, driverGrid({ case: "bull" }));
      queryClient.setQueryData(quarterlyKey, quarterlyGrid({ case: "bull" }));
      const { result } = renderHook(() => usePutDrivers("AAPL"), { wrapper });

      result.current.mutate({ id: 2, case: "bull", rows: [quarterRow] });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(queryClient.getQueryData(quarterlyKey)).toEqual(reply);
      expect(queryClient.getQueryState(quarterlyKey)?.isInvalidated).toBe(false);
      expect(queryClient.getQueryState(annualKey)?.isInvalidated).toBe(true);
    });

    it("takes an annual reply (rows of both frequencies) as the annual grid and refreshes the quarterly one", async () => {
      const reply = driverGrid({ case: "bull", warnings: ["saved"] });
      putDrivers.mockResolvedValue(okResult(reply) as never);
      const { queryClient, wrapper } = setup();
      queryClient.setQueryData(annualKey, driverGrid({ case: "bull" }));
      queryClient.setQueryData(quarterlyKey, quarterlyGrid({ case: "bull" }));
      const { result } = renderHook(() => usePutDrivers("AAPL"), { wrapper });
      const clear = [
        { driver_code: "gross_margin", kind: "offset" as const, values: [] },
        {
          driver_code: "gross_margin",
          kind: "offset" as const,
          freq: "quarterly" as const,
          values: [],
        },
      ];

      result.current.mutate({ id: 2, case: "bull", rows: clear });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(queryClient.getQueryData(annualKey)).toEqual(reply);
      expect(queryClient.getQueryState(annualKey)?.isInvalidated).toBe(false);
      expect(queryClient.getQueryState(quarterlyKey)?.isInvalidated).toBe(true);
    });

    it("rolls back and reloads both frequencies when the save fails", async () => {
      putDrivers.mockResolvedValue(
        errorResult(422, { detail: "Q2 FY2026 is not a forecast quarter" }) as never,
      );
      const { queryClient, wrapper } = setup();
      queryClient.setQueryData(annualKey, driverGrid({ case: "bull" }));
      queryClient.setQueryData(quarterlyKey, quarterlyGrid({ case: "bull" }));
      const { result } = renderHook(() => usePutDrivers("AAPL"), { wrapper });

      result.current.mutate({ id: 2, case: "bull", rows: [quarterRow] });
      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(queryClient.getQueryData(quarterlyKey)).toEqual(quarterlyGrid({ case: "bull" }));
      expect(queryClient.getQueryState(quarterlyKey)?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(annualKey)?.isInvalidated).toBe(true);
    });
  });

  it("usePreviewDriverImport sends a dry run and invalidates nothing", async () => {
    importDrivers.mockResolvedValue(okResult(driverImport()) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => usePreviewDriverImport("AAPL"), { wrapper });
    result.current.mutate({ id: 2, case: "bull", file });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(importDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      body: { file, dry_run: true },
    });
    expect(result.current.data?.changes).toHaveLength(2);
    expectInvalidated(queryClient, false);
  });

  it("useConfirmDriverImport sends the real import and invalidates", async () => {
    importDrivers.mockResolvedValue(
      okResult(driverImport({ dry_run: false, grid: driverGrid() })) as never,
    );
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useConfirmDriverImport("AAPL"), { wrapper });
    result.current.mutate({ id: 2, case: "bull", file });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(importDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      body: { file, dry_run: false },
    });
    expectInvalidated(queryClient, true);
  });

  it("a refused driver file rejects with DriverFileFailed and every located error", async () => {
    const errors = [
      { row: 3, column: "F", message: "'abc' is not a number" },
      { row: null, column: null, message: "The file is empty" },
    ];
    importDrivers.mockResolvedValue(
      errorResult(422, { detail: "The file has errors", errors }) as never,
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => usePreviewDriverImport("AAPL"), { wrapper });
    result.current.mutate({ id: 2, case: "bull", file });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(DriverFileFailed);
    expect((result.current.error as DriverFileFailed).issues).toEqual(errors);
  });

  it("a plain 422 (no error list) stays an ApiError with its detail", async () => {
    importDrivers.mockResolvedValue(
      errorResult(422, { detail: "The file is larger than 1 MB" }) as never,
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => usePreviewDriverImport("AAPL"), { wrapper });
    result.current.mutate({ id: 2, case: "bull", file });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).not.toBeInstanceOf(DriverFileFailed);
    expect(result.current.error).toMatchObject({
      status: 422,
      detail: "The file is larger than 1 MB",
    });
  });
});
