import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBacktestApiV1CompaniesTickerBacktestGet,
  getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet,
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet,
  getCompaniesApiV1CompaniesGet,
  getCompanyApiV1CompaniesTickerGet,
  getSummaryApiV1CompaniesTickerSummaryGet,
  getEarningsReviewApiV1CompaniesTickerEarningsReviewGet,
  getFlagsApiV1CompaniesTickerFlagsGet,
  getGuidanceApiV1CompaniesTickerGuidanceGet,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getRatiosApiV1CompaniesTickerRatiosGet,
  getSeasonalityApiV1CompaniesTickerSeasonalityGet,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  getStatementApiV1CompaniesTickerStatementsGet,
  getStatusApiV1ClassificationStatusGet,
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet,
  listCheckpointsApiV1CompaniesTickerCheckpointsGet,
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet,
  listImportsApiV1CompaniesTickerImportsGet,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
  listScenariosApiV1CompaniesTickerScenariosGet,
  listSetsApiV1CompaniesTickerCompsSetsGet,
  refreshApiV1CompaniesTickerRefreshPost,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { capitalAllocation, flags, ratios } from "@/test/analysis";
import { checkpointList } from "@/test/checkpoints";
import { noClassifierStatus } from "@/test/classification";
import { companyItem, mappingGaps } from "@/test/companies";
import { guidance, note, segments } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import { companySummary } from "@/test/summary";
import { earningsReview } from "@/test/review";
import { scenarios } from "@/test/scenarios";
import { incomeStatement } from "@/test/statements";

import { Company } from "./Company";

// jsdom cannot draw a canvas: the Overview's sparklines render their wrapper only.
vi.mock("echarts-for-react/esm/core", () => ({ default: vi.fn(() => null) }));

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
  getCompanyApiV1CompaniesTickerGet: vi.fn(),
  getSummaryApiV1CompaniesTickerSummaryGet: vi.fn(),
  getEarningsReviewApiV1CompaniesTickerEarningsReviewGet: vi.fn(),
  listCheckpointsApiV1CompaniesTickerCheckpointsGet: vi.fn(),
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet: vi.fn(),
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet: vi.fn(),
  listImportsApiV1CompaniesTickerImportsGet: vi.fn(),
  getStatusApiV1ClassificationStatusGet: vi.fn(),
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  getRatiosApiV1CompaniesTickerRatiosGet: vi.fn(),
  getFlagsApiV1CompaniesTickerFlagsGet: vi.fn(),
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet: vi.fn(),
  getSegmentsApiV1CompaniesTickerSegmentsGet: vi.fn(),
  getSeasonalityApiV1CompaniesTickerSeasonalityGet: vi.fn(() => new Promise(() => {})),
  getBacktestApiV1CompaniesTickerBacktestGet: vi.fn(() => new Promise(() => {})),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  listSetsApiV1CompaniesTickerCompsSetsGet: vi.fn(),
  getGuidanceApiV1CompaniesTickerGuidanceGet: vi.fn(),
  listMetricsApiV1CompaniesTickerGuidanceMetricsGet: vi.fn(),
  refreshApiV1CompaniesTickerRefreshPost: vi.fn(),
  backfillFilingsApiV1CompaniesTickerBackfillFilingsPost: vi.fn(),
  listScenariosApiV1CompaniesTickerScenariosGet: vi.fn(),
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet: vi.fn(
    () => new Promise(() => {}),
  ),
  compareCasesApiV1CompaniesTickerScenariosScenarioIdCompareGet: vi.fn(() => new Promise(() => {})),
  getForecastApiV1CompaniesTickerScenariosScenarioIdCasesCaseForecastGet: vi.fn(
    () => new Promise(() => {}),
  ),
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet: vi.fn(
    () => new Promise(() => {}),
  ),
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet: vi.fn(
    () => new Promise(() => {}),
  ),
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet: vi.fn(
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
  vi.mocked(getSummaryApiV1CompaniesTickerSummaryGet).mockResolvedValue(
    okResult(companySummary()) as never,
  );
  vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
    okResult(mappingGaps()) as never,
  );
  vi.mocked(listAdjustmentsApiV1CompaniesTickerAdjustmentsGet).mockResolvedValue(
    okResult([]) as never,
  );
  vi.mocked(listCorporateActionsApiV1CompaniesTickerCorporateActionsGet).mockResolvedValue(
    okResult([]) as never,
  );
  vi.mocked(listImportsApiV1CompaniesTickerImportsGet).mockResolvedValue(okResult([]) as never);
  vi.mocked(getStatusApiV1ClassificationStatusGet).mockResolvedValue(
    okResult(noClassifierStatus()) as never,
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
  vi.mocked(getEarningsReviewApiV1CompaniesTickerEarningsReviewGet).mockResolvedValue(
    okResult(earningsReview()) as never,
  );
  vi.mocked(listCheckpointsApiV1CompaniesTickerCheckpointsGet).mockResolvedValue(
    okResult(checkpointList()) as never,
  );
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

  it("puts the ticker heading in the company switcher, which opens another company on the same tab (FR-WS-06)", async () => {
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(
      okResult([companyItem(), companyItem({ id: 2, ticker: "MSFT", name: "Microsoft" })]) as never,
    );
    vi.mocked(getCompanyApiV1CompaniesTickerGet).mockImplementation(
      (options) =>
        Promise.resolve(
          okResult(
            options.path.ticker === "MSFT"
              ? companyItem({ id: 2, ticker: "MSFT", name: "Microsoft" })
              : companyItem(),
          ),
        ) as never,
    );
    renderAt("/c/AAPL/ratios");

    const button = await screen.findByRole("button", { name: "Switch company" });
    expect(within(button).getByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    await userEvent.click(button);
    await screen.findByRole("option", { name: /MSFT/ });
    await userEvent.keyboard("ms{Enter}");

    expect(await screen.findByRole("heading", { name: "MSFT" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ratios" })).toHaveAttribute("aria-current", "page");
    await waitFor(() =>
      expect(getRatiosApiV1CompaniesTickerRatiosGet).toHaveBeenCalledWith(
        expect.objectContaining({ path: { ticker: "MSFT" } }),
      ),
    );
  });

  it("marks a filing that is filed but not loaded yet (FR-DATA-23)", async () => {
    vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
      okResult(
        companyItem({
          new_filings: [{ form: "10-Q", filed_at: "2026-08-01", period_end: "2026-06-27" }],
        }),
      ) as never,
    );
    renderAt("/c/AAPL");

    expect(await screen.findByText("10-Q filed Aug 1")).toBeInTheDocument();
  });

  it("shows no mark when nothing is pending", async () => {
    renderAt("/c/AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    expect(screen.queryByText(/filed /)).not.toBeInTheDocument();
  });

  it("shows how many filings are read, with a button to read them all", async () => {
    vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
      okResult(companyItem({ filings_parsed: 12, filings_total: 70 })) as never,
    );
    renderAt("/c/AAPL");

    expect(await screen.findByText("Filings read: 12 of 70")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read all filings" })).toBeEnabled();
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

describe("the snapshot taken by a refresh (FR-ACC-05)", () => {
  const reply = (snapshotId: number | null) => ({
    ticker: "AAPL",
    new_filings: snapshotId === null ? 0 : 1,
    new_facts: 0,
    new_prices: 0,
    new_splits: 0,
    new_filing_lines: 0,
    snapshot_id: snapshotId,
    last_refreshed_at: new Date().toISOString(),
    warnings: [],
  });

  it("says the forecast was snapshotted and links to the review", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      okResult(reply(12)) as never,
    );
    renderAt("/c/AAPL");

    await userEvent.click(await screen.findByRole("button", { name: "Refresh" }));

    expect(
      await screen.findByText("Forecast snapshotted before loading the filing."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review the result" })).toHaveAttribute(
      "href",
      "/c/AAPL/review",
    );
  });

  it("refetches the review after a refresh, with no invalidation of its own", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      okResult(reply(12)) as never,
    );
    renderAt("/c/AAPL/review");
    await screen.findByText("FY26 · 10-K filed Oct 31, 2026");
    const review = vi.mocked(getEarningsReviewApiV1CompaniesTickerEarningsReviewGet);
    expect(review).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(review).toHaveBeenCalledTimes(2));
  });

  it("refetches the checkpoints after a refresh", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      okResult(reply(12)) as never,
    );
    renderAt("/c/AAPL/notes");
    await screen.findByText("Gross margin holds");
    const checkpoints = vi.mocked(listCheckpointsApiV1CompaniesTickerCheckpointsGet);
    expect(checkpoints).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(checkpoints).toHaveBeenCalledTimes(2));
  });

  it("drops the line when another company is opened", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      okResult(reply(12)) as never,
    );
    const queryClient = createQueryClient();
    queryClient.setDefaultOptions({ queries: { retry: false } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/c/AAPL"]}>
          <Link to="/c/MSFT">Open MSFT</Link>
          <Routes>
            <Route path="c/:ticker/:tab?" element={<Company />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Refresh" }));
    await screen.findByText("Forecast snapshotted before loading the filing.");
    vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
      okResult(companyItem({ id: 2, ticker: "MSFT", name: "Microsoft" })) as never,
    );

    await userEvent.click(screen.getByRole("link", { name: "Open MSFT" }));

    expect(await screen.findByRole("heading", { name: "MSFT" })).toBeInTheDocument();
    expect(screen.queryByText(/Forecast snapshotted/)).not.toBeInTheDocument();
  });

  it("says nothing when the refresh took no snapshot", async () => {
    vi.mocked(refreshApiV1CompaniesTickerRefreshPost).mockResolvedValue(
      okResult(reply(null)) as never,
    );
    renderAt("/c/AAPL");

    await userEvent.click(await screen.findByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(refreshApiV1CompaniesTickerRefreshPost).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled());
    expect(screen.queryByText(/Forecast snapshotted/)).not.toBeInTheDocument();
  });
});

describe("tabs", () => {
  it("links the statement tabs by slug", async () => {
    renderAt("/c/AAPL/income");
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

    expect(await screen.findByRole("region", { name: "Key stats" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Key metrics" })).toBeInTheDocument();
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

    expect(await screen.findByRole("region", { name: "Key stats" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
  });

  it("routes /data to the Data tab with its three panels, in Financials (FR-WS-04)", async () => {
    renderAt("/c/AAPL/data");

    expect(await screen.findByRole("region", { name: "Data gaps" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Adjustments" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Corporate actions" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Key stats" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Data" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Financials" })).toHaveAttribute(
      "aria-current",
      "true",
    );
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

  it("lists the six groups in workflow order, each opening its first tab (FR-WS-05)", async () => {
    renderAt("/c/AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    const sections = screen.getByRole("navigation", { name: "Sections" });
    const links = within(sections).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Overview", "/c/AAPL"],
      ["Financials", "/c/AAPL/income"],
      ["Analysis", "/c/AAPL/ratios"],
      ["Model", "/c/AAPL/guidance"],
      ["Track", "/c/AAPL/backtest"],
      ["Notes", "/c/AAPL/notes"],
    ]);
  });

  it.each([
    ["income", "Financials", ["Income", "Balance", "Cash Flow", "Segments", "Data"]],
    ["data", "Financials", ["Income", "Balance", "Cash Flow", "Segments", "Data"]],
    ["comps", "Analysis", ["Ratios", "Capital", "Quality", "Seasonality", "Comps"]],
    ["valuation", "Model", ["Guidance", "Scenarios", "Forecast", "Valuation"]],
    ["review", "Track", ["Backtest", "Review"]],
  ])("on /%s shows the %s group's tabs in order on the second bar", async (slug, group, tabs) => {
    renderAt(`/c/AAPL/${slug}`);
    await screen.findByRole("heading", { name: "AAPL" });

    const second = screen.getByRole("navigation", { name: `${group} tabs` });
    expect(
      within(second)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(tabs);
    expect(
      within(second)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toEqual(tabs.map((label) => `/c/AAPL/${label.toLowerCase().replace(" ", "-")}`));
    const sections = screen.getByRole("navigation", { name: "Sections" });
    expect(within(sections).getByRole("link", { name: group })).toHaveAttribute(
      "aria-current",
      "true",
    );
    // Only the active group is marked.
    expect(
      within(sections)
        .getAllByRole("link")
        .filter((link) => link.hasAttribute("aria-current")),
    ).toHaveLength(1);
  });

  it.each([
    ["/c/AAPL", "Overview"],
    ["/c/AAPL/notes", "Notes"],
  ])("shows no second bar for a group with one tab (%s)", async (path, name) => {
    renderAt(path);
    await screen.findByRole("heading", { name: "AAPL" });

    expect(screen.getAllByRole("navigation")).toHaveLength(1);
    expect(screen.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  });

  it("opens a group's first tab on click, and its tabs on the second bar", async () => {
    renderAt("/c/AAPL");
    await screen.findByRole("heading", { name: "AAPL" });

    await userEvent.click(screen.getByRole("link", { name: "Track" }));

    expect(await screen.findByRole("navigation", { name: "Track tabs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Backtest" })).toHaveAttribute("aria-current", "page");
    expect(getBacktestApiV1CompaniesTickerBacktestGet).toHaveBeenCalled();
  });

  it("builds the group links through tabPath: Model opens Guidance, which takes no scenario", async () => {
    renderAt("/c/AAPL/scenarios?scenario=2&case=bull");
    await screen.findByRole("heading", { name: "AAPL" });

    expect(screen.getByRole("link", { name: "Model" })).toHaveAttribute("href", "/c/AAPL/guidance");
    expect(screen.getByRole("link", { name: "Track" })).toHaveAttribute("href", "/c/AAPL/backtest");
    expect(screen.getByRole("link", { name: "Guidance" })).toHaveAttribute(
      "href",
      "/c/AAPL/guidance",
    );
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

  it("routes /valuation to the picked scenario's valuation summary and marks the tab", async () => {
    renderAt("/c/AAPL/valuation?scenario=2&case=bear");

    await waitFor(() =>
      expect(
        getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
      ).toHaveBeenCalledWith(expect.objectContaining({ path: { ticker: "AAPL", scenario_id: 2 } })),
    );
    expect(screen.getByRole("link", { name: "Valuation" })).toHaveAttribute("aria-current", "page");
  });

  it("keeps the picked scenario and case on the Valuation, Forecast and Scenarios links only", async () => {
    renderAt("/c/AAPL/scenarios?scenario=2&case=bull");
    await screen.findByRole("heading", { name: "AAPL" });
    expect(screen.getByRole("link", { name: "Guidance" })).toHaveAttribute(
      "href",
      "/c/AAPL/guidance",
    );
    expect(screen.getByRole("link", { name: "Valuation" })).toHaveAttribute(
      "href",
      "/c/AAPL/valuation?scenario=2&case=bull",
    );
    expect(screen.getByRole("link", { name: "Forecast" })).toHaveAttribute(
      "href",
      "/c/AAPL/forecast?scenario=2&case=bull",
    );
    expect(screen.getByRole("link", { name: "Scenarios" })).toHaveAttribute(
      "href",
      "/c/AAPL/scenarios?scenario=2&case=bull",
    );
    expect(screen.getByRole("link", { name: "Notes" })).toHaveAttribute("href", "/c/AAPL/notes");
    expect(screen.getByRole("link", { name: "Analysis" })).toHaveAttribute(
      "href",
      "/c/AAPL/ratios",
    );
  });

  it("routes /review to the earnings review and marks the tab", async () => {
    renderAt("/c/AAPL/review?scenario=2");

    expect(await screen.findByText("FY26 · 10-K filed Oct 31, 2026")).toBeInTheDocument();
    const tab = screen.getByRole("link", { name: "Review" });
    expect(tab).toHaveAttribute("aria-current", "page");
    // Review sits in Track, beside Backtest (FR-WS-05).
    expect(screen.getByRole("link", { name: "Track" })).toHaveAttribute("aria-current", "true");
    // Not a scenario tab: the picked scenario does not travel to it.
    expect(tab).toHaveAttribute("href", "/c/AAPL/review");
  });

  it("does not carry the picked scenario to the Backtest tab", async () => {
    renderAt("/c/AAPL/review?scenario=2&case=bull");
    await screen.findByRole("heading", { name: "AAPL" });
    expect(screen.getByRole("link", { name: "Backtest" })).toHaveAttribute(
      "href",
      "/c/AAPL/backtest",
    );
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
    ["seasonality", "Seasonality", getSeasonalityApiV1CompaniesTickerSeasonalityGet],
    ["comps", "Comps", listSetsApiV1CompaniesTickerCompsSetsGet],
    ["guidance", "Guidance", getGuidanceApiV1CompaniesTickerGuidanceGet],
    ["scenarios", "Scenarios", listScenariosApiV1CompaniesTickerScenariosGet],
    ["backtest", "Backtest", getBacktestApiV1CompaniesTickerBacktestGet],
  ])("routes /%s to its view and marks the tab", async (slug, name, sdk) => {
    renderAt(`/c/AAPL/${slug}`);

    await waitFor(() =>
      expect(sdk).toHaveBeenCalledWith(expect.objectContaining({ path: { ticker: "AAPL" } })),
    );
    expect(screen.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("region", { name: "Data gaps" })).not.toBeInTheDocument();
  });

  it("requests ratios when the Analysis group is clicked from Income", async () => {
    renderAt("/c/AAPL/income");
    await screen.findByText("Revenue");
    expect(getRatiosApiV1CompaniesTickerRatiosGet).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("link", { name: "Analysis" }));

    await waitFor(() => expect(getRatiosApiV1CompaniesTickerRatiosGet).toHaveBeenCalled());
    expect(screen.getByRole("link", { name: "Ratios" })).toHaveAttribute("aria-current", "page");
  });

  it("switches views when a tab is clicked", async () => {
    renderAt("/c/AAPL/segments");

    await userEvent.click(await screen.findByRole("link", { name: "Income" }));

    expect(await screen.findByText("Revenue")).toBeInTheDocument();
  });
});
