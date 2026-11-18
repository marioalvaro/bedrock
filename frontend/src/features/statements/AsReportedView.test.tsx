import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAsReportedApiV1CompaniesTickerAsReportedGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { asReportedBalanceSheet } from "@/test/classification";
import { errorResult, okResult } from "@/test/responses";

import { AsReportedView } from "./AsReportedView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getAsReportedApiV1CompaniesTickerAsReportedGet: vi.fn(),
}));

const getAsReported = vi.mocked(getAsReportedApiV1CompaniesTickerAsReportedGet);

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <AsReportedView ticker="AAPL" type="BS" />
    </QueryClientProvider>,
  );
}

const cell = (row: string, col: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${col}"]`) as HTMLElement;

beforeEach(() => {
  getAsReported.mockResolvedValue(okResult(asReportedBalanceSheet()) as never);
  setScale("M");
});

afterEach(() => vi.clearAllMocks());

describe("AsReportedView", () => {
  it("says it is read only, above the table", async () => {
    renderView();
    expect(
      await screen.findByText(
        "Read only. The filing as filed; Bedrock's own statements are under Bedrock rows.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the filing's own labels, period headers and the Bedrock row", async () => {
    renderView();
    await screen.findByText("Vendor non-trade receivables");
    expect(cell("5", "label")).toHaveTextContent("Total current assets");
    expect(screen.getByText("2025-09-27")).toBeInTheDocument();
    expect(screen.getByText("2024-09-28")).toBeInTheDocument();
    expect(screen.getByText("Bedrock row")).toBeInTheDocument();
    expect(cell("3", "bedrock")).toHaveTextContent("Not classified");
    expect(cell("4", "bedrock")).toHaveTextContent("Other: Receivables");
    expect(cell("1", "p0")).toHaveTextContent("29,943");
  });

  it("indents a line by its depth and sets a total in medium weight", async () => {
    renderView();
    await screen.findByText("Vendor non-trade receivables");
    const cash = cell("1", "label").querySelector("[title]") as HTMLElement;
    expect(cash.style.paddingLeft).toBe("12px");
    const total = cell("5", "label").querySelector("[title]") as HTMLElement;
    expect(total.style.paddingLeft).toBe("0px");
    expect(total).toHaveClass("font-medium");
    expect(cash).not.toHaveClass("font-medium");
  });

  it("marks a total that does not foot, in that period only", async () => {
    renderView();
    await screen.findByText("Vendor non-trade receivables");
    const bad = cell("5", "p0").querySelector(".not-foot-mark");
    expect(bad).not.toBeNull();
    expect(cell("5", "p0").querySelector("[title]")).toHaveAttribute(
      "title",
      "Does not equal the sum of its lines in this filing",
    );
    expect(cell("5", "p1").querySelector(".not-foot-mark")).toBeNull();
  });

  it("asks for the default filing, then for the one picked in the selector", async () => {
    renderView();
    const select = (await screen.findByLabelText("Filing")) as HTMLSelectElement;
    expect(getAsReported).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { statement: "BS" },
    });
    expect(select.value).toBe("0000320193-25-000079");
    const options = Array.from(select.options).map((o) => o.textContent);
    expect(options).toEqual([
      "10-Q · period ended 2025-12-27 · filed 2026-01-30",
      "10-K · period ended 2025-09-27 · filed 2025-10-31",
    ]);

    await userEvent.selectOptions(select, "0000320193-26-000020");

    await waitFor(() =>
      expect(getAsReported).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { statement: "BS", accession: "0000320193-26-000020" },
      }),
    );
  });

  it("keeps the shown filing on screen while the picked one loads", async () => {
    renderView();
    const select = await screen.findByLabelText("Filing");
    await screen.findByText("Vendor non-trade receivables");
    getAsReported.mockReturnValue(new Promise(() => {}) as never);

    await userEvent.selectOptions(select, "0000320193-26-000020");

    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Filing")).toBeInTheDocument();
    expect(screen.getByText("Vendor non-trade receivables")).toBeInTheDocument();
  });

  it("says so when the company has no parsed filing for the statement", async () => {
    getAsReported.mockResolvedValue(
      okResult(
        asReportedBalanceSheet({ filing: null, filings: [], periods: [], foots: null, lines: [] }),
      ) as never,
    );
    renderView();
    expect(
      await screen.findByText("No filing has been read for this statement yet."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Filing")).not.toBeInTheDocument();
  });

  it("shows loading, then an error", async () => {
    getAsReported.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the filing.")).toBeInTheDocument();
  });
});
