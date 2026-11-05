import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet,
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet,
  getCompanyApiV1CompaniesTickerGet,
  getFlagsApiV1CompaniesTickerFlagsGet,
  getGuidanceApiV1CompaniesTickerGuidanceGet,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getRatiosApiV1CompaniesTickerRatiosGet,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  getStatementApiV1CompaniesTickerStatementsGet,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
  listScenariosApiV1CompaniesTickerScenariosGet,
  listSetsApiV1CompaniesTickerCompsSetsGet,
  refreshApiV1CompaniesTickerRefreshPost,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { capitalAllocation, flags, ratios } from "@/test/analysis";
import { companyItem, mappingGaps } from "@/test/companies";
import { guidance, note, segments } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import { scenarios } from "@/test/scenarios";
import { incomeStatement } from "@/test/statements";

import { Company } from "./Company";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompanyApiV1CompaniesTickerGet: vi.fn(),
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  getRatiosApiV1CompaniesTickerRatiosGet: vi.fn(),
  getFlagsApiV1CompaniesTickerFlagsGet: vi.fn(),
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet: vi.fn(),
  getSegmentsApiV1CompaniesTickerSegmentsGet: vi.fn(),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  listSetsApiV1CompaniesTickerCompsSetsGet: vi.fn(),
  getGuidanceApiV1CompaniesTickerGuidanceGet: vi.fn(),
  listMetricsApiV1CompaniesTickerGuidanceMetricsGet: vi.fn(),
  refreshApiV1CompaniesTickerRefreshPost: vi.fn(),
  listScenariosApiV1CompaniesTickerScenariosGet: vi.fn(),
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet: vi.fn(
    () => new Promise(() => {}),
  ),
  compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet: vi.fn(() => new Promise(() => {})),
  getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet: vi.fn(
    () => new Promise(() => {}),
  ),
}));

function renderAt(path: string) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="c/:ticker/:tab?" element={<Company />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(okResult(companyItem()) as never);
  vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
    okResult(mappingGaps()) as never,
  );
  vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
    okResult(incomeStatement()) as never,
  );
  vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mockResolvedValue(okResult(ratios()) as never);
  vi.mocked(listScenariosApiV1CompaniesTickerScenariosGet).mockResolvedValue(
    okResult(scenarios()) as never,
  );
  vi.mocked(getSegmentsApiV1CompaniesTickerSegmentsGet).mockResolvedValue(
    okResult(segments()) as never,
  );
  vi.mocked(listNotesApiV1CompaniesTickerNotesGet).mockResolvedValue(
    okResult([note({ body_md: "Thesis text" })]) as never,
  );
  vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet).mockResolvedValue(okResult([]) as never);
  vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(okResult(flags()) as never);
  vi.mocked(listSetsApiV1CompaniesTickerCompsSetsGet).mockResolvedValue(okResult([]) as never);
  vi.mocked(getGuidanceApiV1CompaniesTickerGuidanceGet).mockResolvedValue(
    okResult(guidance()) as never,
  );
  vi.mocked(getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet).mockResolvedValue(
    okResult(capitalAllocation()) as never,
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("company header", () => {
  it("shows the ticker, name, price, market cap and last refresh", async () => {
    renderAt("/c/AAPL");

    expect(await screen.findByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByTestId("header-price")).toHaveTextContent("231.40");
    expect(screen.getByTestId("header-market-cap")).toHaveTextContent("3.5T");
    expect(screen.getByText("Refreshed 2h ago")).toBeInTheDocument();
  });

  it("says when the company is not followed", async () => {
    vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
      errorResult(404, { detail: "ZZZZ is not followed." }) as never,
    );
    renderAt("/c/ZZZZ");

    expect(await screen.findByText("Company not found.")).toBeInTheDocument();
  });
});

describe("refresh", () => {
  it("refreshes the company and then shows the new refresh time", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      okResult({
        ticker: "AAPL",
        new_filings: 1,
        new_facts: 10,
        new_prices: 3,
        last_refreshed_at: new Date().toISOString(),
        warnings: [],
      }) as never,
    );
    renderAt("/c/AAPL");
    await screen.findByText("Refreshed 2h ago");
    vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
      okResult(companyItem({ last_refreshed_at: new Date().toISOString() })) as never,
    );

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(refreshApiV1CompaniesTickerRefreshPost).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
    });
    expect(await screen.findByText("Refreshed just now")).toBeInTheDocument();
  });

  it("shows the API's reason when the refresh fails", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      errorResult(502, { detail: "SEC EDGAR is unavailable." }) as never,
    );
    renderAt("/c/AAPL");

    await userEvent.click(await screen.findByRole("button", { name: "Refresh" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("SEC EDGAR is unavailable.");
  });

  it("shows a refresh warning, such as a price failure", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      okResult({
        ticker: "AAPL",
        new_filings: 0,
        new_facts: 0,
        new_prices: 0,
        last_refreshed_at: new Date().toISOString(),
        warnings: ["Prices could not be updated."],
      }) as never,
    );
    renderAt("/c/AAPL");

    await userEvent.click(await screen.findByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("Prices could not be updated.")).toBeInTheDocument();
  });
});

describe("tabs", () => {
  it("links the statement tabs by slug", async () => {
    renderAt("/c/AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/c/AAPL");
    expect(screen.getByRole("link", { name: "Income" })).toHaveAttribute("href", "/c/AAPL/income");
    expect(screen.getByRole("link", { name: "Balance" })).toHaveAttribute(
      "href",
      "/c/AAPL/balance",
    );
    expect(screen.getByRole("link", { name: "Cash Flow" })).toHaveAttribute(
      "href",
      "/c/AAPL/cash-flow",
    );
  });

  it("shows the overview by default", async () => {
    renderAt("/c/AAPL");

    expect(await screen.findByRole("region", { name: "Data gaps" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(getStatementApiV1CompaniesTickerStatementsGet).not.toHaveBeenCalled();
  });

  it.each([
    ["income", "IS", "Income"],
    ["balance", "BS", "Balance"],
    ["cash-flow", "CF", "Cash Flow"],
  ])("routes /%s to the %s statement", async (slug, type, name) => {
    renderAt(`/c/AAPL/${slug}`);

    expect(await screen.findByText("Revenue")).toBeInTheDocument();
    expect(getStatementApiV1CompaniesTickerStatementsGet).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { type, freq: "annual", common_size_base: "total", basis: "reported" },
    });
    expect(screen.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  });

  it("falls back to the overview for an unknown tab", async () => {
    renderAt("/c/AAPL/nonsense");

    expect(await screen.findByRole("region", { name: "Data gaps" })).toBeInTheDocument();
  });

  it("routes /segments to the segments grid", async () => {
    renderAt("/c/AAPL/segments");

    expect(await screen.findByText("Americas")).toBeInTheDocument();
    expect(getSegmentsApiV1CompaniesTickerSegmentsGet).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { freq: "annual" },
    });
    expect(screen.getByRole("link", { name: "Segments" })).toHaveAttribute("aria-current", "page");
  });

  it("routes /notes to the notes journal", async () => {
    renderAt("/c/AAPL/notes");

    expect(await screen.findByText("Thesis text")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Notes" })).toHaveAttribute("aria-current", "page");
  });

  it("lists the thirteen tabs in order, the analysis tabs after Cash Flow", async () => {
    renderAt("/c/AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    const links = within(screen.getByRole("navigation")).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Overview",
      "Income",
      "Balance",
      "Cash Flow",
      "Ratios",
      "Quality",
      "Capital",
      "Segments",
      "Comps",
      "Guidance",
      "Forecast",
      "Scenarios",
      "Notes",
    ]);
    expect(screen.getByRole("link", { name: "Ratios" })).toHaveAttribute("href", "/c/AAPL/ratios");
    expect(screen.getByRole("link", { name: "Quality" })).toHaveAttribute(
      "href",
      "/c/AAPL/quality",
    );
    expect(screen.getByRole("link", { name: "Capital" })).toHaveAttribute(
      "href",
      "/c/AAPL/capital",
    );
    expect(screen.getByRole("link", { name: "Segments" })).toHaveAttribute(
      "href",
      "/c/AAPL/segments",
    );
    expect(screen.getByRole("link", { name: "Comps" })).toHaveAttribute("href", "/c/AAPL/comps");
    expect(screen.getByRole("link", { name: "Guidance" })).toHaveAttribute(
      "href",
      "/c/AAPL/guidance",
    );
    expect(screen.getByRole("link", { name: "Forecast" })).toHaveAttribute(
      "href",
      "/c/AAPL/forecast",
    );
    expect(screen.getByRole("link", { name: "Scenarios" })).toHaveAttribute(
      "href",
      "/c/AAPL/scenarios",
    );
    expect(screen.getByRole("link", { name: "Notes" })).toHaveAttribute("href", "/c/AAPL/notes");
  });

  it("routes /forecast to the picked scenario and case's forecast and marks the tab", async () => {
    renderAt("/c/AAPL/forecast?scenario=2&case=bear");

    await waitFor(() =>
      expect(
        getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { ticker: "AAPL", scenario_id: 2, case: "bear" },
          query: { type: "IS", freq: "annual" },
        }),
      ),
    );
    expect(screen.getByRole("link", { name: "Forecast" })).toHaveAttribute("aria-current", "page");
  });

  it("keeps the picked scenario and case on the Forecast and Scenarios links only", async () => {
    renderAt("/c/AAPL/scenarios?scenario=2&case=bull");
    await screen.findByRole("heading", { name: "AAPL" });
    expect(screen.getByRole("link", { name: "Forecast" })).toHaveAttribute(
      "href",
      "/c/AAPL/forecast?scenario=2&case=bull",
    );
    expect(screen.getByRole("link", { name: "Scenarios" })).toHaveAttribute(
      "href",
      "/c/AAPL/scenarios?scenario=2&case=bull",
    );
    expect(screen.getByRole("link", { name: "Notes" })).toHaveAttribute("href", "/c/AAPL/notes");
  });

  it("carries a lone ?case without adding a ?scenario", async () => {
    renderAt("/c/AAPL/scenarios?case=bear");
    await screen.findByRole("heading", { name: "AAPL" });
    expect(screen.getByRole("link", { name: "Forecast" })).toHaveAttribute(
      "href",
      "/c/AAPL/forecast?case=bear",
    );
  });

  it.each([
    ["ratios", "Ratios", getRatiosApiV1CompaniesTickerRatiosGet],
    ["quality", "Quality", getFlagsApiV1CompaniesTickerFlagsGet],
    ["capital", "Capital", getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet],
    ["comps", "Comps", listSetsApiV1CompaniesTickerCompsSetsGet],
    ["guidance", "Guidance", getGuidanceApiV1CompaniesTickerGuidanceGet],
    ["scenarios", "Scenarios", listScenariosApiV1CompaniesTickerScenariosGet],
  ])("routes /%s to its view and marks the tab", async (slug, name, sdk) => {
    renderAt(`/c/AAPL/${slug}`);

    await waitFor(() =>
      expect(sdk).toHaveBeenCalledWith(expect.objectContaining({ path: { ticker: "AAPL" } })),
    );
    expect(screen.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("region", { name: "Data gaps" })).not.toBeInTheDocument();
  });

  it("requests ratios when the Ratios tab is clicked from Income", async () => {
    renderAt("/c/AAPL/income");
    await screen.findByText("Revenue");
    expect(getRatiosApiV1CompaniesTickerRatiosGet).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("link", { name: "Ratios" }));

    await waitFor(() => expect(getRatiosApiV1CompaniesTickerRatiosGet).toHaveBeenCalled());
    expect(screen.getByRole("link", { name: "Ratios" })).toHaveAttribute("aria-current", "page");
  });

  it("switches views when a tab is clicked", async () => {
    renderAt("/c/AAPL");

    await userEvent.click(await screen.findByRole("link", { name: "Income" }));

    expect(await screen.findByText("Revenue")).toBeInTheDocument();
  });
});
