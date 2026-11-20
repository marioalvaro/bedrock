// The Review tab (M7c, FR-ACC-06): the newest report against the snapshot taken before it.
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCompanyApiV1CompaniesTickerGet,
  getEarningsReviewApiV1CompaniesTickerEarningsReviewGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { checkpointOut } from "@/test/checkpoints";
import { companyItem } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";
import {
  earningsReview,
  emptyReview,
  flagChange,
  restatedRow,
  reviewDriver,
  reviewLine,
} from "@/test/review";

import { ReviewView } from "./ReviewView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompanyApiV1CompaniesTickerGet: vi.fn(),
  getEarningsReviewApiV1CompaniesTickerEarningsReviewGet: vi.fn(),
}));

const getReview = vi.mocked(getEarningsReviewApiV1CompaniesTickerEarningsReviewGet);

beforeEach(() => {
  vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
    okResult(companyItem({ classification_mode: "off" })) as never,
  );
});
afterEach(() => vi.clearAllMocks());

function renderReview(review = earningsReview()) {
  getReview.mockResolvedValue(okResult(review) as never);
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReviewView ticker="AAPL" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const cells = (row: HTMLElement) =>
  within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
const bodyRows = (name: string) =>
  within(screen.getByRole("table", { name })).getAllByRole("row").slice(1);

describe("the heading", () => {
  it("names the report and the snapshot it is read against", async () => {
    renderReview();
    expect(await screen.findByText("FY26 · 10-K filed Oct 31, 2026")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /^Against the snapshot of .* \(Main\)$/ });
    expect(link).toHaveAttribute("href", "/c/AAPL/backtest?view=snapshots");
  });

  it("says when no snapshot was taken before the filing", async () => {
    renderReview(earningsReview({ snapshot: null }));
    expect(
      await screen.findByText("No snapshot was taken before this filing."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Against the snapshot/ })).not.toBeInTheDocument();
  });

  it("says nothing of the classification when the mode is unchanged", async () => {
    renderReview();
    await screen.findByText("FY26 · 10-K filed Oct 31, 2026");
    expect(screen.queryByText(/Line classification/)).not.toBeInTheDocument();
  });

  it("names the snapshot's classification mode when it differs from the company's", async () => {
    const review = earningsReview();
    renderReview({ ...review, snapshot: { ...review.snapshot!, classification_mode: "all" } });
    expect(
      await screen.findByText("Line classification: All · differs from the current setting"),
    ).toBeInTheDocument();
  });
});

describe("Key lines", () => {
  it("shows the actual, the snapshot's forecast, the consensus and the guidance", async () => {
    renderReview();
    const [row] = await screen.findAllByRole("row", { name: /^Revenue/ });
    expect(cells(row!)).toEqual([
      "Revenue",
      "416.2B",
      "+6.4%",
      "425.0B",
      "+2.1%",
      "400.0B–440.0B",
      "415.0B–418.0BIn range",
      "410.0B–420.0BBeat",
    ]);
    const guidance = within(row!).getByText("Beat");
    expect(guidance).toHaveClass("text-positive");
  });

  it("shows a dash where a column has no data", async () => {
    renderReview(
      earningsReview({
        lines: [
          reviewLine({
            forecast: null,
            pct_error: null,
            low: null,
            high: null,
            in_range: null,
            consensus: null,
            guidance: null,
            yoy: null,
          }),
        ],
      }),
    );
    const [row] = await screen.findAllByRole("row", { name: /^Revenue/ });
    expect(cells(row!)).toEqual(["Revenue", "416.2B", "—", "—", "—", "—", "—", "—"]);
  });

  it("colors an error only when the actual fell outside the Bear–Bull range", async () => {
    renderReview(
      earningsReview({
        lines: [
          reviewLine(),
          reviewLine({
            code: "net_income",
            label: "Net income",
            in_range: false,
            pct_error: "0.2",
          }),
        ],
      }),
    );
    const inside = await screen.findByText("+2.1%");
    expect(inside).not.toHaveClass("text-negative");
    expect(screen.getByText("+20.0%")).toHaveClass("text-negative");
  });
});

describe("Drivers that missed most", () => {
  it("lists the drivers with their source", async () => {
    renderReview();
    await screen.findByRole("table", { name: "Drivers that missed most" });
    const [row] = bodyRows("Drivers that missed most");
    expect(cells(row!)).toEqual(["Gross margin", "46.0%", "46.9%", "-1.9%", "manual"]);
  });

  it("shows the note when drivers are not scored", async () => {
    renderReview(
      earningsReview({ drivers: [], drivers_note: "Drivers are scored on a 10-K only." }),
    );
    expect(await screen.findByText("Drivers are scored on a 10-K only.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Drivers that missed most" })).toBeNull();
  });

  it("shows a dash for a driver with no source", async () => {
    renderReview(earningsReview({ drivers: [reviewDriver({ source: null })] }));
    await screen.findByRole("table", { name: "Drivers that missed most" });
    const [row] = bodyRows("Drivers that missed most");
    expect(cells(row!).at(-1)).toBe("—");
  });
});

describe("Restated", () => {
  it("lists the prior values the filing restated", async () => {
    renderReview();
    await screen.findByRole("table", { name: "Restated" });
    const [row] = bodyRows("Restated");
    expect(cells(row!)).toEqual(["Revenue", "FY2025", "391.0B", "391.5B", "+0.1%"]);
    expect(screen.queryByText(/^Showing/)).not.toBeInTheDocument();
  });

  it("says how many are shown when the list is capped", async () => {
    renderReview(earningsReview({ restated: [restatedRow()], restated_total: 120 }));
    expect(await screen.findByText("Showing 1 of 120")).toBeInTheDocument();
  });

  it("says when nothing was restated", async () => {
    renderReview(earningsReview({ restated: [], restated_total: 0 }));
    expect(await screen.findByText("Nothing was restated.")).toBeInTheDocument();
  });
});

describe("Quality flags", () => {
  it("shows each flag that changed, with its values", async () => {
    renderReview();
    await screen.findByRole("table", { name: "Quality flags" });
    const [row] = bodyRows("Quality flags");
    expect(cells(row!)).toEqual(["Accruals ratio", "None → Warn", "4.0% → 8.1%"]);
  });

  it("shows a dash for a side with no value", async () => {
    renderReview(
      earningsReview({
        flags: [flagChange({ unit: "x", before: null, value_before: null, value_after: "2.5" })],
      }),
    );
    await screen.findByRole("table", { name: "Quality flags" });
    const [row] = bodyRows("Quality flags");
    expect(cells(row!)).toEqual(["Accruals ratio", "— → Warn", "— → 2.5x"]);
  });

  it("says when no flag changed", async () => {
    renderReview(earningsReview({ flags: [] }));
    expect(await screen.findByText("No flag changed.")).toBeInTheDocument();
  });
});

describe("Thesis", () => {
  it("lists the checkpoints the report changed, with a link to the Notes tab", async () => {
    renderReview();
    await screen.findByRole("table", { name: "Thesis" });
    const [row] = bodyRows("Thesis");
    expect(cells(row!)).toEqual(["Gross margin holds", "Holding → Broken"]);
    expect(screen.getByRole("link", { name: "Notes" })).toHaveAttribute("href", "/c/AAPL/notes");
  });

  it("calls a checkpoint with nothing to read before the report new", async () => {
    renderReview(
      earningsReview({
        checkpoints: [checkpointOut({ changed: true, previous_state: "unknown" })],
      }),
    );
    await screen.findByRole("table", { name: "Thesis" });
    expect(cells(bodyRows("Thesis")[0]!)).toEqual(["Gross margin holds", "New → Holding"]);
  });

  it("says when no checkpoint changed", async () => {
    renderReview(earningsReview({ checkpoints: [] }));
    expect(await screen.findByText(/No checkpoint changed\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Notes" })).toBeInTheDocument();
  });
});

describe("states", () => {
  it("says when no 10-K or 10-Q is loaded", async () => {
    renderReview(emptyReview());
    expect(await screen.findByText("No 10-K or 10-Q is loaded yet.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says when the review cannot be loaded", async () => {
    getReview.mockResolvedValue(errorResult(500) as never);
    const queryClient = createQueryClient();
    queryClient.setDefaultOptions({ queries: { retry: false } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ReviewView ticker="AAPL" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Could not load the review.")).toBeInTheDocument();
  });

  it("shows a loading line first", () => {
    getReview.mockReturnValue(new Promise(() => {}) as never);
    const queryClient = createQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ReviewView ticker="AAPL" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
