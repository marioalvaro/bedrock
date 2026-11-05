// The Scenarios view's test harness: the mocked API calls, a render on a router, cell helpers and
// the default mocks. Each test file mocks `@/api/generated/sdk.gen` itself (vi.mock is per file).
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, vi } from "vitest";

import {
  compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet,
  createScenarioApiV1CompaniesTickerScenariosPost,
  deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete,
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  listScenariosApiV1CompaniesTickerScenariosGet,
  putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut,
  resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost,
  setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut,
  updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut,
} from "@/api/generated/sdk.gen";
import { ScenariosView } from "@/features/scenarios/ScenariosView";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { segments } from "@/test/context";
import { LocationProbe } from "@/test/LocationProbe";
import { okResult } from "@/test/responses";
import { bullGrid, driverGrid, quarterlyGrid, scenarios } from "@/test/scenarios";

export const list = vi.mocked(listScenariosApiV1CompaniesTickerScenariosGet);
export const create = vi.mocked(createScenarioApiV1CompaniesTickerScenariosPost);
export const update = vi.mocked(updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut);
export const remove = vi.mocked(deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete);
export const getDrivers = vi.mocked(
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet,
);
export const putDrivers = vi.mocked(
  putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut,
);
export const resetCase = vi.mocked(
  resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost,
);
export const compare = vi.mocked(compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet);
export const getSegments = vi.mocked(getSegmentsApiV1CompaniesTickerSegmentsGet);
export const setYearMode = vi.mocked(
  setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut,
);

// The URL's query, as the view last left it.
export const seen = { search: "" };
const onSearch = (search: string) => {
  seen.search = search;
};

export function renderView(path = "/c/AAPL/scenarios") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="c/:ticker/:tab?"
            element={
              <>
                <ScenariosView ticker="AAPL" />
                <LocationProbe onSearch={onSearch} />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const picker = () => screen.getByRole("combobox", { name: "Scenario" }) as HTMLSelectElement;

export async function renderLoaded(path?: string) {
  renderView(path);
  await screen.findByText("Gross margin");
}

export const cell = (row: string, column: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${column}"]`) as HTMLElement;

// Opens the cell editor, replaces its text and commits with Enter.
export async function edit(row: string, column: string, text: string) {
  await userEvent.dblClick(cell(row, column));
  const input = (await waitFor(() => {
    const found = cell(row, column).querySelector("input");
    expect(found).not.toBeNull();
    return found;
  })) as HTMLInputElement;
  await userEvent.clear(input);
  if (text) await userEvent.type(input, text);
  await userEvent.keyboard("{Enter}");
}

// The scenario's KPIs: a count (volume), a per-unit price, and a percent (neither).
export function kpiSegments() {
  return segments({
    blocks: [
      {
        dimension: "kpi",
        metric: null,
        unallocated: null,
        series: [
          {
            id: 5,
            name: "iPhone units",
            metric: "iphone_units",
            unit: "count",
            display_order: 1,
            values: [],
          },
          {
            id: 6,
            name: "iPhone ASP",
            metric: "iphone_asp",
            unit: "USD_per_unit",
            display_order: 2,
            values: [],
          },
          {
            id: 7,
            name: "Gross margin target",
            metric: "gm_target",
            unit: "pct",
            display_order: 3,
            values: [],
          },
        ],
      },
    ],
  });
}

/** Registers the view's default mocks before each test and clears them after. */
export function setupScenariosView() {
  beforeEach(() => {
    setScale("M");
    list.mockResolvedValue(okResult(scenarios()) as never);
    getDrivers.mockImplementation(((options: {
      path: { scenario_id: number; case: "base" | "bull" | "bear" };
      query: { freq: "annual" | "quarterly" };
    }) => {
      const { scenario_id, case: scenarioCase } = options.path;
      const grid =
        options.query.freq === "quarterly"
          ? quarterlyGrid()
          : scenarioCase === "base"
            ? driverGrid()
            : bullGrid();
      return Promise.resolve(okResult({ ...grid, scenario_id, case: scenarioCase }));
    }) as never);
    putDrivers.mockResolvedValue(okResult(driverGrid()) as never);
    compare.mockReturnValue(new Promise(() => {}) as never);
    getSegments.mockResolvedValue(okResult(kpiSegments()) as never);
  });

  afterEach(() => {
    vi.clearAllMocks();
    setScale("M");
  });
}
