import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  compareScenariosApiV1CompaniesTickerScenariosCompareGet,
  createScenarioApiV1CompaniesTickerScenariosPost,
  deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete,
  getDriversApiV1CompaniesTickerScenariosScenarioIdDriversGet,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  listScenariosApiV1CompaniesTickerScenariosGet,
  putDriversApiV1CompaniesTickerScenariosScenarioIdDriversPut,
  updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { segments } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import { bullGrid, comparison, driverGrid, scenario, scenarios } from "@/test/scenarios";

import { ScenariosView } from "./ScenariosView";

vi.mock("@/api/generated/sdk.gen", () => ({
  listScenariosApiV1CompaniesTickerScenariosGet: vi.fn(),
  createScenarioApiV1CompaniesTickerScenariosPost: vi.fn(),
  updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut: vi.fn(),
  deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete: vi.fn(),
  getDriversApiV1CompaniesTickerScenariosScenarioIdDriversGet: vi.fn(),
  putDriversApiV1CompaniesTickerScenariosScenarioIdDriversPut: vi.fn(),
  importDriversApiV1CompaniesTickerScenariosScenarioIdDriversImportPost: vi.fn(),
  compareScenariosApiV1CompaniesTickerScenariosCompareGet: vi.fn(),
  getSegmentsApiV1CompaniesTickerSegmentsGet: vi.fn(),
}));

// The comparison has its own test file; here its chart only needs to render nothing.
vi.mock("echarts-for-react/esm/core", () => ({ default: () => null }));

const list = vi.mocked(listScenariosApiV1CompaniesTickerScenariosGet);
const create = vi.mocked(createScenarioApiV1CompaniesTickerScenariosPost);
const update = vi.mocked(updateScenarioApiV1CompaniesTickerScenariosScenarioIdPut);
const remove = vi.mocked(deleteScenarioApiV1CompaniesTickerScenariosScenarioIdDelete);
const getDrivers = vi.mocked(getDriversApiV1CompaniesTickerScenariosScenarioIdDriversGet);
const putDrivers = vi.mocked(putDriversApiV1CompaniesTickerScenariosScenarioIdDriversPut);
const compare = vi.mocked(compareScenariosApiV1CompaniesTickerScenariosCompareGet);
const getSegments = vi.mocked(getSegmentsApiV1CompaniesTickerSegmentsGet);

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
  getDrivers.mockImplementation(((options: { path: { scenario_id: number } }) =>
    Promise.resolve(
      okResult(
        options.path.scenario_id === 1
          ? driverGrid()
          : { ...bullGrid(), scenario_id: options.path.scenario_id },
      ),
    )) as never);
  putDrivers.mockResolvedValue(okResult(driverGrid()) as never);
  compare.mockReturnValue(new Promise(() => {}) as never);
  getSegments.mockResolvedValue(okResult(kpiSegments()) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("picker", () => {
  it("lists the scenarios, Base first and picked by default", async () => {
    await renderLoaded();
    expect(
      within(picker())
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Base", "Bull", "Bear"]);
    expect(picker().value).toBe("1");
    expect(getDrivers).toHaveBeenCalledWith({ path: { ticker: "AAPL", scenario_id: 1 } });
  });

  it("picks the scenario of ?scenario and writes the choice back", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=3");
    expect(picker().value).toBe("3");
    await userEvent.selectOptions(picker(), "2");
    expect(new URLSearchParams(seen.search).get("scenario")).toBe("2");
    await waitFor(() =>
      expect(getDrivers).toHaveBeenLastCalledWith({ path: { ticker: "AAPL", scenario_id: 2 } }),
    );
  });

  it("creates a scenario and picks it", async () => {
    create.mockResolvedValue(
      okResult(scenario({ id: 4, name: "Recession", is_default: false, base_id: 1 }), 201) as never,
    );
    await renderLoaded();
    list.mockResolvedValue(
      okResult([
        ...scenarios(),
        scenario({ id: 4, name: "Recession", is_default: false, base_id: 1 }),
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
    create.mockResolvedValue(errorResult(409, { detail: "A scenario named Bull exists" }) as never);
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Name"), "Bull");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A scenario named Bull exists");
  });

  it("renames the picked scenario", async () => {
    update.mockResolvedValue(okResult(scenario({ id: 2, name: "Bullish" })) as never);
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Bull");
    await userEvent.clear(name);
    await userEvent.type(name, "Bullish");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2 },
      body: { name: "Bullish" },
    });
  });

  it("offers no Delete for Base", async () => {
    await renderLoaded();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("deletes a scenario after a confirmation and goes back to Base", async () => {
    remove.mockResolvedValue(okResult(null, 204) as never);
    await renderLoaded("/c/AAPL/scenarios?scenario=3");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Delete Bear?");
    list.mockResolvedValue(okResult(scenarios().slice(0, 2)) as never);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", scenario_id: 3 } });
    await waitFor(() => expect(picker().value).toBe("1"));
  });

  it("shows the reason when a delete fails", async () => {
    remove.mockResolvedValue(errorResult(409, { detail: "Base cannot be deleted" }) as never);
    await renderLoaded("/c/AAPL/scenarios?scenario=3");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Base cannot be deleted");
  });

  it("links the driver files of the picked scenario", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/v1/companies/AAPL/scenarios/2/drivers/export?format=csv",
    );
    expect(screen.getByRole("link", { name: "Export Excel" })).toHaveAttribute(
      "href",
      "/api/v1/companies/AAPL/scenarios/2/drivers/export?format=xlsx",
    );
  });
});

describe("import", () => {
  it("opens the driver import sheet for the picked scenario", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    const sheet = await screen.findByRole("dialog", { name: "Import drivers" });
    expect(within(sheet).getByLabelText("Driver file")).toBeInTheDocument();
  });
});

describe("compare", () => {
  it("compares every scenario under the grid", async () => {
    await renderLoaded();
    expect(screen.getByRole("region", { name: "Compare scenarios" })).toBeInTheDocument();
    expect(compare).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, query: { freq: "annual" } });
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

  it("has no Mode column on Base", async () => {
    await renderLoaded();
    expect(screen.queryByRole("combobox", { name: /^Mode of/ })).not.toBeInTheDocument();
  });

  it("sends one PUT with the whole row on an edit", async () => {
    await renderLoaded();
    await edit("driver:gross_margin", "f:2027", "50");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1 },
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
      path: { ticker: "AAPL", scenario_id: 1 },
      body: { rows: [{ driver_code: "gross_margin", kind: "value", values: [] }] },
    });
  });
});

describe("vs Base mode", () => {
  it("shows and edits the offset", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    expect(screen.getByRole("combobox", { name: "Mode of Revenue growth" })).toHaveValue("offset");
    expect(cell("driver:revenue_growth", "f:2026")).toHaveTextContent("+3.0 pts");
    expect(cell("driver:gross_margin", "f:2026")).toHaveTextContent("47.0%");
    await edit("driver:revenue_growth", "f:2026", "-5");
    await waitFor(() => expect(putDrivers).toHaveBeenCalledTimes(1));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2 },
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
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode of Revenue growth" }),
      "value",
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Switch Revenue growth to Value?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Switch" }));
    expect(putDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2 },
      body: { rows: [{ driver_code: "revenue_growth", kind: "value", values: [] }] },
    });
  });

  it("keeps the values when the switch is cancelled", async () => {
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
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
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
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
    await renderLoaded("/c/AAPL/scenarios?scenario=2");
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
    await renderLoaded("/c/AAPL/scenarios?scenario=2");

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
