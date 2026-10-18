import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getMultiplesApiV1CompaniesTickerMultiplesGet,
  getRatiosApiV1CompaniesTickerRatiosGet,
} from "@/api/generated/sdk.gen";
import { downloadText } from "@/lib/download";
import { createQueryClient } from "@/lib/query-client";
import { multiples, ratios } from "@/test/analysis";
import { errorResult, okResult } from "@/test/responses";

import { RatiosView } from "./RatiosView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getRatiosApiV1CompaniesTickerRatiosGet: vi.fn(),
  getMultiplesApiV1CompaniesTickerMultiplesGet: vi.fn(),
}));
vi.mock("@/lib/download", () => ({ downloadText: vi.fn() }));

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <RatiosView ticker="DE" />
    </QueryClientProvider>,
  );
}

const cell = (row: string, period: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${period}"]`) as HTMLElement;
const labelCell = (row: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="label"]`) as HTMLElement;
const lastQuery = () =>
  vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mock.calls.at(-1)![0]!.query;

beforeEach(() => {
  // no caveat: the "†" notes below the grid are the ratio table's own
  vi.mocked(getMultiplesApiV1CompaniesTickerMultiplesGet).mockResolvedValue(
    okResult(
      multiples({ rows: multiples().rows.map((row) => ({ ...row, caveat: null })) }),
    ) as never,
  );
  vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mockResolvedValue(okResult(ratios()) as never);
});
afterEach(() => {
  vi.clearAllMocks();
});

describe("RatiosView", () => {
  it("shows the valuation multiples above the grid, for the chosen basis", async () => {
    renderView();
    expect(await screen.findByRole("region", { name: "Valuation multiples" })).toBeInTheDocument();
    expect(getMultiplesApiV1CompaniesTickerMultiplesGet).toHaveBeenCalledWith({
      path: { ticker: "DE" },
      query: { basis: "reported" },
    });

    await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));
    await waitFor(() =>
      expect(getMultiplesApiV1CompaniesTickerMultiplesGet).toHaveBeenLastCalledWith({
        path: { ticker: "DE" },
        query: { basis: "normalized" },
      }),
    );
  });

  it("requests annual, reported ratios by default", async () => {
    renderView();
    await screen.findByText("Gross margin †");

    expect(getRatiosApiV1CompaniesTickerRatiosGet).toHaveBeenCalledWith({
      path: { ticker: "DE" },
      query: { freq: "annual", basis: "reported" },
    });
    expect(screen.getByRole("radio", { name: "Annual" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Reported" })).toBeChecked();
    expect(screen.getByText("Ratio")).toBeInTheDocument();
  });

  it("puts a heading row for each category, in order, before its ratios", async () => {
    renderView();
    await screen.findByText("Profitability");

    const ids = [...document.querySelectorAll(".ag-center-cols-container [row-id], [row-id]")]
      .map((el) => el.getAttribute("row-id"))
      .filter((id, i, all) => all.indexOf(id) === i);
    expect(ids).toEqual([
      "category:Profitability",
      "gross_margin",
      "roe",
      "category:Solvency",
      "debt_to_equity",
      "interest_coverage",
      "category:Efficiency",
      "dso",
      "category:Per share",
      "eps_diluted",
    ]);
    const heading = labelCell("category:Profitability");
    expect(heading.querySelector(".font-medium")).not.toBeNull();
    expect(cell("category:Profitability", "FY2024")).toHaveTextContent("");
  });

  it("marks only caveat rows with a dagger and carries the definition as a title", async () => {
    renderView();
    await screen.findByText("Profitability");

    expect(screen.getByText("Gross margin †")).toBeInTheDocument();
    expect(screen.getByText("Return on equity")).toBeInTheDocument();
    expect(screen.queryByText("Return on equity †")).not.toBeInTheDocument();
    expect(labelCell("roe").querySelector("[title]")).toHaveAttribute(
      "title",
      "net_income_common ÷ avg(equity_parent)",
    );
  });

  it("lists each distinct caveat once, with the rows that carry it", async () => {
    renderView();
    await screen.findByText("Profitability");

    const notes = screen.getAllByText(/^† /);
    expect(notes).toHaveLength(2);
    expect(notes[0]).toHaveTextContent(
      /^† Gross margin, Days sales outstanding: Deere's revenue is net sales/,
    );
    expect(notes[1]).toHaveTextContent(
      /^† Debt \/ equity, Interest coverage: Consolidated figures include John Deere Financial/,
    );
  });

  it("shows no note when no row has a caveat", async () => {
    const payload = ratios();
    payload.rows = payload.rows.map((r) => ({ ...r, caveat: null }));
    vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mockResolvedValue(okResult(payload) as never);
    renderView();
    await screen.findByText("Gross margin");

    expect(screen.queryByText(/^† /)).not.toBeInTheDocument();
  });

  it("formats each unit, negatives in parentheses and nulls as a dash", async () => {
    renderView();
    await screen.findByText("Profitability");

    expect(cell("gross_margin", "FY2024")).toHaveTextContent("46.2%");
    expect(cell("roe", "FY2023")).toHaveTextContent("(3.4%)");
    expect(cell("debt_to_equity", "FY2023")).toHaveTextContent("2.8x");
    expect(cell("interest_coverage", "FY2023")).toHaveTextContent("—");
    expect(cell("dso", "FY2023")).toHaveTextContent("61");
    expect(cell("eps_diluted", "FY2023")).toHaveTextContent("34.63");
    expect(cell("gross_margin", "FY2024")).toHaveClass("num", "ag-right-aligned-cell");
  });

  it("sends TTM and Normalized, and keeps the basis across a frequency change", async () => {
    renderView();
    await screen.findByText("Profitability");

    await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));
    await waitFor(() => expect(lastQuery()).toMatchObject({ freq: "annual", basis: "normalized" }));
    await userEvent.click(screen.getByRole("radio", { name: "TTM" }));

    await waitFor(() => expect(lastQuery()).toEqual({ freq: "ttm", basis: "normalized" }));
    expect(screen.getByRole("radio", { name: "Normalized" })).toBeChecked();
  });

  it("does not deselect an active toggle when it is clicked again", async () => {
    renderView();
    await screen.findByText("Profitability");

    await userEvent.click(screen.getByRole("radio", { name: "Annual" }));
    await userEvent.click(screen.getByRole("radio", { name: "Reported" }));

    expect(screen.getByRole("radio", { name: "Annual" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Reported" })).toBeChecked();
    expect(getRatiosApiV1CompaniesTickerRatiosGet).toHaveBeenCalledTimes(1);
  });

  it("shows a loading line while pending", async () => {
    vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mockReturnValue(
      new Promise(() => {}) as never,
    );
    renderView();
    expect(await screen.findByText("Loading…")).toBeInTheDocument();
  });

  it("shows an error line when the API fails", async () => {
    vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mockResolvedValue(errorResult(500) as never);
    renderView();

    const line = await screen.findByText("Could not load the ratios.");
    expect(line).toHaveClass("text-destructive");
  });

  it.each([
    ["no rows", { rows: [] }],
    ["no periods", { periods: [] }],
  ])("shows the empty state for %s", async (_name, override) => {
    vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mockResolvedValue(
      okResult(ratios(override)) as never,
    );
    renderView();

    expect(await screen.findByText("No ratios for this company.")).toBeInTheDocument();
  });

  it("exports the grid as CSV with plain labels and headings", async () => {
    renderView();
    await screen.findByText("Profitability");

    await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));

    expect(downloadText).toHaveBeenCalledTimes(1);
    const [name, csv, type] = vi.mocked(downloadText).mock.calls[0]!;
    expect(name).toBe("DE_ratios_annual.csv");
    expect(type).toBe("text/csv");
    const lines = csv.trim().split(/\r?\n/);
    expect(lines[0]).toBe('"Ratio","FY2023","FY2024"');
    expect(lines).toContain('"Profitability","",""');
    expect(lines).toContain('"Gross margin","44.1%","46.2%"');
    expect(lines).toContain('"Return on equity","-3.4%","164.6%"');
    expect(lines).toContain('"Interest coverage","",""');
    expect(lines.some((l) => l.includes("†"))).toBe(false);
  });

  it("names the CSV after the frequency", async () => {
    renderView();
    await screen.findByText("Profitability");
    await userEvent.click(screen.getByRole("radio", { name: "TTM" }));
    await waitFor(() => expect(lastQuery()).toMatchObject({ freq: "ttm" }));
    await screen.findByText("Profitability");

    await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));

    expect(vi.mocked(downloadText).mock.calls.at(-1)![0]).toBe("DE_ratios_ttm.csv");
  });
});
