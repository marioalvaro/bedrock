import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  backfillFilingsApiV1CompaniesTickerBackfillFilingsPost,
  getCompanyApiV1CompaniesTickerGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { companyItem } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import { FilingsStatus } from "./FilingsStatus";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompanyApiV1CompaniesTickerGet: vi.fn(),
  backfillFilingsApiV1CompaniesTickerBackfillFilingsPost: vi.fn(),
}));

const backfill = vi.mocked(backfillFilingsApiV1CompaniesTickerBackfillFilingsPost);
const getCompany = vi.mocked(getCompanyApiV1CompaniesTickerGet);
const POLL_MS = 20;

function renderStatus(company = companyItem({ filings_parsed: 4, filings_total: 70 })) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <FilingsStatus company={company} pollMs={POLL_MS} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

// The company as successive polls see it: the count rises, then stays.
function polls(...parsed: number[]) {
  for (const n of parsed) {
    getCompany.mockResolvedValueOnce(
      okResult(companyItem({ filings_parsed: n, filings_total: 70 })) as never,
    );
  }
  const last = parsed.at(-1) ?? 0;
  getCompany.mockResolvedValue(
    okResult(companyItem({ filings_parsed: last, filings_total: 70 })) as never,
  );
}

afterEach(() => vi.clearAllMocks());

describe("FilingsStatus", () => {
  it("shows how many filings are read", () => {
    renderStatus();
    expect(screen.getByText("Filings read: 4 of 70")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read all filings" })).toBeEnabled();
  });

  it("starts the backfill, is disabled while it runs and follows the count until it stops", async () => {
    backfill.mockResolvedValue(okResult({ ticker: "AAPL" }, 202) as never);
    polls(10, 30, 30, 30);
    const { invalidate } = renderStatus();

    await userEvent.click(screen.getByRole("button", { name: "Read all filings" }));

    expect(backfill).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(screen.getByRole("button", { name: "Reading filings…" })).toBeDisabled();
    expect(await screen.findByText("Filings read: 30 of 70")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Read all filings" })).toBeEnabled(),
    );
    const calls = getCompany.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 5));
    expect(getCompany.mock.calls.length).toBe(calls); // the poll stopped
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["companies", "AAPL"] });
  });

  it("keeps following when one slow filing holds the count for a poll", async () => {
    backfill.mockResolvedValue(okResult({ ticker: "AAPL" }, 202) as never);
    polls(10, 10, 20, 20, 20);
    renderStatus();

    await userEvent.click(screen.getByRole("button", { name: "Read all filings" }));

    // the held count (10, 10) does not end the follow: all five polls run
    await waitFor(() => expect(getCompany.mock.calls.length).toBeGreaterThanOrEqual(5));
    expect(screen.getByText("Filings read: 20 of 70")).toBeInTheDocument();
  });

  it("stops as soon as every filing is read", async () => {
    backfill.mockResolvedValue(okResult({ ticker: "AAPL" }, 202) as never);
    polls(70);
    renderStatus();

    await userEvent.click(screen.getByRole("button", { name: "Read all filings" }));

    expect(await screen.findByText("Filings read: 70 of 70")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Read all filings" })).toBeEnabled(),
    );
    const calls = getCompany.mock.calls.length; // the first poll, then the views' refresh
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 5));
    expect(getCompany.mock.calls.length).toBe(calls);
  });

  it("follows a backfill that is already running (409) without an error", async () => {
    backfill.mockResolvedValue(
      errorResult(409, { detail: "A backfill is running for AAPL" }) as never,
    );
    polls(12, 12, 12);
    renderStatus();

    await userEvent.click(screen.getByRole("button", { name: "Read all filings" }));

    expect(await screen.findByText("Filings read: 12 of 70")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Read all filings" })).toBeEnabled(),
    );
  });

  it("shows the API's reason when the backfill cannot start", async () => {
    backfill.mockResolvedValue(errorResult(503, { detail: "SEC is not configured" }) as never);
    renderStatus();

    await userEvent.click(screen.getByRole("button", { name: "Read all filings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("SEC is not configured");
    expect(screen.getByRole("button", { name: "Read all filings" })).toBeEnabled();
    expect(getCompany).not.toHaveBeenCalled();
  });

  it("shows nothing for a manual company, which has no filings", () => {
    renderStatus(companyItem({ source: "manual", cik: null }));
    expect(screen.queryByText(/Filings read/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers no backfill while the company has no filing listed", () => {
    renderStatus(companyItem({ filings_parsed: 0, filings_total: 0 }));
    expect(screen.getByText("Filings read: 0 of 0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read all filings" })).toBeDisabled();
  });
});
