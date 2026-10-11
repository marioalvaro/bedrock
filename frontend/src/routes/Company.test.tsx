import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCompanyApiV1CompaniesTickerGet,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getStatementApiV1CompaniesTickerStatementsGet,
  refreshApiV1CompaniesTickerRefreshPost,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { companyItem, mappingGaps } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";
import { incomeStatement } from "@/test/statements";

import { Company } from "./Company";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompanyApiV1CompaniesTickerGet: vi.fn(),
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  refreshApiV1CompaniesTickerRefreshPost: vi.fn(),
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
  it("links the four tabs by slug", async () => {
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
      query: { type, freq: "annual", common_size_base: "total" },
    });
    expect(screen.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  });

  it("falls back to the overview for an unknown tab", async () => {
    renderAt("/c/AAPL/ratios");

    expect(await screen.findByRole("region", { name: "Data gaps" })).toBeInTheDocument();
  });

  it("switches views when a tab is clicked", async () => {
    renderAt("/c/AAPL");

    await userEvent.click(await screen.findByRole("link", { name: "Income" }));

    expect(await screen.findByText("Revenue")).toBeInTheDocument();
  });
});
