// Year modes in the driver grid (M4 S10): the A | Q switch, the roll-up and locked cells.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { errorResult, okResult } from "@/test/responses";
import { bullGrid, driverGrid, modesOf, quarterlyGrid } from "@/test/scenarios";
import {
  getDrivers,
  putDrivers,
  setYearMode,
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

describe("year modes", () => {
  // The scenario's modes live on the server: the mocks keep them here and switch them on a PUT.
  const server = { mode: "annual" as "annual" | "quarterly" };

  function serve() {
    server.mode = "annual";
    getDrivers.mockImplementation(((options: {
      path: { scenario_id: number; case: "base" | "bull" | "bear" };
      query: { freq: "annual" | "quarterly" };
    }) => {
      const year_modes = modesOf(server.mode);
      const { case: scenarioCase } = options.path;
      if (options.query.freq === "quarterly") {
        return Promise.resolve(okResult(quarterlyGrid({ year_modes, case: scenarioCase })));
      }
      const grid = scenarioCase === "base" ? driverGrid({ year_modes }) : bullGrid();
      grid.year_modes = year_modes;
      if (server.mode === "quarterly") {
        grid.rows[0] = { ...grid.rows[0]!, rollup: ["0.0501", null] };
      }
      return Promise.resolve(okResult(grid));
    }) as never);
    setYearMode.mockImplementation((async ({
      body,
    }: {
      body: { mode: "annual" | "quarterly" };
    }) => {
      server.mode = body.mode;
      return okResult({ years: modesOf(body.mode) });
    }) as never);
  }

  const yearSwitch = (label: string) => screen.getByRole("radiogroup", { name: `${label} mode` });
  const modeRadio = (label: string, name: "Annual" | "By quarter") =>
    within(yearSwitch(label)).getByRole("radio", { name });
  const freqRadio = (name: "Annual" | "Quarterly") =>
    within(screen.getByRole("radiogroup", { name: "Driver frequency" })).getByRole("radio", {
      name,
    });

  async function toQuarterly() {
    await userEvent.click(freqRadio("Quarterly"));
    await screen.findByText("Q1 FY26E");
  }

  it("puts an Annual | By quarter switch in the header of each year of the span, none after it", async () => {
    serve();
    await renderLoaded();
    expect(modeRadio("FY26E", "Annual")).toBeChecked();
    expect(modeRadio("FY26E", "By quarter")).not.toBeChecked();
    expect(screen.queryByRole("radiogroup", { name: "FY27E mode" })).not.toBeInTheDocument();
    expect(screen.getByText("FY27E")).toBeInTheDocument();
  });

  it("keeps the switch short: A and Q, each naming its mode on hover and to a screen reader", async () => {
    serve();
    await renderLoaded();
    const group = yearSwitch("FY26E");
    expect(
      within(group)
        .getAllByRole("radio")
        .map((r) => r.textContent),
    ).toEqual(["A", "Q"]);
    expect(modeRadio("FY26E", "Annual")).toHaveAttribute("title", "Annual");
    expect(modeRadio("FY26E", "By quarter")).toHaveAttribute("title", "By quarter");
  });

  it("gives a year with a switch the same column width as the others", async () => {
    serve();
    await renderLoaded();
    const width = (column: string) =>
      (document.querySelector(`.ag-header-cell[col-id="${column}"]`) as HTMLElement).style.width;
    expect(width("f:2026")).not.toBe("");
    expect(width("f:2026")).toBe(width("f:2027"));
  });

  it("fits the switch over a year with a single quarter left", async () => {
    serve();
    getDrivers.mockImplementation(((options: { query: { freq: string } }) => {
      const grid = quarterlyGrid({ year_modes: modesOf("annual") });
      grid.forecast_periods = grid.forecast_periods.slice(1); // only Q2 FY26E is left
      grid.rows = grid.rows.map((r) => ({
        ...r,
        values: r.values.slice(1),
        sources: r.sources.slice(1),
        own: r.own.slice(1),
      }));
      return Promise.resolve(okResult(options.query.freq === "quarterly" ? grid : driverGrid()));
    }) as never);
    await renderLoaded();
    await userEvent.click(freqRadio("Quarterly"));
    await screen.findByText("Q2 FY26E");
    const group = document.querySelector(".ag-header-group-cell") as HTMLElement;
    const widthOf = (e: HTMLElement) => parseInt(e.style.width, 10);
    // The group header must be as wide as the label and the switch need (144 px).
    expect(widthOf(group)).toBeGreaterThanOrEqual(144);
    expect(within(group).getByText("FY26E")).toBeInTheDocument();
    expect(modeRadio("FY26E", "Annual")).toBeInTheDocument();
  });

  it("puts the switch before the year's name, which stays at the numbers' edge", async () => {
    serve();
    await renderLoaded();
    const label = within(
      document.querySelector('.ag-header-cell[col-id="f:2026"]') as HTMLElement,
    ).getByText("FY26E");
    expect(
      yearSwitch("FY26E").compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await userEvent.click(freqRadio("Quarterly"));
    await screen.findByText("Q1 FY26E");
    const group = document.querySelector(".ag-header-group-cell") as HTMLElement;
    expect(
      yearSwitch("FY26E").compareDocumentPosition(within(group).getByText("FY26E")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("explains the choice in one line above the grid", async () => {
    serve();
    await renderLoaded();
    expect(
      screen.getByText("Each year is set either as one annual value or quarter by quarter."),
    ).toBeInTheDocument();
  });

  it("switching to By quarter sends one PUT and shows the roll-up, read-only", async () => {
    serve();
    await renderLoaded();
    expect(cell("driver:revenue_growth", "f:2026")).toHaveTextContent("2.3%");
    await userEvent.click(modeRadio("FY26E", "By quarter"));
    await waitFor(() => expect(setYearMode).toHaveBeenCalledTimes(1));
    expect(setYearMode).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, fiscal_year: 2026 },
      body: { mode: "quarterly" },
    });
    await waitFor(() =>
      expect(cell("driver:revenue_growth", "f:2026")).toHaveTextContent("5.0%Quarters"),
    );
    expect(modeRadio("FY26E", "By quarter")).toBeChecked();
    expect(
      within(cell("driver:revenue_growth", "f:2026")).getByTitle(
        "Built from Q1–Q4. Switch FY26 to Annual to set it here.",
      ),
    ).toBeInTheDocument();
    await userEvent.dblClick(cell("driver:revenue_growth", "f:2026"));
    expect(cell("driver:revenue_growth", "f:2026").querySelector("input")).toBeNull();
    expect(putDrivers).not.toHaveBeenCalled();
  });

  it("never sends an annual value for a year set by quarter on an edit of another year", async () => {
    serve();
    server.mode = "quarterly";
    getDrivers.mockImplementation(((options: { query: { freq: string } }) => {
      const grid = driverGrid({ year_modes: modesOf("quarterly") });
      grid.rows[1] = { ...grid.rows[1]!, own: ["0.47", "0.46"], kind: "value" }; // FY26's is hidden
      return Promise.resolve(okResult(options.query.freq === "quarterly" ? quarterlyGrid() : grid));
    }) as never);
    await renderLoaded();
    await edit("driver:gross_margin", "f:2027", "50");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      {
        driver_code: "gross_margin",
        kind: "value",
        values: [{ fiscal_year: 2027, value: "0.5" }],
      },
    ]);
  });

  it("disables the switch while the mode is being saved", async () => {
    serve();
    let finish: (result: unknown) => void = () => {};
    setYearMode.mockImplementation((() => new Promise((resolve) => (finish = resolve))) as never);
    await renderLoaded();
    await userEvent.click(modeRadio("FY26E", "By quarter"));
    await waitFor(() => expect(modeRadio("FY26E", "Annual")).toBeDisabled());
    expect(modeRadio("FY26E", "By quarter")).toBeDisabled();
    finish(okResult({ years: modesOf("quarterly") }));
    await waitFor(() => expect(modeRadio("FY26E", "Annual")).toBeEnabled());
  });

  it("shows the API's reason when the switch is refused, leaving the mode as it was", async () => {
    serve();
    setYearMode.mockResolvedValue(
      errorResult(422, { detail: "FY2026 is not in the quarterly span" }) as never,
    );
    await renderLoaded();
    await userEvent.click(modeRadio("FY26E", "By quarter"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "FY2026 is not in the quarterly span",
    );
    expect(modeRadio("FY26E", "Annual")).toBeChecked();
  });

  describe("going back to annual", () => {
    async function openByQuarter() {
      serve();
      server.mode = "quarterly";
      await renderLoaded();
      expect(modeRadio("FY26E", "By quarter")).toBeChecked();
    }

    it("asks first, saying the quarter values of the three cases are deleted", async () => {
      await openByQuarter();
      await userEvent.click(modeRadio("FY26E", "Annual"));
      const dialog = await screen.findByRole("alertdialog");
      expect(dialog).toHaveTextContent(
        "FY26 returns to its annual values. The quarter values of Base, Bull and Bear are deleted.",
      );
      expect(setYearMode).not.toHaveBeenCalled();
    });

    it("sends nothing on Cancel", async () => {
      await openByQuarter();
      await userEvent.click(modeRadio("FY26E", "Annual"));
      await userEvent.click(
        within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
      );
      expect(setYearMode).not.toHaveBeenCalled();
      expect(modeRadio("FY26E", "By quarter")).toBeChecked();
    });

    it("puts the annual mode on confirm and makes the cell editable again", async () => {
      await openByQuarter();
      await userEvent.click(modeRadio("FY26E", "Annual"));
      await userEvent.click(
        within(await screen.findByRole("alertdialog")).getByRole("button", {
          name: "Return to annual",
        }),
      );
      await waitFor(() => expect(setYearMode).toHaveBeenCalledTimes(1));
      expect(setYearMode).toHaveBeenCalledWith({
        path: { ticker: "AAPL", scenario_id: 1, fiscal_year: 2026 },
        body: { mode: "annual" },
      });
      await waitFor(() => expect(modeRadio("FY26E", "Annual")).toBeChecked());
      await userEvent.dblClick(cell("driver:revenue_growth", "f:2026"));
      expect(cell("driver:revenue_growth", "f:2026").querySelector("input")).not.toBeNull();
    });
  });

  describe("in the quarterly grid", () => {
    it("puts the switch over the year's quarters", async () => {
      serve();
      await renderLoaded();
      await toQuarterly();
      expect(modeRadio("FY26E", "Annual")).toBeChecked();
      await userEvent.click(modeRadio("FY26E", "By quarter"));
      await waitFor(() => expect(setYearMode).toHaveBeenCalledTimes(1));
      expect(setYearMode.mock.lastCall?.[0].path.fiscal_year).toBe(2026);
    });

    it("locks the quarters of an annually set year, naming the year", async () => {
      serve();
      await renderLoaded();
      await toQuarterly();
      const quarter = cell("driver:gross_margin", "f:2026Q1");
      expect(quarter).toHaveTextContent("48.0%FY26"); // no "From": the year says it
      expect(
        within(quarter).getByTitle(
          "FY26 is set annually. Switch it to By quarter to edit quarters.",
        ),
      ).toBeInTheDocument();
      await userEvent.dblClick(quarter);
      expect(quarter.querySelector("input")).toBeNull();
    });

    it("unlocks them once the year is set by quarter", async () => {
      serve();
      await renderLoaded();
      await toQuarterly();
      await userEvent.click(modeRadio("FY26E", "By quarter"));
      await waitFor(() => expect(modeRadio("FY26E", "By quarter")).toBeChecked());
      await waitFor(() =>
        expect(cell("driver:gross_margin", "f:2026Q1")).not.toHaveTextContent("FY26"),
      );
      await edit("driver:gross_margin", "f:2026Q2", "50");
      await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
      expect(putDrivers.mock.lastCall?.[0].body.rows[0]).toMatchObject({
        freq: "quarterly",
        values: [
          { fiscal_year: 2026, fiscal_period: "Q1", value: "0.48" }, // the switch's fill, its own
          { fiscal_year: 2026, fiscal_period: "Q2", value: "0.5" },
        ],
      });
    });
  });

  it("shows the same modes for Bull and Bear: the switch is the scenario's", async () => {
    serve();
    server.mode = "quarterly";
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    expect(modeRadio("FY26E", "By quarter")).toBeChecked();
    await userEvent.click(modeRadio("FY26E", "Annual"));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Return to annual",
      }),
    );
    await waitFor(() => expect(setYearMode).toHaveBeenCalledTimes(1));
    expect(setYearMode.mock.lastCall?.[0].path).toEqual({
      ticker: "AAPL",
      scenario_id: 1,
      fiscal_year: 2026,
    }); // no case in the route
  });
});
