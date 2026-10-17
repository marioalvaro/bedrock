import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getFlagsApiV1CompaniesTickerFlagsGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { flags } from "@/test/analysis";
import { errorResult, okResult } from "@/test/responses";

import { QualityView } from "./QualityView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getFlagsApiV1CompaniesTickerFlagsGet: vi.fn(),
}));

vi.mock("./OffBalanceItems", () => ({
  OffBalanceItems: ({ ticker }: { ticker: string }) => (
    <section data-testid="off-balance" data-ticker={ticker} />
  ),
}));

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <QualityView ticker="AAPL" />
    </QueryClientProvider>,
  );
}

const cell = (row: string, period: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${period}"]`) as HTMLElement;

beforeEach(() => {
  setScale("M");
  vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(okResult(flags()) as never);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("QualityView", () => {
  it("colors period cells by severity and shows formatted values", async () => {
    renderView();
    await waitFor(() => expect(cell("accruals_ratio", "FY2023")).not.toBeNull());

    expect(cell("accruals_ratio", "FY2023")).toHaveTextContent("6.2%");
    expect(cell("accruals_ratio", "FY2023")).toHaveClass("flag-warn");
    expect(cell("accruals_ratio", "FY2024")).toHaveTextContent("15.0%");
    expect(cell("accruals_ratio", "FY2024")).toHaveClass("flag-alert");
    expect(cell("cfo_to_net_income", "FY2023")).toHaveTextContent("1.2x");
    expect(cell("cfo_to_net_income", "FY2023")).not.toHaveClass("flag-warn");
    expect(cell("cfo_to_net_income", "FY2023")).not.toHaveClass("flag-alert");
    expect(cell("cfo_to_net_income", "FY2024")).toHaveTextContent("—");
    expect(cell("cfo_to_net_income", "FY2024")).not.toHaveClass("flag-warn");
    expect(cell("cfo_to_net_income", "FY2024")).not.toHaveClass("flag-alert");
    expect(cell("goodwill_impairment", "FY2024")).not.toHaveClass("flag-warn");
    expect(cell("goodwill_impairment", "FY2024")).not.toHaveClass("flag-alert");
  });

  it("shows the label, the rule text and the thresholds", async () => {
    renderView();
    expect(await screen.findByText("Accruals ratio")).toHaveAttribute("title", "accruals_ratio");
    const rule = screen.getByText("cfo ÷ net_income; null when net_income ≤ 0");
    expect(rule).toHaveAttribute("title", "cfo ÷ net_income; null when net_income ≤ 0");
    expect(screen.getByText("warn > 5% · alert > 10%")).toBeInTheDocument();
    expect(screen.getByText("warn < 0.8x · alert < 0x")).toBeInTheDocument();
    expect(screen.getByText("warn > 0%")).toBeInTheDocument();
  });

  it("shows a dash when both thresholds are null", async () => {
    const payload = flags();
    payload.rules = [{ ...payload.rules[0]!, warn: null, alert: null }];
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(okResult(payload) as never);
    renderView();
    await waitFor(() => expect(cell("accruals_ratio", "FY2023")).not.toBeNull());
    expect(
      document.querySelector('[row-id="accruals_ratio"] [col-id="thresholds"]'),
    ).toHaveTextContent("—");
  });

  it("requests annual, then TTM after toggling; the active item cannot deselect", async () => {
    const user = userEvent.setup();
    renderView();
    await screen.findByText("Accruals ratio");
    expect(getFlagsApiV1CompaniesTickerFlagsGet).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: { freq: "annual" } }),
    );

    await user.click(screen.getByRole("radio", { name: "Annual" }));
    expect(screen.getByRole("radio", { name: "Annual" })).toBeChecked();

    await user.click(screen.getByRole("radio", { name: "TTM" }));
    await waitFor(() =>
      expect(getFlagsApiV1CompaniesTickerFlagsGet).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: { freq: "ttm" } }),
      ),
    );
    await user.click(screen.getByRole("radio", { name: "TTM" }));
    expect(screen.getByRole("radio", { name: "TTM" })).toBeChecked();
  });

  it("renders OffBalanceItems for the ticker once the flags load", async () => {
    renderView();
    await screen.findByText("Accruals ratio");
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows a loading line while pending, with OffBalanceItems already present", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows an error line when the request fails and still renders OffBalanceItems", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText(/Could not load/)).toHaveClass("text-destructive");
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows the empty state and still renders OffBalanceItems", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(
      okResult(flags({ rules: [] })) as never,
    );
    renderView();
    expect(await screen.findByText("No quality flags for this company.")).toBeInTheDocument();
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows the empty state when there are no periods", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(
      okResult(flags({ periods: [] })) as never,
    );
    renderView();
    expect(await screen.findByText("No quality flags for this company.")).toBeInTheDocument();
  });
});
