import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getMultiplesApiV1CompaniesTickerMultiplesGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { multiples } from "@/test/analysis";
import { errorResult, okResult } from "@/test/responses";

import { MultiplesTable } from "./MultiplesTable";

vi.mock("@/api/generated/sdk.gen", () => ({
  getMultiplesApiV1CompaniesTickerMultiplesGet: vi.fn(),
}));

function renderTable(basis: "reported" | "normalized" = "reported") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MultiplesTable ticker="AAPL" basis={basis} />
    </QueryClientProvider>,
  );
}

const row = (label: string) => screen.getByRole("row", { name: new RegExp(`^${label}`) });

beforeEach(() => {
  vi.mocked(getMultiplesApiV1CompaniesTickerMultiplesGet).mockResolvedValue(
    okResult(multiples()) as never,
  );
});
afterEach(() => vi.clearAllMocks());

describe("MultiplesTable", () => {
  it("requests the multiples of the chosen basis", async () => {
    renderTable("normalized");
    await screen.findByText("P/E");
    expect(getMultiplesApiV1CompaniesTickerMultiplesGet).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { basis: "normalized" },
    });
  });

  it("shows the price and its date", async () => {
    renderTable();
    expect(await screen.findByText(/Price 250\.50 on 2026-10-07/)).toBeInTheDocument();
  });

  it("shows current, min, median, max and the percentile of a multiple", async () => {
    renderTable();
    await screen.findByText("P/E");
    const cells = within(row("P/E"))
      .getAllByRole("cell")
      .map((c) => c.textContent);
    expect(cells.slice(1, 6)).toEqual(["32.5x", "10.2x", "24.9x", "38.1x", "85th"]);
    expect(within(row("P/E")).getByRole("meter")).toHaveAttribute("aria-valuenow", "85");
  });

  it("formats a pct multiple as a percent and shows a dash for no current value", async () => {
    renderTable();
    await screen.findByText("FCF yield");
    const cells = within(row("FCF yield"))
      .getAllByRole("cell")
      .map((c) => c.textContent);
    expect(cells.slice(1, 6)).toEqual(["—", "2.0%", "4.0%", "7.0%", "—"]);
  });

  it("marks a row without enough history and a caveat with †", async () => {
    renderTable();
    await screen.findByText("EV/Sales †");
    expect(within(row("EV/Sales")).getByText("2 yrs")).toBeInTheDocument();
    expect(screen.getByText(/† EV\/Sales: Enterprise value includes/)).toBeInTheDocument();
  });

  it("says so when the company has no price", async () => {
    vi.mocked(getMultiplesApiV1CompaniesTickerMultiplesGet).mockResolvedValue(
      okResult(multiples({ price: null, price_date: null })) as never,
    );
    renderTable();
    expect(await screen.findByText(/No price stored/)).toBeInTheDocument();
  });

  it("shows an error when the request fails", async () => {
    vi.mocked(getMultiplesApiV1CompaniesTickerMultiplesGet).mockResolvedValue(
      errorResult(500, { detail: "boom" }) as never,
    );
    renderTable();
    await waitFor(() =>
      expect(screen.getByText("Could not load the valuation multiples.")).toBeInTheDocument(),
    );
  });
});
