import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getForecastApiV1CompaniesTickerScenariosScenarioIdForecastGet,
  listScenariosApiV1CompaniesTickerScenariosGet,
} from "@/api/generated/sdk.gen";
import type { ForecastOut } from "@/api/generated/types.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { errorResult, okResult } from "@/test/responses";
import { forecastIncome, scenarios } from "@/test/scenarios";

import { ForecastView } from "./ForecastView";

vi.mock("@/api/generated/sdk.gen", () => ({
  listScenariosApiV1CompaniesTickerScenariosGet: vi.fn(),
  getForecastApiV1CompaniesTickerScenariosScenarioIdForecastGet: vi.fn(),
}));

const list = vi.mocked(listScenariosApiV1CompaniesTickerScenariosGet);
const getForecast = vi.mocked(getForecastApiV1CompaniesTickerScenariosScenarioIdForecastGet);

const seen = { path: "", search: "" };

function LocationProbe() {
  const { pathname, search } = useLocation();
  useEffect(() => {
    seen.path = pathname;
    seen.search = search;
  }, [pathname, search]);
  return null;
}

function renderView(path = "/c/AAPL/forecast") {
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
                <ForecastView ticker="AAPL" />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const cell = (row: string, column: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${column}"]`) as HTMLElement;
const header = (column: string) =>
  document.querySelector(`.ag-header-cell[col-id="${column}"]`) as HTMLElement;
const picker = () => screen.getByRole("combobox", { name: "Scenario" }) as HTMLSelectElement;
// The header renders before the rows: wait for a forecast cell of `row`.
const loaded = (row = "revenue") => waitFor(() => expect(cell(row, "FY2026")).not.toBeNull());
const lastQuery = () => getForecast.mock.calls.at(-1)?.[0];

/** A balance sheet forecast: total assets, then the check row (one actual year, one forecast). */
function forecastBalance(): ForecastOut {
  const income = forecastIncome();
  const periods = [income.periods[1]!, income.periods[2]!];
  return forecastIncome({
    statement: "BS",
    periods,
    rows: [
      {
        code: "total_assets",
        label: "Total assets",
        unit: "USD",
        kind: "instant",
        depth: 0,
        values: ["364980000000", "371000000000"],
        provenance: ["normalized", "forecast"],
        yoy: [null, null],
        common_size: [null, null],
        adjustable: false,
        custom: false,
        parent: null,
        common_size_base: null,
      },
    ],
    balance_check: [
      { period_key: "FY2025", difference: "0", ok: true },
      { period_key: "FY2026", difference: "0", ok: true },
    ],
    integrity: [income.integrity[0]!],
  });
}

beforeEach(() => {
  setScale("M");
  list.mockResolvedValue(okResult(scenarios()) as never);
  getForecast.mockResolvedValue(okResult(forecastIncome()) as never);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ForecastView", () => {
  it("shows the actual years, then the tinted forecast years labelled E", async () => {
    renderView();

    await loaded();
    expect(header("FY2026")).toHaveTextContent("FY26E");
    expect(header("FY2025")).toHaveTextContent("FY2025");
    expect(header("FY2026")).toHaveClass("cell-forecast");
    expect(header("FY2025")).not.toHaveClass("cell-forecast");
    expect(cell("revenue", "FY2026")).toHaveTextContent("425,900");
    expect(cell("revenue", "FY2026")).toHaveClass("cell-forecast", "prov-forecast");
    expect(cell("revenue", "FY2025")).toHaveClass("prov-normalized");
    expect(cell("revenue", "FY2025")).not.toHaveClass("cell-forecast");
  });

  it("shows every line, its breakdown included", async () => {
    renderView();

    await waitFor(() => expect(cell("gross_profit", "FY2027")).toHaveTextContent("204,453"));
    expect(cell("net_income", "FY2027")).toHaveTextContent("117,900");
  });

  it("keeps every cell inert: no cell opens details in this tab", async () => {
    renderView();

    await loaded();
    expect(cell("revenue", "FY2025")).not.toHaveClass("cursor-pointer");
    expect(cell("revenue", "FY2026")).not.toHaveClass("cursor-pointer");
  });

  it("forecasts Base by default, as an annual income statement", async () => {
    renderView();

    await loaded();
    expect(lastQuery()).toMatchObject({
      path: { ticker: "AAPL", scenario_id: 1 },
      query: { type: "IS", freq: "annual" },
    });
    expect(picker().value).toBe("1");
  });

  it("shares the picked scenario with the Scenarios tab through ?scenario", async () => {
    const user = userEvent.setup();
    renderView("/c/AAPL/forecast?scenario=3");

    await loaded();
    expect(picker().value).toBe("3");
    expect(lastQuery()?.path).toMatchObject({ scenario_id: 3 });

    await user.selectOptions(picker(), "2");

    await waitFor(() => expect(lastQuery()?.path).toMatchObject({ scenario_id: 2 }));
    expect(seen.search).toBe("?scenario=2");
  });

  it("asks for the picked statement and frequency", async () => {
    const user = userEvent.setup();
    renderView();
    await loaded();

    await user.click(screen.getByRole("radio", { name: "Cash flow" }));
    await waitFor(() => expect(lastQuery()?.query).toEqual({ type: "CF", freq: "annual" }));

    await user.click(screen.getByRole("radio", { name: "Quarterly" }));
    await waitFor(() => expect(lastQuery()?.query).toEqual({ type: "CF", freq: "quarterly" }));
  });

  it("keeps the grid mounted while the next frequency loads (G32)", async () => {
    const user = userEvent.setup();
    renderView();
    await loaded();
    const before = header("FY2026");
    getForecast.mockReturnValue(new Promise(() => {}) as never);

    await user.click(screen.getByRole("radio", { name: "Quarterly" }));

    await waitFor(() => expect(lastQuery()?.query).toMatchObject({ freq: "quarterly" }));
    expect(screen.queryByText("Loading…")).toBeNull();
    expect(header("FY2026")).toBe(before);
  });

  it("ends the balance sheet with the Balance check row", async () => {
    getForecast.mockResolvedValue(okResult(forecastBalance()) as never);
    renderView();

    await loaded("balance_check");
    expect(cell("balance_check", "FY2026")).toHaveTextContent("✓");
    expect(cell("balance_check", "FY2026")).toHaveClass("cell-forecast");
  });

  it("shows the integrity checks and the engine's warnings under the grid", async () => {
    getForecast.mockResolvedValue(
      okResult(forecastIncome({ warnings: ["Debt repaid capped in FY2027"] })) as never,
    );
    renderView();

    expect(await screen.findByText("All checks pass")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /^FY27E\b/ })).toBeInTheDocument();
    expect(screen.getByText("Debt repaid capped in FY2027")).toBeInTheDocument();
  });

  it("adds the forecast line to the legend", async () => {
    renderView();

    expect(
      await screen.findByText("Forecast: built from the scenario's drivers"),
    ).toBeInTheDocument();
  });

  it("explains a missing driver and opens Scenarios on the same scenario", async () => {
    const user = userEvent.setup();
    getForecast.mockResolvedValue(
      errorResult(422, { detail: "Set these drivers: gross_margin" }) as never,
    );
    renderView("/c/AAPL/forecast?scenario=3");

    expect(await screen.findByText("Set these drivers: gross_margin")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Open Scenarios" }));

    expect(seen.path).toBe("/c/AAPL/scenarios");
    expect(seen.search).toBe("?scenario=3");
  });

  it("shows any other unavailable forecast without the Scenarios link", async () => {
    getForecast.mockResolvedValue(errorResult(422, { detail: "No quarterly history" }) as never);
    renderView();

    expect(await screen.findByText("No quarterly history")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open Scenarios" })).toBeNull();
  });

  it("shows loading, then a failure to load the forecast", async () => {
    getForecast.mockResolvedValue(errorResult(500, { detail: "boom" }) as never);
    renderView();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the forecast.")).toBeInTheDocument();
  });

  it("shows the reason the scenarios could not load", async () => {
    list.mockResolvedValue(errorResult(404, { detail: "Company not found" }) as never);
    renderView();

    expect(await screen.findByText("Company not found")).toBeInTheDocument();
    expect(getForecast).not.toHaveBeenCalled();
  });

  it("says so, without an error, when the company has no scenario", async () => {
    list.mockResolvedValue(okResult([]) as never);
    renderView();

    expect(await screen.findByText("No scenarios.")).not.toHaveClass("text-destructive");
    expect(getForecast).not.toHaveBeenCalled();
  });

  it("marks the shown forecast as updating while the next frequency loads", async () => {
    const user = userEvent.setup();
    renderView();
    await loaded();
    expect(screen.queryByText("Updating…")).toBeNull();
    getForecast.mockReturnValue(new Promise(() => {}) as never);

    await user.click(screen.getByRole("radio", { name: "Quarterly" }));

    expect(await screen.findByText("Updating…")).toBeInTheDocument();
  });

  it("says so when the forecast has no line to show", async () => {
    getForecast.mockResolvedValue(okResult(forecastIncome({ rows: [] })) as never);
    renderView();

    expect(await screen.findByText("No forecast lines to show.")).toBeInTheDocument();
  });
});
