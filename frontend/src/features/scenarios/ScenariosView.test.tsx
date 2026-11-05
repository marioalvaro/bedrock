import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { segments } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import {
  bullGrid,
  comparison,
  driverGrid,
  modesOf,
  quarterlyGrid,
  scenario,
  scenarios,
} from "@/test/scenarios";

import { ScenariosView } from "./ScenariosView";

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

const list = vi.mocked(listScenariosApiV1CompaniesTickerScenariosGet);
const create = vi.mocked(createScenarioApiV1CompaniesTickerScenariosPost);
const update = vi.mocked(updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut);
const remove = vi.mocked(deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete);
const getDrivers = vi.mocked(getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet);
const putDrivers = vi.mocked(putDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversPut);
const resetCase = vi.mocked(resetCaseApiV1CompaniesTickerScenariosScenarioIdCasesCaseResetPost);
const compare = vi.mocked(compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet);
const getSegments = vi.mocked(getSegmentsApiV1CompaniesTickerSegmentsGet);
const setYearMode = vi.mocked(
  setYearModeApiV1CompaniesTickerScenariosScenarioIdYearsFiscalYearModePut,
);

// The URL's query, as the view last left it.
const seen = { search: "" };

function LocationProbe() {
  const { search } = useLocation();
  useEffect(() => {
    seen.search = search;
  }, [search]);
  return null;
}

function renderView(path = "/c/AAPL/scenarios") {
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
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const picker = () => screen.getByRole("combobox", { name: "Scenario" }) as HTMLSelectElement;

async function renderLoaded(path?: string) {
  renderView(path);
  await screen.findByText("Gross margin");
}

const cell = (row: string, column: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${column}"]`) as HTMLElement;

// Opens the cell editor, replaces its text and commits with Enter.
async function edit(row: string, column: string, text: string) {
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
function kpiSegments() {
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

describe("picker", () => {
  it("lists the scenarios, the default first and picked by default", async () => {
    await renderLoaded();
    expect(
      within(picker())
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Main", "Cycle"]);
    expect(picker().value).toBe("1");
    expect(getDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      query: { freq: "annual" },
    });
  });

  it("picks the scenario of ?scenario and writes the choice back, keeping the case", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2&case=bull");
    expect(picker().value).toBe("2");
    await userEvent.selectOptions(picker(), "1");
    expect(new URLSearchParams(seen.search).get("scenario")).toBe("1");
    expect(new URLSearchParams(seen.search).get("case")).toBe("bull");
    await waitFor(() =>
      expect(getDrivers).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL", scenario_id: 1, case: "bull" },
        query: { freq: "annual" },
      }),
    );
  });

  it("creates a scenario and picks it", async () => {
    create.mockResolvedValue(
      okResult(scenario({ id: 4, name: "Recession", is_default: false }), 201) as never,
    );
    await renderLoaded();
    list.mockResolvedValue(
      okResult([
        ...scenarios(),
        scenario({ id: 4, name: "Recession", is_default: false }),
      ]) as never,
    );
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Name"), "  Recession ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(create).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, body: { name: "Recession" } });
    await waitFor(() => expect(picker().value).toBe("4"));
  });

  it("refuses an empty name", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a name");
    expect(create).not.toHaveBeenCalled();
  });

  it("shows the API's reason for a duplicate name", async () => {
    create.mockResolvedValue(
      errorResult(409, { detail: "A scenario named Cycle exists" }) as never,
    );
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Name"), "Cycle");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A scenario named Cycle exists");
  });

  it("renames the picked scenario", async () => {
    update.mockResolvedValue(okResult(scenario({ id: 2, name: "Cyclical" })) as never);
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Cycle");
    await userEvent.clear(name);
    await userEvent.type(name, "Cyclical");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2 },
      body: { name: "Cyclical" },
    });
  });

  it("offers no Delete for the default scenario", async () => {
    await renderLoaded();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("deletes a scenario after a confirmation and goes back to the default", async () => {
    remove.mockResolvedValue(okResult(null, 204) as never);
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Delete Cycle?");
    expect(dialog).toHaveTextContent("its Base, Bull and Bear cases");
    list.mockResolvedValue(okResult(scenarios().slice(0, 1)) as never);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", scenario_id: 2 } });
    await waitFor(() => expect(picker().value).toBe("1"));
  });

  it("shows the reason when a delete fails", async () => {
    remove.mockResolvedValue(
      errorResult(409, { detail: "The default scenario cannot be deleted" }) as never,
    );
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The default scenario cannot be deleted",
    );
  });

  it("links the driver files of the picked case", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2&case=bull");
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/v1/companies/AAPL/scenarios/2/cases/bull/drivers/export?format=csv",
    );
    expect(screen.getByRole("link", { name: "Export Excel" })).toHaveAttribute(
      "href",
      "/api/v1/companies/AAPL/scenarios/2/cases/bull/drivers/export?format=xlsx",
    );
  });
});

describe("import", () => {
  it("opens the driver import sheet for the picked case", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2&case=bear");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    const sheet = await screen.findByRole("dialog", { name: "Import drivers" });
    expect(within(sheet).getByLabelText("Driver file")).toBeInTheDocument();
  });
});

describe("compare", () => {
  it("compares the picked scenario's three cases under the grid", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2&case=bull");
    expect(screen.getByRole("region", { name: "Compare cases" })).toBeInTheDocument();
    expect(compare).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2 },
      query: { freq: "annual" },
    });
  });
});

describe("states", () => {
  it("shows Loading… while the scenarios load", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says when the scenarios cannot load", async () => {
    list.mockResolvedValue(errorResult(500, {}) as never);
    renderView();
    expect(await screen.findByText("Could not load the scenarios.")).toBeInTheDocument();
  });

  it("shows the API's reason when the scenarios cannot load", async () => {
    list.mockResolvedValue(errorResult(404, { detail: "Company not followed" }) as never);
    renderView();
    expect(await screen.findByText("Company not followed")).toBeInTheDocument();
  });

  it("shows the API's reason when the drivers cannot load", async () => {
    getDrivers.mockResolvedValue(
      errorResult(422, { detail: "No fiscal year to start from" }) as never,
    );
    renderView();
    expect(await screen.findByText("No fiscal year to start from")).toBeInTheDocument();
  });

  it("shows the grid's warnings", async () => {
    getDrivers.mockResolvedValue(
      okResult(
        driverGrid({ warnings: ["Offsets on revenue_growth are not used by the segments method"] }),
      ) as never,
    );
    await renderLoaded();
    expect(
      screen.getByText("Offsets on revenue_growth are not used by the segments method"),
    ).toBeInTheDocument();
  });
});

describe("settings", () => {
  it("says the settings apply to the three cases, and keeps them across a case switch", async () => {
    await renderLoaded();
    const form = screen.getByRole("form", { name: "Scenario settings" });
    expect(form).toHaveTextContent("Applies to Base, Bull and Bear");
    await userEvent.selectOptions(screen.getByLabelText("Revenue build"), "segments");
    await userEvent.click(screen.getByRole("radio", { name: "Bull" }));
    expect(screen.getByLabelText("Revenue build")).toHaveValue("segments"); // the draft stays
  });

  it("shows the picked scenario's settings with Save disabled until a change", async () => {
    await renderLoaded();
    expect(screen.getByLabelText("Revenue build")).toHaveValue("growth");
    const save = screen.getByRole("button", { name: "Save settings" });
    expect(save).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Revenue build"), "segments");
    expect(save).toBeEnabled();
  });

  it("shows no horizon: it is fixed, so there is nothing to set or state", async () => {
    await renderLoaded();
    expect(screen.queryByText(/horizon/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/8 quarters/)).not.toBeInTheDocument();
  });

  it("saves the revenue build alone, with no horizon", async () => {
    update.mockResolvedValue(okResult(scenario()) as never);
    await renderLoaded();
    await userEvent.selectOptions(screen.getByLabelText("Revenue build"), "segments");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1 },
      body: {
        revenue_method: "segments",
        segment_dimension: "business",
        volume_kpi: null,
        price_kpi: null,
      },
    });
  });

  it("asks for a segment dimension on Segments", async () => {
    update.mockResolvedValue(okResult(scenario()) as never);
    await renderLoaded();
    expect(screen.queryByLabelText("Segment dimension")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Revenue build"), "segments");
    await userEvent.selectOptions(screen.getByLabelText("Segment dimension"), "geo");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(update.mock.lastCall?.[0].body).toMatchObject({
      revenue_method: "segments",
      segment_dimension: "geo",
    });
  });

  it("lists count KPIs for volume and per-unit KPIs for price", async () => {
    update.mockResolvedValue(okResult(scenario()) as never);
    await renderLoaded();
    await userEvent.selectOptions(screen.getByLabelText("Revenue build"), "volume_price");
    const volume = await screen.findByLabelText("Volume KPI");
    const options = (select: HTMLElement) =>
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent);
    expect(options(volume)).toEqual(["Choose…", "iPhone units"]);
    expect(options(screen.getByLabelText("Price KPI"))).toEqual(["Choose…", "iPhone ASP"]);
    await userEvent.selectOptions(volume, "iphone_units");
    await userEvent.selectOptions(screen.getByLabelText("Price KPI"), "iphone_asp");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(update.mock.lastCall?.[0].body).toMatchObject({
      revenue_method: "volume_price",
      volume_kpi: "iphone_units",
      price_kpi: "iphone_asp",
    });
    expect(getSegments).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { freq: "annual" },
    });
  });

  it("explains an empty KPI list", async () => {
    getSegments.mockResolvedValue(okResult(segments({ blocks: [] })) as never);
    await renderLoaded();
    await userEvent.selectOptions(screen.getByLabelText("Revenue build"), "volume_price");
    expect(
      await screen.findByText("Add a count KPI and a price KPI in Segments"),
    ).toBeInTheDocument();
  });

  it("shows the API's reason when the settings are refused", async () => {
    update.mockResolvedValue(
      errorResult(422, { detail: "segments needs a segment_dimension" }) as never,
    );
    await renderLoaded();
    await userEvent.selectOptions(screen.getByLabelText("Revenue build"), "segments");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "segments needs a segment_dimension",
    );
  });
});

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

describe("new scenario", () => {
  async function openNew() {
    create.mockResolvedValue(
      okResult(scenario({ id: 4, name: "Recession", is_default: false }), 201) as never,
    );
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Name"), "Recession");
  }

  it("offers the revenue build, starting from the default scenario's", async () => {
    await openNew();
    const build = screen.getByLabelText("New scenario revenue build");
    expect(build).toHaveValue("");
    expect(
      within(build)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Same as Main", "Growth", "Segments"]);
  });

  it("builds on Growth when picked", async () => {
    await openNew();
    await userEvent.selectOptions(screen.getByLabelText("New scenario revenue build"), "growth");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(create).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { name: "Recession", revenue_method: "growth" },
    });
  });

  it("builds on the business segments when Segments is picked", async () => {
    await openNew();
    await userEvent.selectOptions(screen.getByLabelText("New scenario revenue build"), "segments");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(create).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { name: "Recession", revenue_method: "segments", segment_dimension: "business" },
    });
  });

  it("has no revenue build when renaming", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(screen.queryByLabelText("New scenario revenue build")).not.toBeInTheDocument();
  });
});

describe("case toggle", () => {
  const radio = (name: string) => screen.getByRole("radio", { name });

  it("offers Base, Bull and Bear, Base picked by default", async () => {
    await renderLoaded();
    const group = screen.getByRole("radiogroup", { name: "Case" });
    expect(
      within(group)
        .getAllByRole("radio")
        .map((r) => r.textContent),
    ).toEqual(["Base", "Bull", "Bear"]);
    expect(radio("Base")).toBeChecked();
  });

  it("picks the case of ?case", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=bear");
    expect(radio("Bear")).toBeChecked();
    expect(getDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "bear" },
      query: { freq: "annual" },
    });
  });

  it("falls back to Base for an unknown case", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=sideways");
    expect(radio("Base")).toBeChecked();
  });

  it("asks for that case's drivers and writes ?case, keeping ?scenario", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    await userEvent.click(radio("Bull"));
    expect(new URLSearchParams(seen.search).get("case")).toBe("bull");
    expect(new URLSearchParams(seen.search).get("scenario")).toBe("2");
    await waitFor(() =>
      expect(getDrivers).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
        query: { freq: "annual" },
      }),
    );
    await waitFor(() =>
      expect(cell("driver:revenue_growth", "f:2026")).toHaveTextContent("+3.0 pts"),
    );
  });

  it("edits go to the picked case", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await edit("driver:gross_margin", "f:2027", "+1");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers.mock.lastCall?.[0].path).toEqual({
      ticker: "AAPL",
      scenario_id: 1,
      case: "bull",
    });
  });
});

describe("reset a case", () => {
  const resetButton = (case_: string) => screen.getByRole("button", { name: `Reset ${case_}` });

  it("asks first, with Base's text", async () => {
    await renderLoaded();
    await userEvent.click(resetButton("Base"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Reset Base?");
    expect(dialog).toHaveTextContent("Every driver of Base goes back to its default.");
    expect(resetCase).not.toHaveBeenCalled();
  });

  it.each([
    ["bull", "Bull"],
    ["bear", "Bear"],
  ])("asks first, with the default offsets' text on %s", async (slug, name) => {
    await renderLoaded(`/c/AAPL/scenarios?case=${slug}`);
    await userEvent.click(resetButton(name));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(`Reset ${name}?`);
    expect(dialog).toHaveTextContent(
      "Its own values are removed and the default offsets come back (+3 pts revenue growth, +1 pt gross margin; each segment's growth on Segments).",
    );
    expect(resetCase).not.toHaveBeenCalled();
  });

  it("sends nothing on Cancel", async () => {
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await userEvent.click(resetButton("Bull"));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(resetCase).not.toHaveBeenCalled();
  });

  it("posts the reset of the picked case on OK and shows the reply", async () => {
    const reset = bullGrid();
    reset.rows[0] = {
      ...reset.rows[0]!,
      values: ["0.0534", "0.0534"],
      sources: ["offset", "offset"],
    };
    reset.rows[1] = {
      ...reset.rows[1]!,
      values: ["0.47", "0.4573"],
      own: [null, null],
      kind: null,
      sources: ["base", "default"],
    };
    resetCase.mockResolvedValue(okResult(reset) as never);
    await renderLoaded("/c/AAPL/scenarios?scenario=2&case=bull");
    await userEvent.click(resetButton("Bull"));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Reset" }),
    );
    expect(resetCase).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
    });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("shows the API's reason when the reset is refused", async () => {
    resetCase.mockResolvedValue(
      errorResult(422, { detail: "No fiscal year to start from" }) as never,
    );
    await renderLoaded();
    await userEvent.click(resetButton("Base"));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Reset" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("No fiscal year to start from");
  });
});

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

  it("does not clear a quarter of a by-quarter year: it says why and sends nothing", async () => {
    await openQuarterly();
    await edit("driver:gross_margin", "f:2026Q1", "");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Q1 FY26 cannot be cleared (FY26 is set by quarter)",
    );
    expect(putDrivers).not.toHaveBeenCalled();
    expect(cell("driver:gross_margin", "f:2026Q1")).toHaveTextContent("48.0%");
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

  it("offers no row Reset in the quarterly grid of a by-quarter year (its quarters cannot be cleared)", async () => {
    await openQuarterly();
    // Gross margin has an own quarter value, but a reset would leave the year without quarters.
    expect(screen.queryByRole("button", { name: "Reset Gross margin" })).not.toBeInTheDocument();
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
    await userEvent.click(within(dialog).getByRole("button", { name: "Switch" }));
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    // FY26 is set by quarter: its quarters stay, at the values they resolve to.
    expect(putDrivers.mock.lastCall?.[0].body.rows).toEqual([
      { driver_code: "revenue_growth", kind: "value", values: [] },
      {
        driver_code: "revenue_growth",
        kind: "value",
        freq: "quarterly",
        values: [
          { fiscal_year: 2026, fiscal_period: "Q1", value: "0.0534" },
          { fiscal_year: 2026, fiscal_period: "Q2", value: "0.0234" },
        ],
      },
    ]);
  });

  it("clears the annual row alone when the company has no quarterly history", async () => {
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        options.query.freq === "quarterly"
          ? errorResult(422, { detail: "No quarterly history" })
          : okResult(bullGrid()),
      )) as never);
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

  it("sends nothing on a mode switch when the quarterly grid fails for another reason", async () => {
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(
        options.query.freq === "quarterly"
          ? errorResult(422, { detail: "Q1 FY2025 has no value" })
          : okResult(bullGrid()),
      )) as never);
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Switch" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Q1 FY2025 has no value");
    expect(putDrivers).not.toHaveBeenCalled();
  });

  it("clears only the annual row of a driver the quarterly grid does not list", async () => {
    const grid = bullQuarterly();
    grid.rows = grid.rows.filter((row) => row.code !== "revenue_growth");
    getDrivers.mockImplementation(((options: { query: { freq: string } }) =>
      Promise.resolve(okResult(options.query.freq === "quarterly" ? grid : bullGrid()))) as never);
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
          { fiscal_year: 2026, fiscal_period: "Q1", value: "0.48" },
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

  it("explains in the mode-switch confirm that a by-quarter year keeps its quarters", async () => {
    serve();
    server.mode = "quarterly";
    await renderLoaded("/c/AAPL/scenarios?case=bull");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "Years set by quarter keep their quarters",
    );
  });
});
