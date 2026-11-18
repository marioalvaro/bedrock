import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getSummaryApiV1CompaniesTickerSummaryGet,
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet,
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet,
  listImportsApiV1CompaniesTickerImportsGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { companyItem } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";
import { companySummary } from "@/test/summary";

import { Overview } from "./Overview";

vi.mock("@/api/generated/sdk.gen", () => ({
  getSummaryApiV1CompaniesTickerSummaryGet: vi.fn(),
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet: vi.fn(),
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet: vi.fn(),
  listImportsApiV1CompaniesTickerImportsGet: vi.fn(),
  importStatementsApiV1CompaniesTickerImportsPost: vi.fn(),
  deleteImportApiV1CompaniesTickerImportsImportIdDelete: vi.fn(),
}));

// jsdom cannot draw a canvas: the sparklines render their wrapper only.
vi.mock("echarts-for-react/esm/core", () => ({ default: vi.fn(() => null) }));

const getSummary = vi.mocked(getSummaryApiV1CompaniesTickerSummaryGet);

beforeEach(() => {
  getSummary.mockResolvedValue(okResult(companySummary()) as never);
  vi.mocked(listImportsApiV1CompaniesTickerImportsGet).mockResolvedValue(okResult([]) as never);
});

function renderOverview() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Overview company={companyItem()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

const region = (name: string) => screen.findByRole("region", { name });
const cells = (row: HTMLElement) =>
  within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);

describe("Overview", () => {
  it("shows the key stats, with a dash for one that is missing", async () => {
    renderOverview();

    const stats = await region("Key stats");
    expect(within(stats).getByText("Price")).toBeInTheDocument();
    expect(within(stats).getByText("231.40")).toBeInTheDocument();
    expect(within(stats).getByText("3.5T")).toBeInTheDocument();
    expect(within(stats).getByText("34.2x")).toBeInTheDocument();
    expect(within(stats).getByText("5.1%")).toBeInTheDocument();
    expect(within(stats).getByText("—")).toBeInTheDocument();
  });

  it("opens the import sheet from its import button", async () => {
    renderOverview();

    await userEvent.click(await screen.findByRole("button", { name: "Import" }));

    expect(await screen.findByText("Import statements")).toBeVisible();
  });

  it("leaves the data gaps, adjustments and corporate actions to the Data tab", async () => {
    renderOverview();
    await region("Key metrics");

    for (const name of ["Data gaps", "Adjustments", "Corporate actions"]) {
      expect(screen.queryByRole("region", { name })).not.toBeInTheDocument();
    }
    expect(getMappingGapsApiV1CompaniesTickerMappingGapsGet).not.toHaveBeenCalled();
    expect(listAdjustmentsApiV1CompaniesTickerAdjustmentsGet).not.toHaveBeenCalled();
    expect(listCorporateActionsApiV1CompaniesTickerCorporateActionsGet).not.toHaveBeenCalled();
    expect(
      screen.getByRole("link", {
        name: "Data gaps, adjustments and corporate actions are on the Data tab.",
      }),
    ).toHaveAttribute("href", "/c/AAPL/data");
  });

  it("asks for the company's summary", async () => {
    renderOverview();
    await region("Key metrics");

    expect(getSummary).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
  });
});

describe("key metrics", () => {
  it("lists the seven metrics in the API's order, under the five fiscal years", async () => {
    renderOverview();

    const table = within(await region("Key metrics")).getByRole("table");
    const [header, ...rows] = within(table).getAllByRole("row");
    expect(
      within(header!)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual([
      "Metric",
      "FY2021",
      "FY2022",
      "FY2023",
      "FY2024",
      "FY2025",
      "Trend",
      "Latest",
      "YoY",
    ]);
    expect(rows.map((row) => within(row).getByRole("rowheader").textContent)).toEqual([
      "Revenue",
      "Gross margin",
      "Operating margin",
      "FCF margin",
      "Return on invested capital",
      "EPS (diluted)",
      "Net debt / EBITDA",
    ]);
  });

  it.each([
    ["Revenue", ["365.8B", "394.3B", "383.3B", "391.0B", "416.2B", "", "416.2B", "+6.4%"]],
    ["Gross margin", ["41.8%", "43.3%", "44.1%", "46.2%", "46.9%", "", "46.9%", "+0.7 pts"]],
    ["EPS (diluted)", ["5.61", "6.11", "6.13", "6.08", "7.46", "", "7.46", "+22.7%"]],
    ["Net debt / EBITDA", ["0.4x", "0.4x", "0.4x", "0.3x", "0.2x", "", "0.2x", "-0.1x"]],
    // A year the ratio could not be computed for is a dash.
    [
      "Return on invested capital",
      ["—", "55.3%", "54.8%", "56.4%", "59.8%", "", "59.8%", "+3.4 pts"],
    ],
  ])("formats %s by its unit, the change against the year before included", async (label, want) => {
    renderOverview();

    const table = within(await region("Key metrics")).getByRole("table");
    const row = within(table).getByRole("rowheader", { name: label }).closest("tr")!;
    expect(cells(row)).toEqual(want);
  });

  it("draws a sparkline per metric", async () => {
    renderOverview();

    const metrics = await region("Key metrics");
    expect(within(metrics).getByRole("img", { name: "Revenue trend" })).toBeInTheDocument();
    expect(within(metrics).getAllByRole("img")).toHaveLength(7);
  });

  it("colors the change by its sign only", async () => {
    renderOverview();

    const metrics = await region("Key metrics");
    expect(within(metrics).getByText("+6.4%")).toHaveClass("text-positive");
    expect(within(metrics).getByText("-3.9 pts")).toHaveClass("text-negative");
    // Net debt falling is good news, but the color says only that the number went down.
    expect(within(metrics).getByText("-0.1x")).toHaveClass("text-negative");
  });

  it("says so when no metric has a year", async () => {
    const metrics = companySummary().metrics.map((m) => ({
      ...m,
      years: [],
      latest: null,
      yoy: null,
    }));
    getSummary.mockResolvedValue(okResult(companySummary({ metrics })) as never);
    renderOverview();

    const block = await region("Key metrics");
    expect(within(block).getByText("No annual figures yet.")).toBeInTheDocument();
    expect(within(block).queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("open flags", () => {
  it("lists each flag's rule, severity, value by its unit and period, linking to Quality", async () => {
    renderOverview();

    const block = await region("Open flags");
    const rows = within(block).getAllByRole("row");
    expect(rows.map(cells)).toEqual([
      ["Accruals ratio", "Alert", "12.3%", "FY26"],
      ["Receivables growing faster than revenue", "Warn", "1.8x", "FY26"],
    ]);
    expect(within(block).getByText("Alert")).toHaveClass("flag-alert");
    expect(within(block).getByText("Warn")).toHaveClass("flag-warn");
    expect(
      within(block).getByRole("link", { name: "All flags on the Quality tab" }),
    ).toHaveAttribute("href", "/c/AAPL/quality");
  });

  it("says so when no flag is open", async () => {
    getSummary.mockResolvedValue(okResult(companySummary({ flags: [] })) as never);
    renderOverview();

    expect(within(await region("Open flags")).getByText("No open flags.")).toBeInTheDocument();
  });
});

describe("valuation", () => {
  it("reads the range, the base value against the price and the upside, linking to Valuation", async () => {
    renderOverview();

    const link = within(await region("Valuation")).getByRole("link");
    expect(link).toHaveTextContent(
      "Value 180.25–265.10 per share · base 242.00 vs price 231.40 (+4.6%)",
    );
    expect(link).toHaveAttribute("href", "/c/AAPL/valuation");
  });

  it("shows dashes for a missing base value and price, and no upside", async () => {
    const valuation = { ...companySummary().valuation!, base: null, price: null, upside: null };
    getSummary.mockResolvedValue(okResult(companySummary({ valuation })) as never);
    renderOverview();

    expect(within(await region("Valuation")).getByRole("link").textContent).toBe(
      "Value 180.25–265.10 per share · base — vs price —",
    );
  });

  it("says so when the default scenario is not valued", async () => {
    getSummary.mockResolvedValue(okResult(companySummary({ valuation: null })) as never);
    renderOverview();

    const block = await region("Valuation");
    expect(within(block).getByText("No default scenario valued yet.")).toBeInTheDocument();
    expect(within(block).queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("forecast", () => {
  it("reads when the default scenario was updated and last snapshotted", async () => {
    renderOverview();

    const block = await region("Forecast");
    expect(block).toHaveTextContent("Base thesis updated 3d ago, last snapshot 5h ago");
    expect(within(block).queryByText(/Not updated since/)).not.toBeInTheDocument();
  });

  it("says never for a scenario with no snapshot", async () => {
    const forecast = { ...companySummary().forecast!, last_snapshot_at: null };
    getSummary.mockResolvedValue(okResult(companySummary({ forecast })) as never);
    renderOverview();

    expect(await region("Forecast")).toHaveTextContent("last snapshot never");
  });

  it("warns, linking to Scenarios, when a newer filing landed after the last update", async () => {
    const forecast = { ...companySummary().forecast!, stale: true };
    getSummary.mockResolvedValue(okResult(companySummary({ forecast })) as never);
    renderOverview();

    const stale = within(await region("Forecast")).getByRole("link", {
      name: "Not updated since the Oct 31, 2026 filing.",
    });
    expect(stale).toHaveAttribute("href", "/c/AAPL/scenarios");
    expect(stale).toHaveClass("text-flag-warn");
  });

  it("says so when there is no default scenario", async () => {
    getSummary.mockResolvedValue(okResult(companySummary({ forecast: null })) as never);
    renderOverview();

    expect(
      within(await region("Forecast")).getByText("No default scenario yet."),
    ).toBeInTheDocument();
  });
});

describe("latest notes", () => {
  it("lists the three excerpts with their dates, linking to Notes", async () => {
    renderOverview();

    const block = await region("Latest notes");
    const items = within(block).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Nov 2, 2026Services margin keeps widening.",
      "Oct 20, 2026Buyback pace slowed in Q3.",
      "Sep 1, 2026Thesis: installed base monetisation.",
    ]);
    expect(within(block).getByRole("link", { name: "All notes" })).toHaveAttribute(
      "href",
      "/c/AAPL/notes",
    );
  });

  it("says so when there is no note", async () => {
    getSummary.mockResolvedValue(okResult(companySummary({ notes: [] })) as never);
    renderOverview();

    expect(within(await region("Latest notes")).getByText("No notes yet.")).toBeInTheDocument();
  });
});

describe("summary states", () => {
  it("shows the warnings of the blocks that could not be computed", async () => {
    getSummary.mockResolvedValue(
      okResult(
        companySummary({
          valuation: null,
          warnings: ["Valuation, bear case: WACC must exceed the terminal growth rate"],
        }),
      ) as never,
    );
    renderOverview();

    const warnings = await screen.findByRole("list", { name: "Summary warnings" });
    expect(
      within(warnings).getByText("Valuation, bear case: WACC must exceed the terminal growth rate"),
    ).toHaveClass("text-muted-foreground");
  });

  it("shows no warning list when there is none", async () => {
    renderOverview();
    await region("Key metrics");

    expect(screen.queryByRole("list", { name: "Summary warnings" })).not.toBeInTheDocument();
  });

  it("keeps the key stats while the summary loads", async () => {
    getSummary.mockReturnValue(new Promise(() => {}) as never);
    renderOverview();

    expect(await region("Key stats")).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Key metrics" })).not.toBeInTheDocument();
  });

  it.each([
    ["an error", errorResult(500)],
    ["a 200 that is not a summary (G2/G4)", okResult("<!doctype html>")],
  ])("says the summary could not load on %s, keeping the key stats", async (_name, result) => {
    getSummary.mockResolvedValue(result as never);
    renderOverview();

    expect(await screen.findByText("Could not load the summary.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Key stats" })).toBeInTheDocument();
  });
});
