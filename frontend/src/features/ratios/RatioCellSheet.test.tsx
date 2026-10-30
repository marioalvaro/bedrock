import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getRatioCellApiV1CompaniesTickerRatiosCellGet,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { ratioCell, term } from "@/test/analysis";
import { errorResult, okResult } from "@/test/responses";

import { RatioCellSheet, type RatioCellTarget } from "./RatioCellSheet";

vi.mock("@/api/generated/sdk.gen", () => ({
  getRatioCellApiV1CompaniesTickerRatiosCellGet: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
}));
const fetchCell = vi.mocked(getRatioCellApiV1CompaniesTickerRatiosCellGet);

const FY2024: RatioCellTarget = {
  code: "pe",
  label: "P/E",
  periodLabel: "FY2024",
  fiscalYear: 2024,
  fiscalPeriod: "FY",
  ttm: false,
};

function renderSheet(
  target: RatioCellTarget | null = FY2024,
  basis: "reported" | "normalized" = "reported",
) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <RatioCellSheet ticker="DE" freq="annual" basis={basis} target={target} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  fetchCell.mockResolvedValue(okResult(ratioCell()) as never);
  vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet).mockResolvedValue(okResult([]) as never);
  vi.mocked(listNotesApiV1CompaniesTickerNotesGet).mockResolvedValue(okResult([]) as never);
});
afterEach(() => vi.clearAllMocks());

describe("RatioCellSheet", () => {
  it("asks for the cell of the ratio, period, frequency and basis", async () => {
    renderSheet(FY2024, "normalized");
    await screen.findByText("market_cap ÷ net_income_common");

    expect(fetchCell).toHaveBeenCalledWith({
      path: { ticker: "DE" },
      query: {
        freq: "annual",
        basis: "normalized",
        code: "pe",
        fiscal_year: 2024,
        fiscal_period: "FY",
      },
    });
  });

  it("asks for nothing while closed", () => {
    renderSheet(null);

    expect(fetchCell).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the ratio, the period, its value and its definition", async () => {
    renderSheet();
    const sheet = await screen.findByRole("dialog");

    expect(within(sheet).getByText("P/E")).toBeVisible();
    expect(within(sheet).getByText(/DE · FY2024/)).toBeVisible();
    expect(await within(sheet).findByText("30.0x")).toBeVisible();
    expect(within(sheet).getByText("market_cap ÷ net_income_common")).toBeVisible();
  });

  it("lists the numerator and the denominator with their inputs and values", async () => {
    renderSheet();
    const sheet = await screen.findByRole("dialog");

    const numerator = await within(sheet).findByRole("region", { name: "Numerator" });
    expect(within(numerator).getByText("Market cap")).toBeVisible();
    expect(within(numerator).getAllByText("600.0M").length).toBeGreaterThan(0);
    const denominator = within(sheet).getByRole("region", { name: "Denominator" });
    expect(within(denominator).getByText("Net income to common")).toBeVisible();
    expect(within(denominator).getByText("20.0M")).toBeVisible();
  });

  it("expands a metric into its own inputs and shows a price's note", async () => {
    renderSheet();
    const numerator = await screen.findByRole("region", { name: "Numerator" });

    expect(within(numerator).getByText("price × shares_outstanding")).toBeVisible();
    expect(within(numerator).getByText("Share price")).toBeVisible();
    expect(within(numerator).getByText("60.00")).toBeVisible();
    expect(within(numerator).getByText("Shares outstanding")).toBeVisible();
    expect(within(numerator).getByText("10.0M")).toBeVisible();
    expect(within(numerator).getByText(/close of 2024-09-27, the last on or before/)).toBeVisible();
  });

  it("shows both years of an average", async () => {
    fetchCell.mockResolvedValue(
      okResult(
        ratioCell({
          code: "roe",
          label: "Return on equity",
          unit: "pct",
          value: "0.4",
          definition: "net_income_common ÷ avg(equity_parent)",
          denominator: {
            text: "equity_parent",
            average: true,
            value: "50000000",
            terms: [term({ code: "equity_parent", label: "Parent equity", value: "60000000" })],
            prior_terms: [
              term({ code: "equity_parent", label: "Parent equity", value: "40000000" }),
            ],
          },
        }),
      ) as never,
    );
    renderSheet();
    const denominator = await screen.findByRole("region", { name: "Denominator" });

    expect(within(denominator).getByText(/Average of FY2024 and FY2023/)).toBeVisible();
    expect(within(denominator).getByText("FY2024")).toBeVisible();
    expect(within(denominator).getByText("60.0M")).toBeVisible();
    expect(within(denominator).getByText("FY2023")).toBeVisible();
    expect(within(denominator).getByText("40.0M")).toBeVisible();
    expect(within(denominator).getByText("50.0M")).toBeVisible();
  });

  it("shows a subtracted member with its sign", async () => {
    fetchCell.mockResolvedValue(
      okResult(
        ratioCell({
          denominator: {
            text: "total_debt - cash",
            average: false,
            value: "30000000",
            terms: [
              term({ code: "total_debt", label: "Total debt", value: "40000000" }),
              term({ code: "cash", label: "Cash", value: "10000000", sign: -1 }),
            ],
            prior_terms: [],
          },
        }),
      ) as never,
    );
    renderSheet();
    const denominator = await screen.findByRole("region", { name: "Denominator" });

    expect(within(denominator).getByText("− Cash")).toBeVisible();
    expect(within(denominator).getByText("Total debt")).toBeVisible();
  });

  it("shows the scale when the ratio multiplies by one", async () => {
    fetchCell.mockResolvedValue(okResult(ratioCell({ scale: "365" })) as never);
    renderSheet();

    expect(await screen.findByText("× 365")).toBeVisible();
  });

  it("shows a ratio with no denominator as its numerator alone", async () => {
    fetchCell.mockResolvedValue(okResult(ratioCell({ denominator: null })) as never);
    renderSheet();
    await screen.findByRole("region", { name: "Numerator" });

    expect(screen.queryByRole("region", { name: "Denominator" })).not.toBeInTheDocument();
  });

  it("says why a value is empty", async () => {
    fetchCell.mockResolvedValue(
      okResult(ratioCell({ value: null, reason: "denominator ≤ 0" })) as never,
    );
    renderSheet();

    expect(await screen.findByText("No value: denominator ≤ 0")).toBeVisible();
  });

  it("shows the caveat of the company", async () => {
    fetchCell.mockResolvedValue(
      okResult(
        ratioCell({ caveat: "Consolidated figures include John Deere Financial." }),
      ) as never,
    );
    renderSheet();

    expect(await screen.findByText(/include John Deere Financial/)).toBeVisible();
  });

  it("shows a loading line and an error line", async () => {
    fetchCell.mockReturnValue(new Promise(() => {}) as never);
    renderSheet();
    expect(await screen.findByText("Loading…")).toBeVisible();
  });

  it("shows an error line when the cell cannot load", async () => {
    fetchCell.mockResolvedValue(errorResult(404, { detail: "No such ratio cell" }) as never);
    renderSheet();

    expect(await screen.findByText("Could not load the ratio details.")).toBeVisible();
  });

  it("carries the notes of the cell, except on a TTM column", async () => {
    renderSheet();
    const sheet = await screen.findByRole("dialog");
    await userEvent.click(await within(sheet).findByRole("button", { name: "Add note" }));
    expect(within(sheet).getByText("Linked to P/E · FY2024")).toBeVisible();
  });

  it("has no notes on a TTM column", async () => {
    renderSheet({ ...FY2024, periodLabel: "TTM Q3 FY24", fiscalPeriod: "Q3", ttm: true });
    const sheet = await screen.findByRole("dialog");
    await within(sheet).findByRole("region", { name: "Numerator" });

    expect(within(sheet).queryByRole("button", { name: "Add note" })).not.toBeInTheDocument();
  });

  it("closes", async () => {
    const onClose = renderSheet();
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });
});
