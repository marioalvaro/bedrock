// The annual driver grid's engines (M6): the Engine column, its PUT, the cross-check mark and the
// Engines button.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { driverEngines, engineChoices } from "@/test/engines";
import { errorResult, okResult } from "@/test/responses";
import { driverGrid, quarterlyGrid } from "@/test/scenarios";
import {
  cell,
  getDriverEngines,
  getDrivers,
  putEngines,
  renderLoaded,
  setupScenariosView,
} from "@/test/scenariosView";

vi.mock("@/api/generated/sdk.gen", () => ({
  listScenariosApiV1CompaniesTickerScenariosGet: vi.fn(),
  createScenarioApiV1CompaniesTickerScenariosPost: vi.fn(),
  updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut: vi.fn(),
  deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete: vi.fn(),
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet: vi.fn(),
  putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut: vi.fn(),
  resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost: vi.fn(),
  importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost: vi.fn(),
  compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet: vi.fn(),
  getSegmentsApiV1CompaniesTickerSegmentsGet: vi.fn(),
  setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut: vi.fn(),
  putEnginesApiV1CompaniesTickerScenariosScenarioIdEnginesPut: vi.fn(),
  getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet: vi.fn(),
}));

vi.mock("echarts-for-react/esm/core", () => ({ default: () => null }));

setupScenariosView();

const engineSelect = (label: string) =>
  screen.getByRole("combobox", { name: `${label} engine` }) as HTMLSelectElement;
const optionTexts = (select: HTMLSelectElement) =>
  Array.from(select.options).map((option) => option.textContent);
const headerIndex = (colId: string) =>
  Number(
    document.querySelector(`.ag-header-cell[col-id="${colId}"]`)?.getAttribute("aria-colindex"),
  );

// The driver grid's frequency toggle (the comparison below has its own).
const quarterlyRadio = () =>
  within(screen.getByRole("radiogroup", { name: "Driver frequency" })).getByRole("radio", {
    name: "Quarterly",
  });

// Serves `grid` as the annual grid of every case (the quarterly one stays the fixture's).
function serveAnnual(grid: ReturnType<typeof driverGrid>) {
  getDrivers.mockImplementation(((options: {
    path: { scenario_id: number; case: "base" | "bull" | "bear" };
    query: { freq: "annual" | "quarterly" };
  }) =>
    Promise.resolve(
      okResult({
        ...(options.query.freq === "quarterly" ? quarterlyGrid() : grid),
        scenario_id: options.path.scenario_id,
        case: options.path.case,
      }),
    )) as never);
}

describe("engine column", () => {
  it("sits after Unit, and before Mode on Bull", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=1&case=bull");
    expect(screen.getByText("Engine")).toBeInTheDocument();
    expect(headerIndex("engine")).toBe(headerIndex("unit") + 1);
    expect(headerIndex("mode")).toBe(headerIndex("engine") + 1);
  });

  it("shows what Auto picked and the shared scope", async () => {
    await renderLoaded();
    const select = engineSelect("Gross margin");
    expect(select).toHaveValue("auto");
    expect(select.selectedOptions[0]).toHaveTextContent("Auto · ETS");
    expect(select).toHaveAttribute("title", "Applies to Base, Bull and Bear");
  });

  it("offers STL only to a seasonal driver", async () => {
    await renderLoaded();
    expect(optionTexts(engineSelect("Gross margin"))).toEqual([
      "Auto · ETS",
      "Mean (3 yr)",
      "ARIMA",
      "ETS",
      "Blend",
      "STL",
    ]);
    expect(optionTexts(engineSelect("Revenue growth"))).toEqual([
      "Auto · Mean",
      "Mean (3 yr)",
      "ARIMA",
      "ETS",
      "Blend",
    ]);
  });

  it("shows a dash and no select for a driver with no numeric default", async () => {
    await renderLoaded();
    expect(cell("driver:tax_rate", "engine")).toHaveTextContent("—");
    expect(screen.queryByRole("combobox", { name: "Tax rate engine" })).not.toBeInTheDocument();
  });

  it("is not in the quarterly grid", async () => {
    await renderLoaded();
    await userEvent.click(quarterlyRadio());
    await waitFor(() => expect(screen.queryByText("Updating…")).not.toBeInTheDocument());
    await screen.findByText("Gross margin");
    expect(document.querySelector('[col-id="engine"]')).toBeNull();
    expect(screen.queryByRole("combobox", { name: /engine$/ })).not.toBeInTheDocument();
  });

  it("sends the one row on a change", async () => {
    putEngines.mockResolvedValue(okResult(engineChoices()) as never);
    await renderLoaded();
    await userEvent.selectOptions(engineSelect("Gross margin"), "mean");
    await waitFor(() => expect(putEngines).toHaveBeenCalledTimes(1));
    expect(putEngines).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1 },
      body: { rows: [{ driver_code: "gross_margin", engine: "mean" }] },
    });
  });

  it("disables the selects while the PUT runs", async () => {
    putEngines.mockReturnValue(new Promise(() => {}) as never);
    await renderLoaded();
    await userEvent.selectOptions(engineSelect("Gross margin"), "arima");
    await waitFor(() => expect(engineSelect("Gross margin")).toBeDisabled());
    expect(engineSelect("Revenue growth")).toBeDisabled();
  });

  it("shows the API's reason when the PUT fails", async () => {
    putEngines.mockResolvedValue(
      errorResult(422, {
        detail: "STL applies to ratio and days drivers only: gross_margin",
      }) as never,
    );
    await renderLoaded();
    await userEvent.selectOptions(engineSelect("Gross margin"), "stl");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "STL applies to ratio and days drivers only: gross_margin",
    );
    expect(engineSelect("Gross margin")).toBeEnabled();
  });

  it("is disabled while the other frequency's grid is the placeholder", async () => {
    await renderLoaded();
    getDrivers.mockReturnValue(new Promise(() => {}) as never);
    await userEvent.click(quarterlyRadio());
    await screen.findByText("Updating…");
    expect(engineSelect("Gross margin")).toBeDisabled();
  });
});

describe("cross-check mark", () => {
  it("marks a set value outside the engine's range and names the range", async () => {
    const grid = driverGrid();
    grid.rows[1] = {
      ...grid.rows[1]!,
      values: ["0.9", "0.4573"],
      own: ["0.9", null],
      check: [{ engine: "ets", p05: "0.4297", p95: "0.5073", outside: true }, null],
    };
    serveAnnual(grid);
    await renderLoaded();
    const value = within(cell("driver:gross_margin", "f:2026")).getByText("90.0%");
    expect(value).toHaveClass("cell-check-outside");
    expect(value).toHaveAttribute(
      "title",
      "Set in this scenario · Outside the ETS 90% range (43.0%–50.7%)",
    );
  });
});

describe("Engines button", () => {
  it("opens the driver's engine sheet", async () => {
    getDriverEngines.mockResolvedValue(okResult(driverEngines()) as never);
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Gross margin engines" }));
    expect(await screen.findByRole("dialog", { name: "Gross margin · engines" })).toBeVisible();
    expect(getDriverEngines).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      query: { code: "gross_margin" },
    });
    expect(await screen.findByRole("table", { name: "Engine forecasts" })).toBeVisible();
  });

  it("is offered only to a driver with a numeric default, and not in the quarterly grid", async () => {
    await renderLoaded();
    expect(screen.queryByRole("button", { name: "Tax rate engines" })).not.toBeInTheDocument();
    await userEvent.click(quarterlyRadio());
    await waitFor(() => expect(screen.queryByText("Updating…")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Gross margin engines" })).not.toBeInTheDocument();
  });
});
