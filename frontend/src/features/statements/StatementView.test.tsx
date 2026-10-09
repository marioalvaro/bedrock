import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCellApiV1CompaniesTickerStatementsCellGet,
  getStatementApiV1CompaniesTickerStatementsGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { errorResult, okResult } from "@/test/responses";
import { balanceStatement, incomeStatement } from "@/test/statements";

import { StatementView } from "./StatementView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  getCellApiV1CompaniesTickerStatementsCellGet: vi.fn(),
}));

function renderView(type: "IS" | "BS" | "CF" = "IS") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <StatementView ticker="AAPL" cik="0000320193" type={type} />
    </QueryClientProvider>,
  );
}

const cellDetail = {
  code: "revenue",
  label: "Revenue",
  fiscal_year: 2024,
  fiscal_period: "FY",
  value: "391035000000",
  provenance: "reported",
  source: {
    taxonomy: "us-gaap",
    concept: "RevenueFromContractWithCustomerExcludingAssessedTax",
    unit: "USD",
  },
  filing: { accession_no: "0000320193-24-000123", form: "10-K", filed_at: "2024-11-01" },
  derivation: null,
  vintages: [
    {
      value: "391035000000",
      accession_no: "0000320193-24-000123",
      form: "10-K",
      filed_at: "2024-11-01",
    },
    {
      value: "391000000000",
      accession_no: "0000320193-24-000050",
      form: "10-Q",
      filed_at: "2024-08-02",
    },
  ],
  adjustments: [],
};

beforeEach(() => {
  setScale("M");
  vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
    okResult(incomeStatement()) as never,
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("StatementView", () => {
  it("renders labels and formatted values from the payload", async () => {
    renderView();

    expect(await screen.findByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Cost of revenue")).toBeInTheDocument();
    expect(screen.getByText("391,035")).toBeInTheDocument();
    expect(screen.getByText("383,285")).toBeInTheDocument();
    expect(screen.getByText("6.08")).toBeInTheDocument();
    expect(screen.getByText("FY2024")).toBeInTheDocument();
    expect(screen.getByText("USD millions")).toBeInTheDocument();
  });

  it("requests the statement type and frequency", async () => {
    renderView("CF");
    await screen.findByText("Revenue");

    expect(getStatementApiV1CompaniesTickerStatementsGet).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { type: "CF", freq: "annual" },
    });
  });

  it("refetches when the frequency changes", async () => {
    renderView();
    await screen.findByText("Revenue");

    await userEvent.click(screen.getByRole("radio", { name: "Quarterly" }));

    expect(getStatementApiV1CompaniesTickerStatementsGet).toHaveBeenLastCalledWith({
      path: { ticker: "AAPL" },
      query: { type: "IS", freq: "quarterly" },
    });
  });

  it("disables TTM on the balance sheet but not on the income statement", async () => {
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(balanceStatement()) as never,
    );
    renderView("BS");
    expect(await screen.findByText("Total assets")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "TTM" })).toBeDisabled();
  });

  it("enables TTM on the income statement", async () => {
    renderView();
    await screen.findByText("Revenue");

    expect(screen.getByRole("radio", { name: "TTM" })).toBeEnabled();
  });

  it("shows the balance check row: a tick when it balances, the difference when it does not", async () => {
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(balanceStatement()) as never,
    );
    renderView("BS");

    const label = await screen.findByText("Balance check");
    const row = label.closest("[role=row]") as HTMLElement;
    expect(within(row).getByText("✓")).toBeInTheDocument();
    expect(within(row).getByText("(2)")).toBeInTheDocument();
  });

  it("adds YoY rows when toggled", async () => {
    renderView();
    await screen.findByText("Revenue");
    expect(screen.queryByText("2.0%")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "YoY" }));

    expect(screen.getByText("2.0%")).toBeInTheDocument();
    expect(screen.getAllByRole("gridcell", { name: "YoY" }).length).toBeGreaterThan(0);
  });

  it("adds common-size rows when toggled", async () => {
    renderView();
    await screen.findByText("Revenue");

    await userEvent.click(screen.getByRole("button", { name: "Common size" }));

    expect(screen.getByText("53.8%")).toBeInTheDocument();
  });

  it("rescales the values when the scale changes", async () => {
    renderView();
    await screen.findByText("391,035");

    await userEvent.click(screen.getByRole("radio", { name: "B" }));

    expect(screen.getByText("391.0")).toBeInTheDocument();
    expect(screen.getByText("USD billions")).toBeInTheDocument();
  });

  it("marks derived cells apart from reported ones and shows the legend", async () => {
    renderView();
    const derived = await screen.findByText("391,035");
    const reported = screen.getByText("383,285");

    expect(derived.closest("[col-id]")).toHaveClass("prov-derived");
    expect(reported.closest("[col-id]")).not.toHaveClass("prov-derived");
    expect(screen.getByText(/Derived/)).toBeInTheDocument();
  });

  it("hides line items with no values", async () => {
    renderView();
    await screen.findByText("Revenue");

    expect(screen.queryByText("Research and development")).not.toBeInTheDocument();
  });

  it("opens the cell details with the source, filing and vintages on a click", async () => {
    vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet).mockResolvedValue(
      okResult(cellDetail) as never,
    );
    renderView();

    await userEvent.click(await screen.findByText("391,035"));

    const sheet = await screen.findByRole("dialog");
    expect(getCellApiV1CompaniesTickerStatementsCellGet).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { code: "revenue", fiscal_year: 2024, fiscal_period: "FY" },
    });
    expect(
      await within(sheet).findByText("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"),
    ).toBeInTheDocument();
    const link = within(sheet).getByRole("link", { name: /0000320193-24-000123/ });
    expect(link).toHaveAttribute(
      "href",
      "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/",
    );
    expect(within(sheet).getByText("10-Q")).toBeInTheDocument();
    expect(within(sheet).getByText(/Adjustments: none/)).toBeInTheDocument();
  });

  it("shows the derivation of a derived cell and says it has no vintages", async () => {
    vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet).mockResolvedValue(
      okResult({
        ...cellDetail,
        provenance: "derived",
        source: null,
        filing: null,
        derivation: {
          formula: "FY - YTD Q3",
          inputs: [
            { code: "revenue", fiscal_period: "FY", value: "391035000000" },
            { code: "revenue", fiscal_period: "Q3", value: "294866000000" },
          ],
        },
        vintages: [],
      }) as never,
    );
    renderView();

    await userEvent.click(await screen.findByText("391,035"));

    const sheet = await screen.findByRole("dialog");
    expect(await within(sheet).findByText("FY - YTD Q3")).toBeInTheDocument();
    expect(within(sheet).getByText(/revenue Q3/)).toHaveTextContent("294,866");
    expect(within(sheet).queryByRole("table")).not.toBeInTheDocument();
    expect(
      within(sheet).getByText("No filed vintages: computed from other cells."),
    ).toBeInTheDocument();
  });

  it("does not open details for a sub-row cell", async () => {
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "YoY" }));

    await userEvent.click(screen.getByText("2.0%"));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(getCellApiV1CompaniesTickerStatementsCellGet).not.toHaveBeenCalled();
  });

  it("shows an error state when the API fails", async () => {
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      errorResult(500) as never,
    );
    renderView();

    expect(await screen.findByText("Could not load the statement.")).toBeInTheDocument();
  });

  it("shows the error state for a 200 whose body is not a statement (G2/G4)", async () => {
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult("<!doctype html><html></html>") as never,
    );
    renderView();

    expect(await screen.findByText("Could not load the statement.")).toBeInTheDocument();
    expect(screen.queryByText("Revenue")).not.toBeInTheDocument();
  });

  describe("CSV export", () => {
    function captureDownload() {
      const blobs: Blob[] = [];
      const names: string[] = [];
      URL.createObjectURL = vi.fn((blob: Blob | MediaSource) => {
        blobs.push(blob as Blob);
        return "blob:csv";
      });
      URL.revokeObjectURL = vi.fn();
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
        this: HTMLAnchorElement,
      ) {
        names.push(this.download);
      });
      return { blobs, names };
    }

    function readText(blob: Blob): Promise<string> {
      return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsText(blob);
      });
    }

    it("exports the visible rows in the current scale with plain minus signs", async () => {
      const download = captureDownload();
      renderView();
      await screen.findByText("Revenue");
      await userEvent.click(screen.getByRole("button", { name: "YoY" }));

      await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));

      expect(download.names).toEqual(["AAPL_IS_annual.csv"]);
      const lines = (await readText(download.blobs[0]!)).trim().split(/\r?\n/);
      expect(lines[0]).toBe('"USD millions","FY2023","FY2024"');
      expect(lines).toContain('"Revenue","383285","391035"');
      expect(lines).toContain('"Revenue YoY","","2.0%"');
      expect(lines).toContain('"Cost of revenue YoY","","-1.8%"');
      expect(lines.some((line) => line.includes("Research"))).toBe(false);
    });
  });
});
