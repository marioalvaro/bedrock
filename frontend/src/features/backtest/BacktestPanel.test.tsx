// The Backtest panel: selectors in the URL, the chart and table of one selection, running one.
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getBacktestApiV1CompaniesTickerBacktestGet,
  runBacktestApiV1CompaniesTickerBacktestPost,
} from "@/api/generated/sdk.gen";
import { Chart } from "@/components/Chart";
import { createQueryClient } from "@/lib/query-client";
import { backtest, noBacktest } from "@/test/accountability";
import { LocationProbe } from "@/test/LocationProbe";
import { errorResult, okResult } from "@/test/responses";

import { BacktestPanel } from "./BacktestPanel";

vi.mock("@/api/generated/sdk.gen", () => ({
  getBacktestApiV1CompaniesTickerBacktestGet: vi.fn(),
  runBacktestApiV1CompaniesTickerBacktestPost: vi.fn(),
}));
vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));

const get = vi.mocked(getBacktestApiV1CompaniesTickerBacktestGet);
const run = vi.mocked(runBacktestApiV1CompaniesTickerBacktestPost);
const chart = vi.mocked(Chart);

afterEach(() => vi.clearAllMocks());

let search = "";
const onSearch = (next: string) => {
  search = next;
};
const param = (name: string) => new URLSearchParams(search).get(name);

function renderPanel(path = "/c/AAPL/backtest") {
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
                <BacktestPanel ticker="AAPL" />
                <LocationProbe onSearch={onSearch} />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function renderLoaded(path?: string, view = backtest()) {
  get.mockResolvedValue(okResult(view) as never);
  renderPanel(path);
  await screen.findByRole("combobox", { name: "Metric" });
}

type ChartProps = { option: EChartsOption; ariaLabel: string; height?: number };
const lastChart = () => chart.mock.lastCall![0] as unknown as ChartProps;
const metric = () => screen.getByRole("combobox", { name: "Metric" }) as HTMLSelectElement;
const radio = (name: string) => screen.getByRole("radio", { name });
const scoreRowCells = (name: string) =>
  within(
    within(screen.getByRole("table", { name: "Scores" })).getByRole("row", {
      name: new RegExp(`^${name}`),
    }),
  ).getAllByRole("cell");

describe("states", () => {
  it("says it is loading", () => {
    get.mockReturnValue(new Promise(() => {}) as never);
    renderPanel();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says when it could not load", async () => {
    get.mockResolvedValue(errorResult(500) as never);
    renderPanel();
    expect(await screen.findByText("Could not load the backtest.")).toBeInTheDocument();
  });

  it("offers the first run when there is none", async () => {
    get.mockResolvedValue(okResult(noBacktest()) as never);
    renderPanel();
    expect(await screen.findByText("No backtest yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run backtest" })).toBeEnabled();
    expect(screen.queryByRole("combobox", { name: "Metric" })).not.toBeInTheDocument();
  });

  it("explains a run that scored nothing and still lists its failures", async () => {
    get.mockResolvedValue(okResult(backtest({ summary: [] })) as never);
    renderPanel();
    expect(await screen.findByText("Nothing could be scored.")).toBeInTheDocument();
    expect(screen.getByText(/^Last run .* could not run$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run backtest" })).toBeEnabled();
  });
});

describe("selection", () => {
  it("defaults to revenue MAPE, annual", async () => {
    await renderLoaded();
    expect(metric().value).toBe("revenue");
    expect(radio("Annual")).toHaveAttribute("aria-checked", "true");
    expect(radio("MAPE")).toHaveAttribute("aria-checked", "true");
    expect(lastChart().ariaLabel).toBe("Revenue: MAPE by horizon");
    expect(lastChart().height).toBe(260);
  });

  it("groups the metric options, lines then drivers", async () => {
    await renderLoaded();
    const groups = [...metric().querySelectorAll("optgroup")].map((group) => [
      group.label,
      [...group.querySelectorAll("option")].map((option) => option.textContent),
    ]);
    expect(groups).toEqual([
      ["Lines", ["Revenue"]],
      ["Drivers", ["Gross margin"]],
    ]);
  });

  it("draws one series per method", async () => {
    await renderLoaded();
    expect((lastChart().option.series as LineSeriesOption[]).map((s) => s.name)).toEqual([
      "Auto",
      "ARIMA",
    ]);
  });

  it("tables methods by horizon, with n in the cell title", async () => {
    await renderLoaded();
    const cells = scoreRowCells("Auto");
    expect(cells.map((cell) => cell.textContent)).toEqual(["5.1%", "12.5%"]);
    expect(cells[0]).toHaveAttribute("title", "n = 10");
    expect(scoreRowCells("ARIMA")[1]).toHaveTextContent("—");
  });

  it("writes the metric to the URL", async () => {
    await renderLoaded();
    await userEvent.selectOptions(metric(), "gross_margin");
    expect(param("metric")).toBe("gross_margin");
    expect(lastChart().ariaLabel).toBe("Gross margin: MAPE by horizon");
  });

  it("switches the stat through the URL", async () => {
    await renderLoaded();
    await userEvent.click(radio("Bias"));
    expect(param("stat")).toBe("bias");
    expect(lastChart().ariaLabel).toBe("Revenue: Bias by horizon");
    expect(scoreRowCells("ARIMA")[0]).toHaveTextContent("-3.0%");
  });

  it("switches the frequency through the URL", async () => {
    await renderLoaded();
    await userEvent.click(radio("Quarterly"));
    expect(param("freq")).toBe("quarterly");
    expect(scoreRowCells("Auto").map((cell) => cell.textContent)).toEqual(["4.0%"]);
  });

  it("reads the selection from the URL", async () => {
    await renderLoaded("/c/AAPL/backtest?metric=gross_margin&stat=hit_rate");
    expect(metric().value).toBe("gross_margin");
    expect(radio("Hit rate")).toHaveAttribute("aria-checked", "true");
    expect(scoreRowCells("Auto")[0]).toHaveTextContent("80%");
  });

  it("falls back from an unknown metric", async () => {
    await renderLoaded("/c/AAPL/backtest?metric=nope");
    expect(metric().value).toBe("revenue");
  });

  it("keeps a driver annual", async () => {
    await renderLoaded("/c/AAPL/backtest?metric=gross_margin&freq=quarterly");
    expect(radio("Annual")).toHaveAttribute("aria-checked", "true");
    expect(radio("Quarterly")).toBeDisabled();
  });

  it("disables the hit rate without a range and says why", async () => {
    await renderLoaded();
    expect(radio("Hit rate")).toBeDisabled();
    expect(radio("Hit rate")).toHaveAttribute(
      "title",
      "Ranges exist for drivers now, and for lines from M8",
    );
  });

  it("shows MAPE when the URL asks for a hit rate there is none of", async () => {
    await renderLoaded("/c/AAPL/backtest?stat=hit_rate");
    expect(radio("MAPE")).toHaveAttribute("aria-checked", "true");
  });

  it("enables the hit rate on a driver with a band", async () => {
    await renderLoaded("/c/AAPL/backtest?metric=gross_margin");
    expect(radio("Hit rate")).toBeEnabled();
    expect(radio("Hit rate")).not.toHaveAttribute("title");
  });

  it("says so when the selection has no scores", async () => {
    const view = backtest({ summary: backtest().summary.filter((row) => row.freq === "annual") });
    await renderLoaded("/c/AAPL/backtest?freq=quarterly", view);
    expect(screen.getByText("No scores for this selection.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Scores" })).not.toBeInTheDocument();
  });
});

describe("status", () => {
  it("states the origins and the runs that could not run", async () => {
    await renderLoaded();
    expect(screen.getByText(/2 origins, 1 method run could not run$/)).toBeInTheDocument();
    expect(screen.queryByText("A newer 10-K is filed: run again")).not.toBeInTheDocument();
  });

  it("says when a newer 10-K is filed", async () => {
    await renderLoaded(undefined, backtest({ stale: true }));
    expect(screen.getByText("A newer 10-K is filed: run again")).toBeInTheDocument();
  });

  it("lists the failed runs in a collapsed details", async () => {
    await renderLoaded();
    const item = screen.getByText("2024-11-01 · ARIMA: Set these drivers: gross_margin");
    expect(item.closest("details")).not.toHaveAttribute("open");
  });

  it("has no details when every run ran", async () => {
    const origins = [{ as_of_date: "2024-11-01", runs: [{ method: "auto", error: null }] }];
    await renderLoaded(undefined, backtest({ origins }));
    expect(document.querySelector("details")).toBeNull();
  });
});

describe("running", () => {
  it("posts, shows that it runs, and then the new results", async () => {
    let finish: (value: unknown) => void = () => {};
    run.mockReturnValue(new Promise((resolve) => (finish = resolve)) as never);
    get.mockResolvedValue(okResult(noBacktest()) as never);
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Run backtest" }));

    const pending = await screen.findByRole("button", { name: "Running…" });
    expect(pending).toBeDisabled();
    expect(pending).toHaveAttribute("title", "Takes about 15 seconds");
    expect(run).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });

    finish(okResult(backtest()));
    expect(await screen.findByRole("combobox", { name: "Metric" })).toBeInTheDocument();
    expect(screen.queryByText("No backtest yet")).not.toBeInTheDocument();
  });

  it("shows the API's detail and keeps the results when it fails", async () => {
    run.mockResolvedValue(errorResult(422, { detail: "No 10-K filings to back-test" }) as never);
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No 10-K filings to back-test");
    expect(screen.getByRole("table", { name: "Scores" })).toBeInTheDocument();
  });

  it("shows the failure from the empty state too, with a fallback text", async () => {
    run.mockResolvedValue(errorResult(500, {}) as never);
    get.mockResolvedValue(okResult(noBacktest()) as never);
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Run backtest" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Could not run the backtest."),
    );
  });
});
