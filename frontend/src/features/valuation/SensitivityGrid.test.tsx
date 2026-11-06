import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet } from "@/api/generated/sdk.gen";
import { setScale } from "@/lib/scale";
import { errorResult, okResult } from "@/test/responses";
import { gridAxis, sensitivityGrid, tornado, tornadoBar } from "@/test/valuation";
import { renderWithClient } from "@/test/valuationView";

import { SensitivityGrid } from "./SensitivityGrid";

vi.mock("@/api/generated/sdk.gen", () => ({
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet: vi.fn(),
}));

const getGrid = vi.mocked(
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
);

const INPUTS = tornado().bars;
const EXIT_INPUTS = [
  ...INPUTS.filter((bar) => bar.code !== "terminal_growth"),
  tornadoBar({
    code: "exit_multiple",
    label: "Exit multiple",
    kind: "valuation",
    unit: "x",
    step: "1",
  }),
];

function renderGrid(inputs = INPUTS, scenarioCase: "base" | "bull" = "base") {
  renderWithClient(
    <SensitivityGrid ticker="AAPL" scenarioId={1} scenarioCase={scenarioCase} inputs={inputs} />,
  );
}

const lastQuery = () => getGrid.mock.calls.at(-1)?.[0].query;
const table = () => screen.findByRole("table", { name: /DCF value per share/ });
const columnHeaders = (grid: HTMLElement) =>
  within(grid)
    .getAllByRole("columnheader")
    .slice(1)
    .map((cell) => cell.textContent);
const rowHeaders = (grid: HTMLElement) =>
  within(grid)
    .getAllByRole("rowheader")
    .map((cell) => cell.textContent);

// The revenue-growth axis of a driver grid (rows), as the API gives it.
const growthAxis = gridAxis({
  code: "revenue_growth",
  label: "Revenue growth",
  step: "0.01",
  shifts: ["-0.02", "-0.01", "0", "0.01", "0.02"],
  points: ["0.03", "0.04", "0.05", "0.06", "0.07"],
});

beforeEach(() => {
  setScale("M");
  getGrid.mockResolvedValue(okResult(sensitivityGrid()) as never);
});
afterEach(() => vi.clearAllMocks());

describe("SensitivityGrid", () => {
  it("runs discount rate × terminal growth by default, with Gordon growth", async () => {
    renderGrid();
    await table();
    expect(lastQuery()).toEqual({ x: "discount_rate", y: "terminal_growth" });
    expect(screen.getByLabelText("Columns")).toHaveValue("discount_rate");
    expect(screen.getByLabelText("Rows")).toHaveValue("terminal_growth");
    expect(getGrid.mock.calls.at(-1)?.[0].path).toEqual({
      ticker: "AAPL",
      scenario_id: 1,
      case: "base",
    });
  });

  it("puts the exit multiple on the rows when the case values by exit multiple", async () => {
    renderGrid(EXIT_INPUTS);
    await table();
    expect(lastQuery()).toEqual({ x: "discount_rate", y: "exit_multiple" });
  });

  it("falls back to two different listed inputs without the rate and a terminal input", async () => {
    const drivers = INPUTS.filter((bar) => bar.kind === "driver");
    renderGrid(drivers);
    await table();
    expect(lastQuery()).toEqual({ x: "revenue_growth", y: "receivable_days" });
  });

  it("lists the tornado's inputs in both selects", () => {
    renderGrid();
    const options = within(screen.getByLabelText("Rows"))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual([
      "Discount rate",
      "Revenue growth",
      "Terminal growth",
      "Receivable days",
      "Buybacks",
    ]);
  });

  it("heads a valuation input's points with their values, captioned by case", async () => {
    renderGrid(INPUTS, "bull");
    const grid = await table();
    expect(columnHeaders(grid)).toEqual(["7.85%", "8.35%", "8.85%", "9.35%", "9.85%"]);
    expect(rowHeaders(grid)).toEqual(["1.5%", "2.0%", "2.5%", "3.0%", "3.5%"]);
    expect(within(grid).getByText("DCF value per share, Bull case")).toBeInTheDocument();
    expect(within(grid).getByText("Terminal growth ↓ · Discount rate →")).toBeInTheDocument();
  });

  it("heads a driver's points with their shifts, the first-year value as the title", async () => {
    getGrid.mockResolvedValue(okResult(sensitivityGrid({ y: growthAxis })) as never);
    renderGrid();
    await userEvent.selectOptions(screen.getByLabelText("Rows"), "revenue_growth");
    expect(lastQuery()).toEqual({ x: "discount_rate", y: "revenue_growth" });
    const grid = await table();
    expect(rowHeaders(grid)).toEqual(["−2 pts", "−1 pt", "Base", "+1 pt", "+2 pts"]);
    expect(within(grid).getByRole("rowheader", { name: "−2 pts" })).toHaveAttribute(
      "title",
      "First forecast year: 3.0%",
    );
  });

  it("shows the values per share, green above the price and red below, the center ringed", async () => {
    renderGrid();
    const grid = await table();
    // Row 4 (growth 3.5%), column 0 (rate 7.85%): 132.47 + 12 + 20 against a 140.00 price.
    const above = within(grid).getByRole("cell", { name: "$164.47" });
    expect(above).toHaveClass("text-positive");
    const below = within(grid).getByRole("cell", { name: "$100.47" });
    expect(below).toHaveClass("text-negative");
    const center = within(grid).getByRole("cell", { name: "$132.47" });
    expect(center).toHaveClass("font-semibold", "ring-1");
    expect(center).toHaveAttribute("aria-current", "true");
    expect(above).not.toHaveAttribute("aria-current");
  });

  it("colors nothing without a price", async () => {
    const plain = sensitivityGrid();
    getGrid.mockResolvedValue(
      okResult({
        ...plain,
        price: null,
        upside: plain.upside.map((row) => row.map(() => null)),
      }) as never,
    );
    renderGrid();
    const grid = await table();
    const cell = within(grid).getByRole("cell", { name: "$164.47" });
    expect(cell).not.toHaveClass("text-positive");
  });

  it("shows a point that failed as a dash with its error as the title", async () => {
    renderGrid();
    const grid = await table();
    const failed = within(grid).getByRole("cell", { name: "—" });
    expect(failed).toHaveAttribute("title", "Discount rate must exceed growth");
  });

  it("asks for two different inputs and sends nothing for the same one twice", async () => {
    renderGrid();
    await table();
    const calls = getGrid.mock.calls.length;
    await userEvent.selectOptions(screen.getByLabelText("Rows"), "discount_rate");
    expect(screen.getByText("Pick two different inputs")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(getGrid.mock.calls.length).toBe(calls);
  });

  it("keeps the previous grid, marked 'Updating…', while a new pair loads", async () => {
    renderGrid();
    await table();
    getGrid.mockReturnValue(new Promise(() => {}) as never);
    await userEvent.selectOptions(screen.getByLabelText("Columns"), "receivable_days");
    expect(screen.getByText("Updating…")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /DCF value per share/ })).toBeInTheDocument();
  });

  it("shows loading, then the API's 422 detail", async () => {
    getGrid.mockResolvedValue(
      errorResult(422, { detail: "Discount rate must exceed growth" }) as never,
    );
    renderGrid();
    expect(screen.getByText("Loading the grid…")).toBeInTheDocument();
    expect(await screen.findByText("Discount rate must exceed growth")).toBeInTheDocument();
  });

  it("falls back to a plain message for another failure", async () => {
    getGrid.mockResolvedValue(errorResult(500) as never);
    renderGrid();
    expect(await screen.findByText("Could not load the sensitivity grid.")).toBeInTheDocument();
  });
});
