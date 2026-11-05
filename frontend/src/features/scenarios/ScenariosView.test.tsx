// The Scenarios tab: the picker and settings, the case toggle and reset, its states. The driver grid has its own files (DriverGrid*.test.tsx).
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { segments } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import { bullGrid, driverGrid, scenario, scenarios } from "@/test/scenarios";
import {
  list,
  create,
  update,
  remove,
  getDrivers,
  putDrivers,
  resetCase,
  compare,
  getSegments,
  seen,
  renderView,
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
