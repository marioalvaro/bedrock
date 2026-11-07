// The quarterly driver grid of the Scenarios tab (M4 S8).
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { errorResult, okResult } from "@/test/responses";
import { bullGrid, driverGrid, modesOf, quarterlyGrid } from "@/test/scenarios";
import {
  getDrivers,
  putDrivers,
  renderLoaded,
  cell,
  edit,
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

// The comparison has its own test file; here its chart only needs to render nothing.
vi.mock("echarts-for-react/esm/core", () => ({ default: () => null }));

setupScenariosView();

describe("quarterly drivers", () => {
  // The comparison below the grid has its own Annual | Quarterly toggle.
  const freqRadio = (name: "Annual" | "Quarterly") =>
    within(screen.getByRole("radiogroup", { name: "Driver frequency" })).getByRole("radio", {
      name,
    });
  const quarterlyCalls = () =>
    getDrivers.mock.calls.filter(([options]) => options.query?.freq === "quarterly");

  async function openQuarterly(path?: string) {
    await renderLoaded(path);
    await userEvent.click(freqRadio("Quarterly"));
    await screen.findByText("Q1 FY26E");
  }

  // Bull's quarterly grid: revenue growth is an offset (+3 pts in Q1, Q2 follows its year).
  function bullQuarterly() {
    const grid = quarterlyGrid({ case: "bull" });
    grid.rows[0] = {
      ...grid.rows[0]!,
      values: ["0.0534", "0.0234"],
      sources: ["offset", "year"],
      own: ["0.03", null],
      kind: "offset",
    };
    return grid;
  }

  it("offers Annual | Quarterly over the grid, Annual picked", async () => {
    await renderLoaded();
    expect(freqRadio("Annual")).toBeChecked();
    expect(freqRadio("Quarterly")).not.toBeChecked();
    expect(quarterlyCalls()).toHaveLength(0);
  });

  it("asks for the quarterly grid and shows the actual and the forecast quarters", async () => {
    await openQuarterly();
    expect(getDrivers).toHaveBeenLastCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      query: { freq: "quarterly" },
    });
    for (const header of ["Q2 FY25A", "Q3 FY25A", "Q4 FY25A", "Q1 FY26E", "Q2 FY26E"]) {
      expect(screen.getByText(header)).toBeInTheDocument();
    }
    // The year is a header over its quarters, with no annual column of its own.
    expect(screen.getAllByText("FY26E")).toHaveLength(1);
    expect(document.querySelector('[col-id="f:2026"]')).toBeNull();
    expect(cell("driver:gross_margin", "h:2025Q3")).toHaveTextContent("46.5%");
    expect(cell("driver:gross_margin", "h:2025Q3")).toHaveClass("text-muted-foreground");
    expect(cell("driver:gross_margin", "f:2026Q1")).toHaveClass("cell-forecast");
    expect(cell("driver:gross_margin", "f:2026Q1")).toHaveTextContent("48.0%");
  });

  it("keeps the grid mounted, read-only, while the quarters load", async () => {
    let settle: (result: unknown) => void = () => {};
    await renderLoaded();
    getDrivers.mockImplementation((() => new Promise((resolve) => (settle = resolve))) as never);
    await userEvent.click(freqRadio("Quarterly"));

    expect(screen.getByText("Updating…")).toBeInTheDocument();
    expect(cell("driver:gross_margin", "f:2026")).toHaveTextContent("47.0%"); // the annual grid
    await userEvent.dblClick(cell("driver:gross_margin", "f:2026"));
    expect(cell("driver:gross_margin", "f:2026").querySelector("input")).toBeNull();
    // The row actions would act on the old frequency's grid: they wait too.
    expect(screen.getByRole("button", { name: "Reset Gross margin" })).toBeDisabled();

    settle(okResult(quarterlyGrid()));
    await screen.findByText("Q1 FY26E");
    expect(screen.queryByText("Updating…")).not.toBeInTheDocument();
  });

  it("shows a quarter that takes its year's value muted, with the year in its tooltip", async () => {
    await openQuarterly();
    const quarter = cell("driver:gross_margin", "f:2026Q2");
    expect(quarter).toHaveTextContent("47.0%");
    expect(within(quarter).getByText("47.0%")).toHaveClass("text-muted-foreground");
    expect(within(quarter).getByTitle("From FY26 (annual)")).toBeInTheDocument();
    expect(within(cell("driver:gross_margin", "f:2026Q1")).getByTitle("Set in this scenario")).toBe(
      within(cell("driver:gross_margin", "f:2026Q1")).getByText("48.0%"),
    );
  });

  it("sends one quarterly PUT with that driver's quarter values on an edit", async () => {
    await openQuarterly();
    await edit("driver:gross_margin", "f:2026Q2", "50");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      body: {
        rows: [
          {
            driver_code: "gross_margin",
            kind: "value",
            freq: "quarterly",
            values: [
              { fiscal_year: 2026, fiscal_period: "Q1", value: "0.48" },
              { fiscal_year: 2026, fiscal_period: "Q2", value: "0.5" },
            ],
          },
        ],
      },
    });
  });

  it("starts the editor of a quarter that follows its year from the year's value", async () => {
    await openQuarterly();
    await userEvent.dblClick(cell("driver:gross_margin", "f:2026Q2"));
    const input = await waitFor(() => {
      const found = cell("driver:gross_margin", "f:2026Q2").querySelector("input");
      expect(found).not.toBeNull();
      return found as HTMLInputElement;
    });
    expect(input.value).toBe("47");
  });

  it("sends nothing when a following quarter's text is left unchanged", async () => {
    await openQuarterly();
    await edit("driver:gross_margin", "f:2026Q2", "47");
    expect(putDrivers).not.toHaveBeenCalled();
  });

  it("clears a quarter of a by-quarter year by sending the row without it", async () => {
    await openQuarterly();
    await edit("driver:gross_margin", "f:2026Q1", "");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      { driver_code: "gross_margin", kind: "value", freq: "quarterly", values: [] },
    ]);
  });

  it("shows the typed quarter at once, and takes the reply as the quarterly grid", async () => {
    const reply = quarterlyGrid({ warnings: ["saved"] });
    reply.rows[1] = { ...reply.rows[1]!, values: ["0.48", "0.5"], own: ["0.48", "0.5"] };
    putDrivers.mockResolvedValue(okResult(reply) as never);
    await openQuarterly();
    await edit("driver:gross_margin", "f:2026Q2", "50");
    expect(await screen.findByText("saved")).toBeInTheDocument();
    expect(cell("driver:gross_margin", "f:2026Q2")).toHaveTextContent("50.0%");
    expect(quarterlyCalls()).toHaveLength(1); // the reply was taken, not reloaded
  });

  it("offers the row Reset in the quarterly grid of a by-quarter year (its quarters follow Base)", async () => {
    await openQuarterly();
    await userEvent.click(screen.getByRole("button", { name: "Reset Gross margin" }));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      { driver_code: "gross_margin", kind: "value", freq: "quarterly", values: [] },
    ]);
  });

  it("resets a row's own quarter values when no year is set by quarter", async () => {
    const grid = quarterlyGrid({ year_modes: modesOf("annual") });
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        okResult(options.query.freq === "quarterly" ? grid : driverGrid()),
      )) as never);
    await openQuarterly();
    await userEvent.click(screen.getByRole("button", { name: "Reset Gross margin" }));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      body: {
        rows: [{ driver_code: "gross_margin", kind: "value", freq: "quarterly", values: [] }],
      },
    });
  });

  it("edits a quarter's offset in vs Base mode", async () => {
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        okResult(options.query.freq === "quarterly" ? bullQuarterly() : bullGrid()),
      )) as never);
    await openQuarterly("/c/AAPL/scenarios?case=bull");
    expect(cell("driver:revenue_growth", "f:2026Q1")).toHaveTextContent("+3.0 pts");
    expect(cell("driver:revenue_growth", "f:2026Q2")).toHaveTextContent("2.3%");
    await edit("driver:revenue_growth", "f:2026Q2", "+1");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      {
        driver_code: "revenue_growth",
        kind: "offset",
        freq: "quarterly",
        values: [
          { fiscal_year: 2026, fiscal_period: "Q1", value: "0.03" },
          { fiscal_year: 2026, fiscal_period: "Q2", value: "0.01" },
        ],
      },
    ]);
  });

  it("clears the annual and the quarterly rows on a mode switch, saying so", async () => {
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        okResult(options.query.freq === "quarterly" ? bullQuarterly() : bullGrid()),
      )) as never);
    await openQuarterly("/c/AAPL/scenarios?case=bull");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("annual and quarterly");
    expect(dialog).not.toHaveTextContent("keep their quarters");
    await userEvent.click(within(dialog).getByRole("button", { name: "Switch" }));
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    // FY26 is set by quarter: its quarters are cleared too and then follow Base.
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      { driver_code: "revenue_growth", kind: "value", values: [] },
      { driver_code: "revenue_growth", kind: "value", freq: "quarterly", values: [] },
    ]);
  });

  it("clears the annual row alone when the company has no quarterly history", async () => {
    getDrivers.mockResolvedValue(okResult({ ...bullGrid(), has_quarters: false }) as never);
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Switch" }),
    );
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      { driver_code: "revenue_growth", kind: "value", values: [] },
    ]);
    expect(quarterlyCalls()).toHaveLength(0); // the grid says so: nothing to fetch
  });

  it("leaves the Mode select alone while the quarters load", async () => {
    let settle: (result: unknown) => void = () => {};
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    getDrivers.mockImplementation((() => new Promise((resolve) => (settle = resolve))) as never);
    await userEvent.click(freqRadio("Quarterly"));
    expect(await screen.findByText("Updating…")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Mode of Revenue growth" })).toBeDisabled();
    settle(okResult(bullQuarterly()));
    await screen.findByText("Q1 FY26E");
    expect(screen.getByRole("combobox", { name: "Mode of Revenue growth" })).toBeEnabled();
  });

  it("clears only the annual row of a driver that cannot be set per quarter", async () => {
    const grid = bullGrid();
    grid.rows[0] = { ...grid.rows[0]!, quarterly: false };
    getDrivers.mockResolvedValue(okResult(grid) as never);
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Switch" }),
    );
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      { driver_code: "revenue_growth", kind: "value", values: [] },
    ]);
    expect(quarterlyCalls()).toHaveLength(0);
  });

  it("names the per-year drivers after a case switch on Quarterly too", async () => {
    const grid = quarterlyGrid();
    grid.rows = grid.rows.filter((row) => row.code !== "tax_rate");
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        okResult(options.query.freq === "quarterly" ? grid : driverGrid()),
      )) as never);
    await openQuarterly();
    expect(await screen.findByText("Set per year only: Tax rate.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Bull" }));
    expect(await screen.findByText("Set per year only: Tax rate.")).toBeInTheDocument();
  });

  it("names the drivers that are set per year only", async () => {
    const grid = quarterlyGrid();
    grid.rows = grid.rows.filter((row) => row.code !== "tax_rate");
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        okResult(options.query.freq === "quarterly" ? grid : driverGrid()),
      )) as never);
    await renderLoaded();
    expect(screen.queryByText(/set per year only/i)).not.toBeInTheDocument();
    await userEvent.click(freqRadio("Quarterly"));
    expect(await screen.findByText("Set per year only: Tax rate.")).toBeInTheDocument();
  });

  it("has no note when every driver has quarters", async () => {
    await openQuarterly();
    expect(screen.queryByText(/set per year only/i)).not.toBeInTheDocument();
  });

  it("shows the API's warnings in the quarterly view", async () => {
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        okResult(
          options.query.freq === "quarterly"
            ? quarterlyGrid({ forecast_periods: [], warnings: ["No forecast quarters"] })
            : driverGrid(),
        ),
      )) as never);
    await renderLoaded();
    await userEvent.click(freqRadio("Quarterly"));
    expect(await screen.findByText("No forecast quarters")).toBeInTheDocument();
  });

  it("shows the API's reason when there is no quarterly history, and goes back to Annual", async () => {
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        options.query.freq === "quarterly"
          ? errorResult(422, { detail: "No quarterly history" })
          : okResult(driverGrid()),
      )) as never);
    await renderLoaded();
    await userEvent.click(freqRadio("Quarterly"));
    expect(await screen.findByText("No quarterly history")).toBeInTheDocument();
    await userEvent.click(freqRadio("Annual"));
    expect(await screen.findByText("FY26E")).toBeInTheDocument();
  });

  it("keeps Quarterly across a case switch", async () => {
    await openQuarterly();
    await userEvent.click(screen.getByRole("radio", { name: "Bull" }));
    await waitFor(() =>
      expect(getDrivers).toHaveBeenCalledWith({
        path: { ticker: "AAPL", scenario_id: 1, case: "bull" },
        query: { freq: "quarterly" },
      }),
    );
  });
});
