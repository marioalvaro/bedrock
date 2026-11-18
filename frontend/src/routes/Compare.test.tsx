import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCompaniesApiV1CompaniesGet,
  getSummaryApiV1CompaniesTickerSummaryGet,
} from "@/api/generated/sdk.gen";
import { Chart } from "@/components/Chart";
import { createQueryClient } from "@/lib/query-client";
import { companyItem } from "@/test/companies";
import { LocationProbe } from "@/test/LocationProbe";
import { errorResult, okResult } from "@/test/responses";
import { companySummary } from "@/test/summary";

import { Compare } from "./Compare";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
  getSummaryApiV1CompaniesTickerSummaryGet: vi.fn(),
}));
vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));
const chart = vi.mocked(Chart);
const getCompanies = vi.mocked(getCompaniesApiV1CompaniesGet);
const getSummary = vi.mocked(getSummaryApiV1CompaniesTickerSummaryGet);

const companies = () => [
  companyItem(),
  companyItem({ id: 2, ticker: "MSFT", name: "Microsoft", price: "410.10", pe: null }),
  companyItem({ id: 3, ticker: "COST", name: "Costco", fiscal_year_end_month: 8 }),
  companyItem({ id: 4, ticker: "DE", name: "Deere" }),
];

// MSFT: the same metrics, its own fiscal years (FY2022–FY2026) and its own latest values.
function msftSummary() {
  const base = companySummary();
  return companySummary({
    ticker: "MSFT",
    metrics: base.metrics.map((metric) => ({
      ...metric,
      years: metric.years.map((year) => ({ ...year, fiscal_year: year.fiscal_year + 1 })),
      latest: metric.code === "revenue" ? "281724000000" : metric.latest,
    })),
  });
}

let search = "";
const onSearch = (next: string) => {
  search = next;
};

function renderCompare(path = "/compare?t=AAPL,MSFT") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Compare />
        <LocationProbe onSearch={onSearch} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getCompanies.mockResolvedValue(okResult(companies()) as never);
  getSummary.mockImplementation((({ path }: { path: { ticker: string } }) =>
    Promise.resolve(
      okResult(path.ticker === "MSFT" ? msftSummary() : companySummary({ ticker: path.ticker })),
    )) as never);
});
afterEach(() => vi.clearAllMocks());

const chip = (ticker: string) => screen.findByRole("button", { name: ticker });
const rowOf = (table: HTMLElement, label: string) =>
  within(table)
    .getAllByRole("row")
    .find((row) => within(row).queryByRole("rowheader")?.textContent === label)!;
const cells = (row: HTMLElement) =>
  within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
const lastOption = () => chart.mock.lastCall![0].option as EChartsOption;

describe("Compare", () => {
  it("offers a chip per followed company, the ones in ?t= pressed", async () => {
    renderCompare();

    expect(await chip("AAPL")).toHaveAttribute("aria-pressed", "true");
    expect(await chip("MSFT")).toHaveAttribute("aria-pressed", "true");
    expect(await chip("COST")).toHaveAttribute("aria-pressed", "false");
  });

  it("adds and removes a company through its chip, keeping ?t=", async () => {
    renderCompare();

    await userEvent.click(await chip("COST"));
    await waitFor(() => expect(new URLSearchParams(search).get("t")).toBe("AAPL,MSFT,COST"));
    await userEvent.click(await chip("AAPL"));
    await waitFor(() => expect(new URLSearchParams(search).get("t")).toBe("MSFT,COST"));
  });

  it("takes six companies at most", async () => {
    const many = ["AAPL", "MSFT", "COST", "DE", "NVDA", "KO", "PEP"].map((ticker, at) =>
      companyItem({ id: at + 1, ticker }),
    );
    getCompanies.mockResolvedValue(okResult(many) as never);
    renderCompare("/compare?t=AAPL,MSFT,COST,DE,NVDA,KO,PEP");

    expect(await chip("KO")).toHaveAttribute("aria-pressed", "true");
    expect(await chip("PEP")).toHaveAttribute("aria-pressed", "false");
    expect(await chip("PEP")).toBeDisabled();
    expect(getSummary).toHaveBeenCalledTimes(6);
  });

  it("asks for a second company while fewer than two are chosen", async () => {
    renderCompare("/compare?t=AAPL");

    expect(await screen.findByText("Choose two to six companies to compare.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Comparison" })).not.toBeInTheDocument();
  });

  it("ignores a ticker that is not followed", async () => {
    renderCompare("/compare?t=AAPL,ZZZZ");

    expect(await screen.findByText("Choose two to six companies to compare.")).toBeInTheDocument();
    expect(getSummary).not.toHaveBeenCalledWith({ path: { ticker: "ZZZZ" } });
  });

  it("tables the key stats, then each summary metric's latest value, a column per ticker", async () => {
    renderCompare();

    const table = await screen.findByRole("table", { name: "Comparison" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["", "AAPL", "MSFT"]);
    expect(cells(rowOf(table, "Price"))).toEqual(["231.40", "410.10"]);
    expect(cells(rowOf(table, "Market cap"))).toEqual(["3.5T", "3.5T"]);
    expect(cells(rowOf(table, "P/E"))).toEqual(["34.2x", "—"]);
    expect(cells(rowOf(table, "Revenue growth"))).toEqual(["5.1%", "5.1%"]);
    await waitFor(() => expect(cells(rowOf(table, "Revenue"))).toEqual(["416.2B", "281.7B"]));
    expect(cells(rowOf(table, "Gross margin"))).toEqual(["46.9%", "46.9%"]);
    expect(cells(rowOf(table, "EPS (diluted)"))).toEqual(["7.46", "7.46"]);
    expect(cells(rowOf(table, "Net debt / EBITDA"))).toEqual(["0.2x", "0.2x"]);
  });

  it("shows a dash and a muted line for a company whose summary fails", async () => {
    getSummary.mockImplementation((({ path }: { path: { ticker: string } }) =>
      Promise.resolve(
        path.ticker === "MSFT" ? errorResult(500) : okResult(companySummary()),
      )) as never);
    renderCompare();

    expect(await screen.findByText("Could not load the summary of MSFT.")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Comparison" });
    expect(cells(rowOf(table, "Revenue"))).toEqual(["416.2B", "—"]);
  });

  it("charts the chosen metric's years per ticker, by fiscal-year label", async () => {
    renderCompare();

    await waitFor(() => expect(chart).toHaveBeenCalled());
    await waitFor(() => expect((lastOption().series as LineSeriesOption[]).length).toBe(2));
    expect(lastOption().xAxis).toMatchObject({
      type: "category",
      data: ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025", "FY2026"],
    });
    const [aapl, msft] = lastOption().series as LineSeriesOption[];
    expect(aapl!.name).toBe("AAPL");
    expect(aapl!.data).toEqual([
      365817000000,
      394328000000,
      383285000000,
      391035000000,
      416161000000,
      null,
    ]);
    expect(msft!.data).toEqual([
      null,
      365817000000,
      394328000000,
      383285000000,
      391035000000,
      416161000000,
    ]);
    expect(chart.mock.lastCall![0].ariaLabel).toBe("Revenue by fiscal year");
    expect(screen.getByText("Fiscal years as each company reports them.")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Chart metric" }), "roic");
    expect(chart.mock.lastCall![0].ariaLabel).toBe("Return on invested capital by fiscal year");
    expect((lastOption().series as LineSeriesOption[])[0]!.data).toEqual([
      null,
      0.553,
      0.548,
      0.564,
      0.598,
      null,
    ]);
  });

  it("says there is nothing to chart when no summary has a metric", async () => {
    getSummary.mockResolvedValue(okResult(companySummary({ metrics: [] })) as never);
    renderCompare();

    expect(await screen.findByText("No data to chart.")).toHaveClass("text-muted-foreground");
    expect(chart).not.toHaveBeenCalled();
  });

  it("shows loading and error lines for the company list", async () => {
    getCompanies.mockReturnValue(new Promise(() => {}) as never);
    renderCompare();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says so when the company list cannot load", async () => {
    getCompanies.mockResolvedValue(errorResult(500) as never);
    renderCompare();
    expect(await screen.findByText("Could not load the companies.")).toBeInTheDocument();
  });

  it("says so when nothing is followed", async () => {
    getCompanies.mockResolvedValue(okResult([]) as never);
    renderCompare();
    expect(
      await screen.findByText("No companies yet. Add some on the Companies page."),
    ).toBeInTheDocument();
  });
});
