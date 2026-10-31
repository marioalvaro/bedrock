import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { compareScenariosApiV1CompaniesTickerScenariosCompareGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { errorResult, okResult } from "@/test/responses";
import { comparison } from "@/test/scenarios";

import { ScenarioCompare } from "./ScenarioCompare";

vi.mock("@/api/generated/sdk.gen", () => ({
  compareScenariosApiV1CompaniesTickerScenariosCompareGet: vi.fn(),
}));

// jsdom cannot draw a canvas: the tests read the `option` handed to ECharts.
vi.mock("echarts-for-react/esm/core", () => ({ default: vi.fn(() => null) }));
const { default: EChartsCore } = await import("echarts-for-react/esm/core");
const echarts = vi.mocked(EChartsCore);

const compare = vi.mocked(compareScenariosApiV1CompaniesTickerScenariosCompareGet);

const lastOption = () => {
  const props = echarts.mock.lastCall?.[0] as unknown as { option: EChartsOption };
  return props.option;
};
const lastSeries = () => lastOption().series as LineSeriesOption[];

function renderCompare() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <ScenarioCompare ticker="AAPL" />
    </QueryClientProvider>,
  );
}

const table = () => screen.getByRole("table", { name: "Scenario comparison" });

beforeEach(() => {
  setScale("M");
  compare.mockResolvedValue(okResult(comparison()) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("ScenarioCompare chart", () => {
  it("draws one line per scenario, on Revenue by default", async () => {
    renderCompare();
    await screen.findByRole("table", { name: "Scenario comparison" });
    expect(screen.getByLabelText("Metric")).toHaveValue("revenue");
    // A scenario that cannot run keeps its (empty) series, so every scenario keeps its color.
    expect(lastSeries().map((series) => series.name)).toEqual(["Base", "Bull", "Bear"]);
    expect(lastSeries()[2]).toMatchObject({ data: [] });
    expect(lastSeries()[0]).toMatchObject({ type: "line", data: [425000, 435000] });
    expect(lastOption().xAxis).toMatchObject({ type: "category", data: ["FY26E", "FY27E"] });
    expect(screen.getByRole("img", { name: "Revenue by scenario" })).toBeInTheDocument();
  });

  it("follows the metric select and the page scale", async () => {
    setScale("B");
    renderCompare();
    await screen.findByRole("table", { name: "Scenario comparison" });
    expect(lastSeries()[1]).toMatchObject({ data: [437, 460] });
    await userEvent.selectOptions(screen.getByLabelText("Metric"), "eps_diluted");
    expect(lastSeries()[1]).toMatchObject({ name: "Bull", data: [7.52, 8.1] });
    expect(screen.getByRole("img", { name: "EPS (diluted) by scenario" })).toBeInTheDocument();
  });

  it("shows 1 decimal in the tooltip and axis, 2 for EPS", async () => {
    renderCompare();
    await screen.findByRole("table", { name: "Scenario comparison" });
    type Formatter = (value: number) => string;
    const tooltip = () => (lastOption().tooltip as { valueFormatter: Formatter }).valueFormatter;
    const axis = () =>
      (lastOption().yAxis as { axisLabel: { formatter: Formatter } }).axisLabel.formatter;
    expect(tooltip()(437123.456789)).toBe("437,123.5");
    expect(axis()(440000)).toBe("440,000.0");
    expect(tooltip()(-1234.56)).toBe("(1,234.6)");
    await userEvent.selectOptions(screen.getByLabelText("Metric"), "eps_diluted");
    expect(tooltip()(7.523456)).toBe("7.52");
    expect(axis()(8)).toBe("8.00");
  });

  it("asks for the quarterly comparison", async () => {
    renderCompare();
    await screen.findByRole("table", { name: "Scenario comparison" });
    await userEvent.click(screen.getByRole("radio", { name: "Quarterly" }));
    await waitFor(() =>
      expect(compare).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { freq: "quarterly" },
      }),
    );
  });
});

describe("ScenarioCompare table", () => {
  it("heads each metric and lists a row per scenario, values by unit", async () => {
    renderCompare();
    const rows = within(await screen.findByRole("table", { name: "Scenario comparison" }))
      .getAllByRole("row")
      .map((row) => row.textContent);
    expect(rows).toEqual([
      "FY26EFY27E",
      "Revenue · USD millions",
      "Base425,000435,000",
      "Bull437,000460,000",
      "BearSet these drivers: tax_rate",
      "EPS (diluted) · USD/share",
      "Base7.107.45",
      "Bull7.528.10",
      "BearSet these drivers: tax_rate",
    ]);
  });

  it("shows a dash where a scenario's horizon stops", async () => {
    const data = comparison();
    data.scenarios[1]!.values.revenue = ["437000000000", null];
    compare.mockResolvedValue(okResult(data) as never);
    renderCompare();
    await screen.findByRole("table", { name: "Scenario comparison" });
    expect(within(table()).getAllByRole("row")[3]).toHaveTextContent("Bull437,000—");
  });
});

describe("ScenarioCompare states", () => {
  it("shows Loading… first", () => {
    compare.mockReturnValue(new Promise(() => {}) as never);
    renderCompare();
    expect(screen.getByText("Loading the comparison…")).toBeInTheDocument();
  });

  it("says when the comparison cannot load", async () => {
    compare.mockResolvedValue(errorResult(500) as never);
    renderCompare();
    expect(await screen.findByText("Could not load the comparison.")).toBeInTheDocument();
  });

  it("lists each scenario's reason when none can run", async () => {
    const data = comparison({ periods: [] });
    data.scenarios = data.scenarios.map((scenario) => ({
      ...scenario,
      values: {},
      error: scenario.name === "Bear" ? "No quarterly history" : "Set these drivers: gross_margin",
    }));
    compare.mockResolvedValue(okResult(data) as never);
    renderCompare();
    const list = await screen.findByRole("list", { name: "Scenarios that cannot run" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Base: Set these drivers: gross_margin",
      "Bull: Set these drivers: gross_margin",
      "Bear: No quarterly history",
    ]);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
