// The Engines sheet of a driver: its history against ARIMA, ETS and Blend, with the case's values.
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet } from "@/api/generated/sdk.gen";
import { Chart } from "@/components/Chart";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { driverEngines, engineFit } from "@/test/engines";
import { errorResult, okResult } from "@/test/responses";

import { DriverEnginesSheet } from "./DriverEnginesSheet";

vi.mock("@/api/generated/sdk.gen", () => ({
  getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet: vi.fn(),
}));

// jsdom cannot draw a canvas: the tests read the props handed to the app's chart wrapper.
vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));
const chart = vi.mocked(Chart);

const getEngines = vi.mocked(
  getDriverEnginesApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriverEnginesGet,
);

type ChartProps = { option: EChartsOption; ariaLabel: string; height?: number; colors?: string[] };
const lastProps = () => chart.mock.lastCall?.[0] as unknown as ChartProps;
const lastSeries = () => lastProps().option.series as LineSeriesOption[];
const seriesNamed = (name: string) => lastSeries().find((series) => series.name === name)!;

function renderSheet(scenarioCase: "base" | "bull" = "base") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <DriverEnginesSheet
        ticker="AAPL"
        scenarioId={1}
        scenarioCase={scenarioCase}
        driver={{ code: "gross_margin", label: "Gross margin" }}
        scale="M"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

const table = () => screen.getByRole("table", { name: "Engine forecasts" });
const rowOf = (name: string) => within(table()).getByRole("row", { name: new RegExp(`^${name}`) });

beforeEach(() => {
  setScale("M");
  getEngines.mockResolvedValue(okResult(driverEngines()) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("DriverEnginesSheet", () => {
  it("asks for the driver in the scenario and case, and titles the sheet", async () => {
    renderSheet();
    expect(await screen.findByRole("dialog", { name: "Gross margin · engines" })).toBeVisible();
    expect(getEngines).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      query: { code: "gross_margin" },
    });
  });

  it("shows the engine note under the title", async () => {
    getEngines.mockResolvedValue(
      okResult(driverEngines({ note: "Auto: 9 years of history; blend", used: "blend" })) as never,
    );
    renderSheet();
    expect(await screen.findByText("Auto: 9 years of history; blend")).toBeVisible();
  });

  it("draws the history, the three engines, the case and the used engine's band", async () => {
    renderSheet("bull");
    await screen.findByRole("table", { name: "Engine forecasts" });
    const props = lastProps();
    expect(props.ariaLabel).toBe("Gross margin: history and engine forecasts");
    expect(props.height).toBe(260);
    expect(lastSeries().map((series) => series.name)).toEqual([
      "History",
      "ARIMA",
      "ETS",
      "Blend",
      "Bull case",
      "90% range low",
      "90% range",
    ]);
    expect(props.colors).toEqual([
      "--muted-foreground",
      "--chart-2",
      "--chart-3",
      "--chart-4",
      "--chart-1",
      "--chart-1",
      "--chart-1",
    ]);
    const x = (props.option.xAxis as { data: string[] }).data;
    expect(x).toHaveLength(10);
    expect(x.slice(0, 2)).toEqual(["FY18A", "FY19A"]);
    expect(x.slice(-3)).toEqual(["FY25A", "FY26E", "FY27E"]);
  });

  it("puts each year on its axis tick, so the guide line, tick and point line up", async () => {
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    expect((lastProps().option.xAxis as { boundaryGap?: boolean }).boundaryGap).toBe(false);
  });

  it("puts history on the actual years and the engines on the forecast years, in percent", async () => {
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    const history = seriesNamed("History").data as (number | null)[];
    expect(history[0]).toBeCloseTo(38.34);
    expect(history.slice(-2)).toEqual([null, null]);
    const arima = seriesNamed("ARIMA");
    expect((arima.data as (number | null)[]).slice(0, 8)).toEqual(Array(8).fill(null));
    expect((arima.data as number[])[8]).toBeCloseTo(45.779);
    expect(arima.lineStyle?.type).toBe("dashed");
    expect(seriesNamed("ETS").lineStyle?.type).toBe("dashed");
    expect(seriesNamed("Blend").lineStyle?.type).toBe("dashed");
  });

  it("draws the case solid from the last actual point on", async () => {
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    const base = seriesNamed("Base case");
    expect(base.lineStyle?.type ?? "solid").toBe("solid");
    const data = base.data as (number | null)[];
    expect(data.slice(0, 7)).toEqual(Array(7).fill(null));
    expect(data[7]).toBeCloseTo(46.9);
    expect(data[8]).toBeCloseTo(45.779);
  });

  it("draws the band as two stacked lines with only the upper one filled", async () => {
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    const low = seriesNamed("90% range low");
    const high = seriesNamed("90% range");
    expect(low.stack).toBe("band");
    expect(high.stack).toBe("band");
    expect((low.data as (number | null)[])[8]).toBeCloseTo(41.863);
    // The upper series is the band's width, stacked on the lower bound: its top is ARIMA's p95.
    expect((high.data as number[])[8]! + (low.data as number[])[8]!).toBeCloseTo(49.695);
    expect(low.areaStyle).toBeUndefined();
    expect(high.areaStyle?.opacity).toBe(0.15);
    expect(low.lineStyle?.opacity).toBe(0);
    expect(high.lineStyle?.opacity).toBe(0);
    const legend = lastProps().option.legend as { data: string[] };
    expect(legend.data).not.toContain("90% range low");
  });

  it("names the band's range in the tooltip, not its stacked width", async () => {
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    const tooltip = lastProps().option.tooltip as { formatter: (params: unknown) => string };
    const at = (seriesName: string, value: number) => ({
      seriesName,
      value,
      dataIndex: 8,
      marker: "",
    });
    const text = tooltip.formatter([
      at("ARIMA", 45.779),
      at("Base case", 45.779),
      at("90% range low", 41.863),
      at("90% range", 7.832),
    ]);
    expect(text).toBe(
      "FY26E<br/>ARIMA: 45.8%<br/>Base case: 45.8%<br/>90% range (ARIMA): 41.9%–49.7%",
    );
  });

  it("draws the case from the first forecast year when there is no history", async () => {
    getEngines.mockResolvedValue(
      okResult(driverEngines({ history: [], history_periods: [] })) as never,
    );
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    const data = seriesNamed("Base case").data as (number | null)[];
    expect(data).toHaveLength(2);
    expect(data[0]).toBeCloseTo(45.779);
  });

  it("draws no band when the driver's default is the 3-year mean", async () => {
    getEngines.mockResolvedValue(
      okResult(driverEngines({ engine: "mean", used: "mean" })) as never,
    );
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    expect(lastSeries().map((series) => series.name)).not.toContain("90% range");
  });

  it("tabulates each engine by year with its holdout error, the used one in use", async () => {
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    const headers = within(table())
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual(["Engine", "FY26E", "FY27E", "Holdout error"]);
    const arima = rowOf("ARIMA");
    expect(
      within(arima)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["45.8%", "44.8%", "5.5 pts"]);
    expect(arima).toHaveTextContent("In use");
    expect(arima).toHaveClass("font-semibold");
    expect(rowOf("ETS")).not.toHaveTextContent("In use");
    expect(within(rowOf("Blend")).getAllByRole("cell").at(-1)).toHaveTextContent("6.1 pts");
    expect(
      within(rowOf("Mean \\(3 yr\\)"))
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["45.7%", "45.7%", "—"]);
  });

  it("marks the mean in use when it is the default", async () => {
    getEngines.mockResolvedValue(
      okResult(driverEngines({ engine: "mean", used: "mean" })) as never,
    );
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    expect(rowOf("Mean \\(3 yr\\)")).toHaveTextContent("In use");
    expect(rowOf("ARIMA")).not.toHaveTextContent("In use");
  });

  it("shows an engine's error across its row and leaves its series empty", async () => {
    const view = driverEngines();
    const failed = engineFit({
      ...{ code: "ets", label: "ETS" },
      values: [],
      p05: [],
      p25: [],
      p75: [],
      p95: [],
      holdout_mae: null,
      error: "6 years of history (needs 8)",
    });
    getEngines.mockResolvedValue(
      okResult({ ...view, engines: [view.engines[0]!, failed, view.engines[2]!] }) as never,
    );
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    const cells = within(rowOf("ETS")).getAllByRole("cell");
    expect(cells).toHaveLength(1);
    expect(cells[0]).toHaveTextContent("6 years of history (needs 8)");
    expect(cells[0]).toHaveAttribute("colspan", "3");
    expect(seriesNamed("ETS").data).toEqual([]);
  });

  it("shows the seasonal index of a seasonal driver, signed", async () => {
    renderSheet();
    const seasonal = await screen.findByRole("table", { name: "Seasonal index" });
    expect(
      within(seasonal)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Q1", "Q2", "Q3", "Q4"]);
    expect(
      within(seasonal)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["0.0 pts", "+1.2 pts", "+0.3 pts", "−1.5 pts"]);
  });

  it("has no seasonal table for a driver without an index", async () => {
    getEngines.mockResolvedValue(okResult(driverEngines({ seasonal: null })) as never);
    renderSheet();
    await screen.findByRole("table", { name: "Engine forecasts" });
    expect(screen.queryByRole("table", { name: "Seasonal index" })).not.toBeInTheDocument();
  });

  it("says it is loading", async () => {
    getEngines.mockReturnValue(new Promise(() => {}) as never);
    renderSheet();
    expect(await screen.findByText("Loading engines…")).toBeVisible();
  });

  it("shows a 422's detail", async () => {
    getEngines.mockResolvedValue(
      errorResult(422, { detail: "No fiscal year to start from" }) as never,
    );
    renderSheet();
    expect(await screen.findByText("No fiscal year to start from")).toBeVisible();
  });

  it("falls back to a plain message on another failure", async () => {
    getEngines.mockResolvedValue(okResult("<!doctype html><html></html>") as never);
    renderSheet();
    expect(await screen.findByText("Could not load the engines.")).toBeVisible();
  });
});
