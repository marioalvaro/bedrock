// The Seasonality tab: a quarterly IS/CF line split into trend, seasonal and residual.
import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSeasonalityApiV1CompaniesTickerSeasonalityGet } from "@/api/generated/sdk.gen";
import { Chart } from "@/components/Chart";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { errorResult, okResult } from "@/test/responses";
import { seasonality } from "@/test/seasonality";

import { SeasonalityView } from "./SeasonalityView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getSeasonalityApiV1CompaniesTickerSeasonalityGet: vi.fn(),
}));

// jsdom cannot draw a canvas: the tests read the props handed to the app's chart wrapper.
vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));
const chart = vi.mocked(Chart);
const getSeasonality = vi.mocked(getSeasonalityApiV1CompaniesTickerSeasonalityGet);

type ChartProps = { option: EChartsOption; ariaLabel: string; height?: number; colors?: string[] };
const MINUS = "−";

// The latest props of the chart with this aria-label.
function chartNamed(ariaLabel: string): ChartProps {
  const calls = chart.mock.calls.map((call) => call[0] as unknown as ChartProps);
  const found = calls.filter((props) => props.ariaLabel === ariaLabel).at(-1);
  if (!found) throw new Error(`no chart "${ariaLabel}"; saw ${calls.map((c) => c.ariaLabel)}`);
  return found;
}
const seriesOf = (ariaLabel: string) => chartNamed(ariaLabel).option.series as LineSeriesOption[];

let location = { search: "", type: "" };
function Probe() {
  const { search } = useLocation();
  const type = useNavigationType();
  useEffect(() => {
    location = { search, type };
  }, [search, type]);
  return null;
}

function renderView(path = "/c/COST/seasonality") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="c/:ticker/:tab"
            element={
              <>
                <SeasonalityView ticker="COST" />
                <Probe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const netIncome = () =>
  seasonality({
    code: "net_income",
    label: "Net income",
    observed: Array(12).fill(1_800_000_000),
    factors: [
      { fiscal_period: "Q1", value: -100_000_000, pct: -0.05 },
      { fiscal_period: "Q2", value: -50_000_000, pct: -0.025 },
      { fiscal_period: "Q3", value: -60_000_000, pct: null },
      { fiscal_period: "Q4", value: 210_000_000, pct: 0.105 },
    ],
    strength: 0.4321,
  });

const lineSelect = () => screen.getByRole("combobox", { name: "Line" });
const factorsTable = () => screen.getByRole("table", { name: "Seasonal factors" });
const rowCells = (name: string) =>
  within(within(factorsTable()).getByRole("row", { name: new RegExp(`^${name}`) }))
    .getAllByRole("cell")
    .map((cell) => cell.textContent);

beforeEach(() => {
  setScale("M");
  location = { search: "", type: "" };
  getSeasonality.mockImplementation(((options: { query: { code: string } }) =>
    Promise.resolve(
      options.query.code === "net_income"
        ? okResult(netIncome())
        : options.query.code === "revenue"
          ? okResult(seasonality())
          : errorResult(422, { detail: `Unknown line ${options.query.code}` }),
    )) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("SeasonalityView", () => {
  it("shows Revenue by default and lists the decomposable lines", async () => {
    renderView();
    await screen.findByText("Seasonal strength 0.98 · 0 = none, 1 = strong");
    expect(getSeasonality).toHaveBeenCalledWith({
      path: { ticker: "COST" },
      query: { code: "revenue" },
    });
    expect(lineSelect()).toHaveValue("revenue");
    expect(
      within(lineSelect())
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Revenue", "Net income", "EPS (diluted)", "Cash from operations"]);
  });

  it("draws observed and trend, seasonal and residual on the shared quarters", async () => {
    renderView();
    await screen.findByText(/Seasonal strength/);
    const labels = seasonality().periods.map((p) => p.label);
    const names = {
      "Revenue: observed and trend": ["Observed", "Trend"],
      "Revenue: seasonal": ["Seasonal"],
      "Revenue: residual": ["Residual"],
    };
    for (const [ariaLabel, series] of Object.entries(names)) {
      const props = chartNamed(ariaLabel);
      expect(props.height).toBe(200);
      expect(props.option.xAxis).toMatchObject({ data: labels });
      expect(seriesOf(ariaLabel).map((s) => s.name)).toEqual(series);
    }
    expect(chartNamed("Revenue: observed and trend").colors).toEqual(["--chart-1", "--chart-2"]);
    expect(chartNamed("Revenue: seasonal").colors).toEqual(["--chart-3"]);
    expect(chartNamed("Revenue: residual").colors).toEqual(["--muted-foreground"]);
    expect(seriesOf("Revenue: observed and trend")[0]!.data![0]).toBeCloseTo(57799);
    for (const heading of ["Observed and trend", "Seasonal", "Residual"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
  });

  it("shows the seasonal factors in the page scale and follows the scale toggle", async () => {
    renderView();
    await screen.findByText(/Seasonal strength/);
    expect(
      within(factorsTable())
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["", "Q1", "Q2", "Q3", "Q4"]);
    expect(rowCells("Amount")).toEqual([
      `${MINUS}5,134`,
      `${MINUS}4,949`,
      `${MINUS}5,945`,
      "+16,029",
    ]);
    expect(rowCells("% of trend")).toEqual([
      `${MINUS}7.4%`,
      `${MINUS}7.1%`,
      `${MINUS}8.6%`,
      "+23.1%",
    ]);
    expect(within(factorsTable()).getByText("· USD millions")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "B" }));
    expect(rowCells("Amount")[3]).toBe("+16.0");
    expect(seriesOf("Revenue: observed and trend")[0]!.data![0]).toBeCloseTo(57.799);
  });

  it("switches line and writes ?line with replace, keeping other params", async () => {
    renderView("/c/COST/seasonality?x=1");
    await screen.findByText(/Seasonal strength 0.98/);
    await userEvent.selectOptions(lineSelect(), "net_income");
    await screen.findByText("Seasonal strength 0.43 · 0 = none, 1 = strong");
    expect(location.type).toBe("REPLACE");
    const search = new URLSearchParams(location.search);
    expect(search.get("line")).toBe("net_income");
    expect(search.get("x")).toBe("1");
    expect(lineSelect()).toHaveValue("net_income");
    expect(rowCells("% of trend")).toEqual([`${MINUS}5.0%`, `${MINUS}2.5%`, "—", "+10.5%"]);
    expect(chartNamed("Net income: seasonal")).toBeDefined();
  });

  it("opens on the line in ?line", async () => {
    renderView("/c/COST/seasonality?line=net_income");
    await screen.findByText(/Seasonal strength 0.43/);
    expect(lineSelect()).toHaveValue("net_income");
    expect(getSeasonality).not.toHaveBeenCalledWith(
      expect.objectContaining({ query: { code: "revenue" } }),
    );
  });

  it("keeps the previous line on screen while the next one loads (G32)", async () => {
    renderView();
    await screen.findByText(/Seasonal strength 0.98/);
    let release: (value: unknown) => void = () => {};
    getSeasonality.mockReturnValueOnce(new Promise((resolve) => (release = resolve)) as never);
    await userEvent.selectOptions(lineSelect(), "net_income");
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(screen.getByText(/Seasonal strength 0.98/)).toBeInTheDocument();
    expect(lineSelect()).toHaveValue("net_income");
    await act(async () => release(okResult(netIncome())));
    await screen.findByText(/Seasonal strength 0.43/);
  });

  it("falls back to Revenue for a line the company cannot decompose", async () => {
    renderView("/c/COST/seasonality?line=total_assets");
    await screen.findByText(/Seasonal strength 0.98/);
    expect(lineSelect()).toHaveValue("revenue");
    expect(chartNamed("Revenue: seasonal")).toBeDefined();
    expect(screen.queryByText("Unknown line total_assets")).not.toBeInTheDocument();
  });

  it("shows Loading… until the first line arrives", async () => {
    getSeasonality.mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(await screen.findByText("Loading…")).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Scale" })).toBeInTheDocument();
  });

  it("shows a 422's detail", async () => {
    getSeasonality.mockResolvedValue(errorResult(422, { detail: "No quarterly history" }) as never);
    renderView();
    expect(await screen.findByText("No quarterly history")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(chart).not.toHaveBeenCalled();
  });

  it("shows Revenue's 422 when the asked line falls back to it", async () => {
    getSeasonality.mockResolvedValue(errorResult(422, { detail: "No quarterly history" }) as never);
    renderView("/c/COST/seasonality?line=net_income");
    expect(await screen.findByText("No quarterly history")).toBeInTheDocument();
    await waitFor(() =>
      expect(getSeasonality).toHaveBeenCalledWith(
        expect.objectContaining({ query: { code: "revenue" } }),
      ),
    );
  });

  it.each([
    ["a server error", errorResult(500)],
    ["a 200 of the wrong shape", okResult("<!doctype html><html></html>")],
  ])("shows the fallback message on %s", async (_name, result) => {
    getSeasonality.mockResolvedValue(result as never);
    renderView();
    expect(await screen.findByText("Could not load the seasonality.")).toBeInTheDocument();
  });
});
