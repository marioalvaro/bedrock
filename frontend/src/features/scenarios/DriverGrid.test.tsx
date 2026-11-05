// The annual driver grid of the Scenarios tab: cells, edits, vs Base mode and saving.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { setScale } from "@/lib/scale";
import { errorResult, okResult } from "@/test/responses";
import { bullGrid, comparison, driverGrid, modesOf, quarterlyGrid } from "@/test/scenarios";
import {
  getDrivers,
  putDrivers,
  compare,
  picker,
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
}));

// The comparison has its own test file; here its chart only needs to render nothing.
vi.mock("echarts-for-react/esm/core", () => ({ default: () => null }));

setupScenariosView();

describe("driver grid", () => {
  it("shows the actual years read-only and the forecast years tinted", async () => {
    await renderLoaded();
    for (const header of ["FY23A", "FY24A", "FY25A", "FY26E", "FY27E"]) {
      expect(screen.getByText(header)).toBeInTheDocument();
    }
    expect(cell("driver:revenue_growth", "h:2024")).toHaveTextContent("(2.8%)");
    expect(cell("driver:revenue_growth", "h:2024")).toHaveClass("text-muted-foreground");
    expect(cell("driver:revenue_growth", "f:2026")).toHaveClass("cell-forecast");
    expect(cell("driver:revenue_growth", "h:2024")).not.toHaveClass("cell-forecast");
  });

  it("heads each group and shows values by unit", async () => {
    await renderLoaded();
    expect(cell("group:Costs", "label")).toHaveTextContent("Costs");
    expect(cell("driver:gross_margin", "f:2026")).toHaveTextContent("47.0%");
    expect(cell("driver:receivable_days", "f:2026")).toHaveTextContent("60.5");
    expect(cell("driver:buybacks", "f:2026")).toHaveTextContent("87,737");
    expect(cell("driver:buybacks", "unit")).toHaveTextContent("USD millions");
  });

  it("names each cell's source", async () => {
    await renderLoaded();
    expect(
      within(cell("driver:gross_margin", "f:2026")).getByTitle("Set in this scenario"),
    ).toBeInTheDocument();
    expect(
      within(cell("driver:gross_margin", "f:2027")).getByTitle("Default: mean of FY23–FY25"),
    ).toBeInTheDocument();
    expect(cell("driver:tax_rate", "f:2026")).toHaveTextContent("Set");
    expect(within(cell("driver:tax_rate", "f:2026")).getByText("Set")).toHaveClass("text-negative");
    expect(cell("driver:receivable_days", "f:2027")).toHaveTextContent("Flat");
  });

  it("has no Mode column on Base, in any scenario", async () => {
    await renderLoaded();
    expect(screen.queryByRole("combobox", { name: /^Mode of/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(picker(), "2");
    await screen.findByText("Gross margin");
    expect(screen.queryByRole("combobox", { name: /^Mode of/ })).not.toBeInTheDocument();
  });

  it("has a Mode column on Bull and Bear, also in the default scenario", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=1&case=bull");
    expect(screen.getByRole("combobox", { name: "Mode of Gross margin" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Bear" }));
    await waitFor(() =>
      expect(getDrivers).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL", scenario_id: 1, case: "bear" },
        query: { freq: "annual" },
      }),
    );
    expect(await screen.findByRole("combobox", { name: "Mode of Gross margin" })).toBeVisible();
  });

  it("sends one PUT with the whole row on an edit", async () => {
    await renderLoaded();
    await edit("driver:gross_margin", "f:2027", "50");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      body: {
        rows: [
          {
            driver_code: "gross_margin",
            kind: "value",
            values: [
              { fiscal_year: 2026, value: "0.47" },
              { fiscal_year: 2027, value: "0.5" },
            ],
          },
        ],
      },
    });
  });

  it("drops the year of an emptied cell", async () => {
    await renderLoaded();
    await edit("driver:gross_margin", "f:2026", "");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      { driver_code: "gross_margin", kind: "value", values: [] },
    ]);
  });

  it("types USD in the page scale", async () => {
    setScale("B");
    await renderLoaded();
    await edit("driver:buybacks", "f:2026", "90");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows[0]?.values).toEqual([
      { fiscal_year: 2026, value: "90000000000" },
    ]);
  });

  it("says 'Enter a number' and sends nothing for text that is not a number", async () => {
    await renderLoaded();
    await edit("driver:gross_margin", "f:2027", "abc");
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a number");
    expect(putDrivers).not.toHaveBeenCalled();
  });

  it("sends nothing when the text is unchanged", async () => {
    await renderLoaded();
    await edit("driver:gross_margin", "f:2026", "47");
    expect(putDrivers).not.toHaveBeenCalled();
  });

  it("shows the API's reason when a value is refused", async () => {
    putDrivers.mockResolvedValue(
      errorResult(422, { detail: "gross_margin must be in [-1, 1]" }) as never,
    );
    await renderLoaded();
    await edit("driver:gross_margin", "f:2027", "500");
    expect(await screen.findByRole("alert")).toHaveTextContent("gross_margin must be in [-1, 1]");
  });

  it("resets a row with own values", async () => {
    await renderLoaded();
    expect(screen.queryByRole("button", { name: "Reset Revenue growth" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reset Gross margin" }));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      body: { rows: [{ driver_code: "gross_margin", kind: "value", values: [] }] },
    });
  });
});

describe("vs Base mode", () => {
  it("shows and edits the offset", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    expect(screen.getByRole("combobox", { name: "Mode of Revenue growth" })).toHaveValue("offset");
    expect(cell("driver:revenue_growth", "f:2026")).toHaveTextContent("+3.0 pts");
    expect(cell("driver:gross_margin", "f:2026")).toHaveTextContent("47.0%");
    await edit("driver:revenue_growth", "f:2026", "-5");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "bull" },
      body: {
        rows: [
          {
            driver_code: "revenue_growth",
            kind: "offset",
            values: [
              { fiscal_year: 2026, value: "-0.05" },
              { fiscal_year: 2027, value: "0.03" },
            ],
          },
        ],
      },
    });
  });

  it("clears the row's own values when the mode switches, after a confirm", async () => {
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        okResult(
          options.query.freq === "quarterly"
            ? quarterlyGrid({ case: "bull", year_modes: modesOf("annual") })
            : bullGrid(),
        ),
      )) as never);
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Switch Revenue growth to Value?");
    expect(dialog).toHaveTextContent(
      "Its own values in this case, annual and quarterly, are cleared",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Switch" }));
    // One kind per driver: the quarterly rows go with the annual ones.
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "bull" },
      body: {
        rows: [
          { driver_code: "revenue_growth", kind: "value", values: [] },
          { driver_code: "revenue_growth", kind: "value", freq: "quarterly", values: [] },
        ],
      },
    });
  });

  it("keeps the values when the switch is cancelled", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(putDrivers).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: "Mode of Revenue growth" })).toHaveValue("offset");
  });

  it("keeps a reset vs Base row in vs Base mode", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    const reset = bullGrid();
    reset.rows[0] = { ...reset.rows[0]!, own: [null, null], kind: null, sources: ["base", "base"] };
    putDrivers.mockResolvedValue(okResult(reset) as never); // the PUT replies with the saved grid
    await userEvent.click(screen.getByRole("button", { name: "Reset Revenue growth" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Reset Revenue growth" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("combobox", { name: "Mode of Revenue growth" })).toHaveValue("offset");
  });

  it("switches a row with no own values at once, and its edits are offsets", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    const mode = screen.getByRole("combobox", { name: "Mode of Gross margin" });
    expect(mode).toHaveValue("value");
    await userEvent.selectOptions(mode, "offset");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await edit("driver:gross_margin", "f:2027", "+1");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      {
        driver_code: "gross_margin",
        kind: "offset",
        values: [{ fiscal_year: 2027, value: "0.01" }],
      },
    ]);
  });
});

describe("saving an edit", () => {
  const driverCalls = (id: number) =>
    getDrivers.mock.calls.filter(([options]) => options.path.scenario_id === id).length;

  it("shows the typed value at once, before the save returns", async () => {
    putDrivers.mockReturnValue(new Promise(() => {}) as never);
    await renderLoaded();
    expect(cell("driver:gross_margin", "f:2027")).toHaveTextContent("45.7%");

    await edit("driver:gross_margin", "f:2027", "50");

    await waitFor(() => expect(cell("driver:gross_margin", "f:2027")).toHaveTextContent("50.0%"));
  });

  it("shows a typed offset at once in vs Base mode", async () => {
    putDrivers.mockReturnValue(new Promise(() => {}) as never);
    await renderLoaded("/c/AAPL/scenarios?case=bull");

    await edit("driver:revenue_growth", "f:2026", "-5");

    await waitFor(() =>
      expect(cell("driver:revenue_growth", "f:2026")).toHaveTextContent("-5.0 pts"),
    );
  });

  it("puts the previous value back and says why when the save fails", async () => {
    let fail: (value: unknown) => void = () => {};
    putDrivers.mockReturnValue(new Promise((resolve) => (fail = resolve)) as never);
    await renderLoaded();
    await edit("driver:gross_margin", "f:2027", "50");
    await waitFor(() => expect(cell("driver:gross_margin", "f:2027")).toHaveTextContent("50.0%"));

    fail(errorResult(422, { detail: "gross_margin must be in [-1, 1]" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("gross_margin must be in [-1, 1]");
    expect(cell("driver:gross_margin", "f:2027")).toHaveTextContent("45.7%");
  });

  it("takes the saved grid from the reply, without reloading the drivers", async () => {
    const saved = driverGrid();
    saved.rows[1] = {
      ...saved.rows[1]!,
      values: ["0.47", "0.52"],
      sources: ["own", "own"],
      own: ["0.47", "0.52"],
    };
    putDrivers.mockResolvedValue(okResult(saved) as never);
    // A comparison with data, so its background refresh is a new request (a pending one is
    // joined, not repeated).
    compare.mockResolvedValue(okResult(comparison()) as never);
    await renderLoaded();
    const loads = driverCalls(1);
    const compares = compare.mock.calls.length;

    await edit("driver:gross_margin", "f:2027", "50");

    await waitFor(() => expect(cell("driver:gross_margin", "f:2027")).toHaveTextContent("52.0%"));
    await waitFor(() => expect(compare.mock.calls.length).toBeGreaterThan(compares));
    expect(driverCalls(1)).toBe(loads);
  });
});
