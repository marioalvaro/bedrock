import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createNoteApiV1CompaniesTickerNotesPost,
  getCellApiV1CompaniesTickerStatementsCellGet,
  getStatementApiV1CompaniesTickerStatementsGet,
  listImportsApiV1CompaniesTickerImportsGet,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { note, noteLink, noteLinks } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import { balanceStatement, customIncomeStatement, incomeStatement } from "@/test/statements";

import { StatementView } from "./StatementView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  getCellApiV1CompaniesTickerStatementsCellGet: vi.fn(),
  createAdjustmentApiV1CompaniesTickerAdjustmentsPost: vi.fn(),
  updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut: vi.fn(),
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
  createNoteApiV1CompaniesTickerNotesPost: vi.fn(),
  listImportsApiV1CompaniesTickerImportsGet: vi.fn(),
  importStatementsApiV1CompaniesTickerImportsPost: vi.fn(),
  deleteImportApiV1CompaniesTickerImportsImportIdDelete: vi.fn(),
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

const cell = (row: string, period: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${period}"]`) as HTMLElement;

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
  normalized_value: null,
};

const emptyCellDetail = (code: string, label: string, fiscalYear: number) => ({
  ...cellDetail,
  code,
  label,
  fiscal_year: fiscalYear,
  value: null,
  provenance: null,
  source: null,
  filing: null,
  vintages: [],
});

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

beforeEach(() => {
  setScale("M");
  vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
    okResult(incomeStatement()) as never,
  );
  vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet).mockResolvedValue(okResult([]) as never);
  vi.mocked(listNotesApiV1CompaniesTickerNotesGet).mockResolvedValue(okResult([]) as never);
  vi.mocked(listImportsApiV1CompaniesTickerImportsGet).mockResolvedValue(okResult([]) as never);
  vi.mocked(createNoteApiV1CompaniesTickerNotesPost).mockResolvedValue(
    okResult(note({ id: 9 }), 201) as never,
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("StatementView", () => {
  it("renders labels and formatted values from the payload", async () => {
    renderView();

    expect(await screen.findByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Gross profit")).toBeInTheDocument();
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
      query: { type: "CF", freq: "annual", common_size_base: "total", basis: "reported" },
    });
  });

  it("refetches when the frequency changes", async () => {
    renderView();
    await screen.findByText("Revenue");

    await userEvent.click(screen.getByRole("radio", { name: "Quarterly" }));

    expect(getStatementApiV1CompaniesTickerStatementsGet).toHaveBeenLastCalledWith({
      path: { ticker: "AAPL" },
      query: { type: "IS", freq: "quarterly", common_size_base: "total", basis: "reported" },
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

    expect(screen.getByText("46.2%")).toBeInTheDocument();
    expect(screen.getAllByRole("gridcell", { name: "% of Revenue" }).length).toBeGreaterThan(0);
  });

  describe("breakdown", () => {
    it("opens collapsed: parent rows only, with a chevron on those that have a breakdown", async () => {
      renderView();
      await screen.findByText("Gross profit");

      expect(screen.queryByText("Cost of revenue")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Expand Gross profit" })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      expect(screen.queryByRole("button", { name: /Expand Revenue/ })).not.toBeInTheDocument();
    });

    it("shows and hides one row's breakdown with its chevron", async () => {
      renderView();
      await userEvent.click(await screen.findByRole("button", { name: "Expand Gross profit" }));

      expect(screen.getByText("Cost of revenue")).toBeInTheDocument();
      const collapse = screen.getByRole("button", { name: "Collapse Gross profit" });
      expect(collapse).toHaveAttribute("aria-expanded", "true");

      await userEvent.click(collapse);

      await waitFor(() => expect(screen.queryByText("Cost of revenue")).not.toBeInTheDocument());
    });

    it("expands and collapses every breakdown from the toolbar", async () => {
      renderView();
      await screen.findByText("Gross profit");

      await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
      expect(screen.getByText("Cost of revenue")).toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Collapse all" }));
      await waitFor(() => expect(screen.queryByText("Cost of revenue")).not.toBeInTheDocument());
      expect(screen.getByRole("button", { name: "Expand all" })).toBeInTheDocument();
    });

    it("keeps nested breakdowns closed until each level is opened", async () => {
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(balanceStatement()) as never,
      );
      renderView("BS");
      await userEvent.click(await screen.findByRole("button", { name: "Expand Total assets" }));

      expect(screen.getByText("Total current assets")).toBeInTheDocument();
      expect(screen.getByText("Total non-current assets")).toBeInTheDocument();
      expect(screen.queryByText("Cash and equivalents")).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Expand Total current assets" }));

      expect(screen.getByText("Cash and equivalents")).toBeInTheDocument();
      expect(screen.queryByText("Property, plant and equipment")).not.toBeInTheDocument();
    });
  });

  describe("columns", () => {
    it("right-aligns each period heading over its numbers, and keeps the label heading left", async () => {
      renderView();
      const heading = (await screen.findByText("FY2024")).closest(".ag-header-cell");
      const figure = screen.getByText("391,035").closest("[col-id]");

      expect(heading).toHaveClass("ag-right-aligned-header");
      expect(figure).toHaveClass("ag-right-aligned-cell");
      expect(screen.getByText("USD millions").closest(".ag-header-cell")).not.toHaveClass(
        "ag-right-aligned-header",
      );
    });
  });

  describe("YoY", () => {
    it("shows growth in italics, green when up and red when down", async () => {
      renderView();
      await userEvent.click(await screen.findByRole("button", { name: "Expand all" }));
      await userEvent.click(screen.getByRole("button", { name: "YoY" }));

      const up = screen.getByText("2.0%").closest("[col-id]");
      const down = screen.getByText("(1.8%)").closest("[col-id]");
      expect(up).toHaveClass("text-positive", "italic");
      expect(down).toHaveClass("text-negative", "italic");
      expect(screen.getAllByRole("gridcell", { name: "YoY" })[0]).toHaveClass("italic");
    });

    it("leaves a missing growth figure neutral", async () => {
      renderView();
      await userEvent.click(await screen.findByRole("button", { name: "YoY" }));

      const missing = screen.getAllByText("—")[0]!.closest("[col-id]");
      expect(missing).not.toHaveClass("text-positive");
      expect(missing).not.toHaveClass("text-negative");
    });
  });

  describe("common size base", () => {
    it("offers the base only while common size is on", async () => {
      renderView();
      await screen.findByText("Revenue");
      expect(
        screen.queryByRole("radiogroup", { name: "Common size base" }),
      ).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Common size" }));

      const group = screen.getByRole("radiogroup", { name: "Common size base" });
      expect(within(group).getByRole("radio", { name: "Revenue" })).toBeChecked();
      expect(within(group).getByRole("radio", { name: "Parent row" })).not.toBeChecked();
    });

    it("names total assets as the base on the balance sheet", async () => {
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(balanceStatement()) as never,
      );
      renderView("BS");
      await userEvent.click(await screen.findByRole("button", { name: "Common size" }));

      expect(screen.getByRole("radio", { name: "Total assets" })).toBeChecked();
    });

    it("refetches with the parent base when it is picked", async () => {
      renderView();
      await userEvent.click(await screen.findByRole("button", { name: "Common size" }));

      await userEvent.click(screen.getByRole("radio", { name: "Parent row" }));

      expect(getStatementApiV1CompaniesTickerStatementsGet).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { type: "IS", freq: "annual", common_size_base: "parent", basis: "reported" },
      });
    });
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

  it("marks approximated cells like derived ones, since they are not hard facts", async () => {
    const payload = incomeStatement();
    payload.rows[0]!.provenance = ["approximated", "reported"];
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(payload) as never,
    );
    renderView();

    const approximated = (await screen.findByText("~383,285")).closest("[col-id]");
    expect(approximated).toHaveClass("prov-derived");
    expect(screen.getByText(/rebuilt Q4 share counts and EPS/)).toBeInTheDocument();
  });

  it("marks an approximated value with a tilde and leaves the other cells unmarked", async () => {
    const payload = incomeStatement();
    payload.rows[0]!.provenance = ["approximated", "reported"];
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(payload) as never,
    );
    renderView();

    expect(await screen.findByText("~383,285")).toBeInTheDocument();
    expect(screen.getByText("391,035")).toBeInTheDocument();
    expect(screen.queryByText("~391,035")).not.toBeInTheDocument();
    expect(screen.getByText(/~ Approximated/)).toBeInTheDocument();
  });

  it("shows an inferred zero as a muted 0", async () => {
    const payload = incomeStatement();
    payload.rows[0]!.values = ["0", "391035000000"];
    payload.rows[0]!.provenance = ["zero_inferred", "reported"];
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(payload) as never,
    );
    renderView();
    await screen.findByText("391,035");

    expect(cell("revenue", "FY2023")).toHaveTextContent(/^0$/);
    expect(cell("revenue", "FY2023")).toHaveClass("prov-zero");
    expect(cell("revenue", "FY2024")).not.toHaveClass("prov-zero");
    expect(screen.getByText(/Inferred 0/)).toBeInTheDocument();
  });

  it("keeps a reported cell exactly as it was", async () => {
    renderView();
    await screen.findByText("383,285");

    const reported = cell("revenue", "FY2023");
    expect(reported).toHaveTextContent(/^383,285$/);
    expect(reported).not.toHaveClass("prov-zero");
    expect(reported).not.toHaveClass("prov-derived");
  });

  describe("basis", () => {
    const lastQuery = () =>
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mock.calls.at(-1)![0]!.query;

    it("defaults to reported", async () => {
      renderView();
      await screen.findByText("Revenue");

      expect(screen.getByRole("radiogroup", { name: "Basis" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "Reported" })).toBeChecked();
      expect(screen.getByRole("radio", { name: "Normalized" })).not.toBeChecked();
      expect(
        vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mock.calls[0]![0]!.query,
      ).toMatchObject({ basis: "reported" });
    });

    it("the basis toggle sends basis=normalized, and back to reported", async () => {
      renderView();
      await screen.findByText("Revenue");

      await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));
      await waitFor(() => expect(lastQuery()).toMatchObject({ basis: "normalized" }));

      await userEvent.click(screen.getByRole("radio", { name: "Reported" }));
      await waitFor(() => expect(lastQuery()).toMatchObject({ basis: "reported" }));
    });

    it("keeps the basis when the selected item is clicked again", async () => {
      renderView();
      await screen.findByText("Revenue");
      await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));
      await waitFor(() => expect(lastQuery()).toMatchObject({ basis: "normalized" }));

      await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));

      expect(lastQuery()).toMatchObject({ basis: "normalized" });
      const bases = vi
        .mocked(getStatementApiV1CompaniesTickerStatementsGet)
        .mock.calls.map((call) => call[0]!.query!.basis);
      expect(bases).not.toContain("");
      expect(screen.getByRole("radio", { name: "Normalized" })).toBeChecked();
    });

    it("survives a frequency change", async () => {
      renderView();
      await screen.findByText("Revenue");
      await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));

      await userEvent.click(screen.getByRole("radio", { name: "Quarterly" }));

      await waitFor(() =>
        expect(lastQuery()).toMatchObject({ freq: "quarterly", basis: "normalized" }),
      );
      expect(screen.getByRole("radio", { name: "Normalized" })).toBeChecked();
    });

    it("a normalized cell has the prov-normalized class, a null one has no provenance class", async () => {
      const payload = incomeStatement();
      payload.rows[0]!.provenance = ["normalized", null];
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(payload) as never,
      );
      renderView();

      const normalized = (await screen.findByText("383,285")).closest("[col-id]");
      expect(normalized).toHaveClass("prov-normalized");
      expect(normalized).not.toHaveClass("prov-derived");
      expect(normalized).not.toHaveClass("italic");
      const plain = screen.getByText("391,035").closest("[col-id]");
      expect(plain).not.toHaveClass("prov-normalized");
      expect(plain).not.toHaveClass("prov-derived");
    });

    it("explains normalized cells in the legend", async () => {
      renderView();
      await screen.findByText("Revenue");

      expect(screen.getByText(/Normalized: with your adjustments/)).toBeInTheDocument();
    });
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

  it("opens an adjustable cell with Add adjustment, and a non-adjustable one without", async () => {
    const payload = incomeStatement();
    payload.rows[0]!.adjustable = true;
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(payload) as never,
    );
    vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet).mockResolvedValue(
      okResult(cellDetail) as never,
    );
    renderView();

    await userEvent.click(await screen.findByText("391,035"));
    const sheet = await screen.findByRole("dialog");
    expect(await within(sheet).findByRole("button", { name: "Add adjustment" })).toBeVisible();

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await userEvent.click(screen.getByText("180,683"));
    const second = await screen.findByRole("dialog");
    await within(second).findByText("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax");
    expect(
      within(second).queryByRole("button", { name: "Add adjustment" }),
    ).not.toBeInTheDocument();
  });

  describe("adjusting where there is no data", () => {
    it("opens an empty cell of an adjustable line with Add adjustment", async () => {
      const payload = incomeStatement();
      payload.rows[0] = { ...payload.rows[0]!, adjustable: true, values: [null, "391035000000"] };
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(payload) as never,
      );
      vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet).mockResolvedValue(
        okResult(emptyCellDetail("revenue", "Revenue", 2023)) as never,
      );
      renderView();
      await screen.findByText("Revenue");

      const empty = cell("revenue", "FY2023");
      expect(empty).toHaveTextContent("—");
      expect(empty).toHaveClass("cursor-pointer");
      await userEvent.click(empty);

      const sheet = await screen.findByRole("dialog");
      expect(getCellApiV1CompaniesTickerStatementsCellGet).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        query: { code: "revenue", fiscal_year: 2023, fiscal_period: "FY" },
      });
      expect(await within(sheet).findByRole("button", { name: "Add adjustment" })).toBeVisible();
      expect(within(sheet).getByText("—")).toBeInTheDocument();
      expect(within(sheet).getByText("(no value)")).toBeInTheDocument();
    });

    it("leaves an empty cell of a non-adjustable line inert", async () => {
      const payload = incomeStatement();
      payload.rows[1] = { ...payload.rows[1]!, adjustable: false, values: [null, "180683000000"] };
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(payload) as never,
      );
      renderView();
      await screen.findByText("Revenue");

      const empty = cell("gross_profit", "FY2023");
      expect(empty).toHaveTextContent("—");
      expect(empty).not.toHaveClass("cursor-pointer");
      await userEvent.click(empty);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(getCellApiV1CompaniesTickerStatementsCellGet).not.toHaveBeenCalled();
    });
  });

  describe("show empty lines", () => {
    // "Other income" is adjustable with no value anywhere; `rnd` is empty and not adjustable.
    beforeEach(() => {
      const payload = incomeStatement();
      const rnd = payload.rows.find((r) => r.code === "rnd")!;
      payload.rows = [
        ...payload.rows,
        { ...rnd, code: "other_income", label: "Other income", depth: 0, adjustable: true },
        { ...rnd, code: "unmapped", label: "Unmapped item", depth: 0, adjustable: false },
      ];
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(payload) as never,
      );
    });
    const toggle = () => screen.getByRole("button", { name: "Show empty lines" });

    it("is off by default and hides the empty adjustable line", async () => {
      renderView();
      await screen.findByText("Revenue");

      expect(toggle()).toHaveAttribute("aria-pressed", "false");
      expect(screen.queryByText("Other income")).not.toBeInTheDocument();
    });

    it("shows the empty adjustable lines when on, never the non-adjustable ones", async () => {
      renderView();
      await screen.findByText("Revenue");

      await userEvent.click(toggle());

      expect(await screen.findByText("Other income")).toBeInTheDocument();
      expect(toggle()).toHaveAttribute("aria-pressed", "true");
      expect(screen.queryByText("Unmapped item")).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
      expect(await screen.findByText("Cost of revenue")).toBeInTheDocument();
      expect(screen.queryByText("Research and development")).not.toBeInTheDocument();
    });

    it("lets Expand all open a parent whose only breakdown is an empty adjustable line", async () => {
      const payload = incomeStatement();
      const rnd = payload.rows.find((r) => r.code === "rnd")!;
      const eps = payload.rows.findIndex((r) => r.code === "eps_diluted");
      payload.rows.splice(eps + 1, 0, {
        ...rnd,
        code: "eps_adjustment",
        label: "EPS adjustment",
        depth: 1,
        adjustable: true,
      });
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(payload) as never,
      );
      renderView();
      await screen.findByText("Revenue");

      await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
      expect(await screen.findByText("Cost of revenue")).toBeInTheDocument();
      expect(screen.queryByText("EPS adjustment")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /EPS, diluted/ })).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Collapse all" }));

      await userEvent.click(toggle());
      await userEvent.click(screen.getByRole("button", { name: "Expand all" }));

      expect(await screen.findByText("EPS adjustment")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Collapse EPS, diluted" })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
      expect(screen.getByRole("button", { name: "Collapse all" })).toBeInTheDocument();
    });

    it("opens a cell of a shown empty line with Add adjustment", async () => {
      vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet).mockResolvedValue(
        okResult(emptyCellDetail("other_income", "Other income", 2024)) as never,
      );
      renderView();
      await screen.findByText("Revenue");
      await userEvent.click(toggle());
      await screen.findByText("Other income");

      const empty = cell("other_income", "FY2024");
      expect(empty).toHaveTextContent("—");
      await userEvent.click(empty);

      const sheet = await screen.findByRole("dialog");
      expect(getCellApiV1CompaniesTickerStatementsCellGet).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        query: { code: "other_income", fiscal_year: 2024, fiscal_period: "FY" },
      });
      expect(await within(sheet).findByRole("button", { name: "Add adjustment" })).toBeVisible();
      expect(within(sheet).getByText("—")).toBeInTheDocument();
      expect(within(sheet).getByText("(no value)")).toBeInTheDocument();
    });

    it("includes shown empty lines in the CSV", async () => {
      const download = captureDownload();
      renderView();
      await screen.findByText("Revenue");
      const exportLines = async (index: number) => {
        await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));
        return (await readText(download.blobs[index]!)).trim().split(/\r?\n/);
      };

      expect((await exportLines(0)).some((line) => line.includes("Other income"))).toBe(false);

      await userEvent.click(toggle());
      await screen.findByText("Other income");
      const lines = await exportLines(1);
      expect(lines).toContain('"Other income","",""');
      expect(lines.some((line) => line.includes("Unmapped item"))).toBe(false);
      vi.mocked(HTMLAnchorElement.prototype.click).mockRestore();
    });

    it("resets Show empty lines when the tab changes", async () => {
      const queryClient = createQueryClient();
      queryClient.setDefaultOptions({ queries: { retry: false } });
      const view = (key: string) => (
        <QueryClientProvider client={queryClient}>
          <StatementView key={key} ticker="AAPL" cik="0000320193" type="IS" />
        </QueryClientProvider>
      );
      const { rerender } = render(view("income-statement"));
      await screen.findByText("Revenue");
      await userEvent.click(toggle());
      expect(toggle()).toHaveAttribute("aria-pressed", "true");
      expect(await screen.findByText("Other income")).toBeInTheDocument();

      rerender(view("cash-flow"));

      await screen.findByText("Revenue");
      expect(toggle()).toHaveAttribute("aria-pressed", "false");
      expect(screen.queryByText("Other income")).not.toBeInTheDocument();
    });

    it("stays on after a frequency change and after a basis change", async () => {
      const lastQuery = () =>
        vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mock.calls.at(-1)![0]!.query;
      renderView();
      await screen.findByText("Revenue");
      await userEvent.click(toggle());

      await userEvent.click(screen.getByRole("radio", { name: "Quarterly" }));
      await waitFor(() => expect(lastQuery()).toMatchObject({ freq: "quarterly" }));
      expect(toggle()).toHaveAttribute("aria-pressed", "true");
      expect(await screen.findByText("Other income")).toBeInTheDocument();

      await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));
      await waitFor(() => expect(lastQuery()).toMatchObject({ basis: "normalized" }));
      expect(toggle()).toHaveAttribute("aria-pressed", "true");
      expect(await screen.findByText("Other income")).toBeInTheDocument();
    });
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
    it("keeps plain values for approximated and inferred cells", async () => {
      const payload = incomeStatement();
      payload.rows[0]!.values = ["0", "391035000000"];
      payload.rows[0]!.provenance = ["zero_inferred", "approximated"];
      vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
        okResult(payload) as never,
      );
      const download = captureDownload();
      renderView();
      await screen.findByText("~391,035");

      await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));

      const lines = (await readText(download.blobs[0]!)).trim().split(/\r?\n/);
      expect(lines).toContain('"Revenue","0","391035"');
      expect(lines.join("")).not.toContain("~");
    });

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
      expect(lines).toContain('"Gross profit YoY","","6.8%"');
      expect(lines.some((line) => line.includes("Cost of revenue"))).toBe(false); // collapsed
      expect(lines.some((line) => line.includes("Research"))).toBe(false);
    });
  });
});

describe("StatementView note markers", () => {
  const links = vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet);
  const notes = vi.mocked(listNotesApiV1CompaniesTickerNotesGet);

  it("marks the cell a note is linked to, and only that one", async () => {
    links.mockResolvedValue(okResult(noteLinks()) as never);
    renderView();
    await screen.findByText("391,035");
    await waitFor(() => expect(cell("revenue", "FY2024")).toHaveClass("has-note"));
    expect(cell("revenue", "FY2023")).not.toHaveClass("has-note");
    expect(cell("gross_profit", "FY2024")).not.toHaveClass("has-note");
  });

  it("marks nothing without links", async () => {
    renderView();
    await screen.findByText("391,035");
    expect(document.querySelector(".has-note")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Notes on/ })).not.toBeInTheDocument();
  });

  it("marks a quarter cell on the quarterly grid", async () => {
    const quarterly = incomeStatement({
      freq: "quarterly",
      periods: [
        {
          key: "Q42024",
          label: "Q4 FY24",
          fiscal_year: 2024,
          fiscal_period: "Q4",
          period_start: "2024-06-30",
          period_end: "2024-09-28",
          is_forecast: false,
        },
      ],
      rows: incomeStatement().rows.map((row) => ({
        ...row,
        values: row.values.slice(1),
        provenance: row.provenance.slice(1),
        yoy: row.yoy.slice(1),
        common_size: row.common_size.slice(1),
      })),
    });
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(quarterly) as never,
    );
    links.mockResolvedValue(
      okResult([
        noteLink({ canonical_code: "revenue", fiscal_year: 2024, fiscal_period: "Q4" }),
      ]) as never,
    );
    renderView();
    await screen.findByText("391,035");
    await waitFor(() => expect(cell("revenue", "Q42024")).toHaveClass("has-note"));
  });

  it("never marks a TTM column", async () => {
    const ttm = incomeStatement({
      freq: "ttm",
      periods: [
        {
          key: "TTM2024Q3",
          label: "TTM Q3 FY24",
          fiscal_year: 2024,
          fiscal_period: "Q3",
          period_start: "2023-07-01",
          period_end: "2024-06-29",
          is_forecast: false,
        },
      ],
      rows: incomeStatement().rows.map((row) => ({
        ...row,
        values: row.values.slice(1),
        provenance: row.provenance.slice(1),
        yoy: row.yoy.slice(1),
        common_size: row.common_size.slice(1),
      })),
    });
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
      okResult(ttm) as never,
    );
    links.mockResolvedValue(
      okResult([
        noteLink({ canonical_code: "revenue", fiscal_year: 2024, fiscal_period: "Q3" }),
      ]) as never,
    );
    renderView();
    await screen.findByText("391,035");
    await waitFor(() => expect(links).toHaveBeenCalled());
    expect(cell("revenue", "TTM2024Q3")).not.toHaveClass("has-note");
  });

  it("still opens the cell details from a marked cell", async () => {
    links.mockResolvedValue(okResult(noteLinks()) as never);
    vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet).mockResolvedValue(
      okResult(cellDetail) as never,
    );
    renderView();
    await screen.findByText("391,035");
    await waitFor(() => expect(cell("revenue", "FY2024")).toHaveClass("has-note"));
    await userEvent.click(cell("revenue", "FY2024"));
    expect(await screen.findByText("Vintages")).toBeVisible();
  });

  it("puts a line marker after the label of a line with a line note", async () => {
    links.mockResolvedValue(okResult([noteLink({ canonical_code: "gross_profit" })]) as never);
    renderView();
    expect(await screen.findByRole("button", { name: "Notes on Gross profit" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Notes on Revenue" })).not.toBeInTheDocument();
  });

  it("opens the line's notes from the line marker and adds a line note", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 23, 22, 30));
    links.mockResolvedValue(okResult([noteLink({ canonical_code: "gross_profit" })]) as never);
    notes.mockResolvedValue(
      okResult([
        note({
          id: 4,
          body_md: "Watch services mix",
          canonical_code: "gross_profit",
          label: "Gross profit",
          fiscal_year: null,
          fiscal_period: null,
        }),
      ]) as never,
    );
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Notes on Gross profit" }));
    expect(await screen.findByText("Watch services mix")).toBeVisible();
    expect(notes).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { code: "gross_profit" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(screen.getByText("Linked to Gross profit")).toBeVisible();
    await userEvent.type(screen.getByLabelText("Note"), "New thought");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(vi.mocked(createNoteApiV1CompaniesTickerNotesPost)).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: {
          body_md: "New thought",
          canonical_code: "gross_profit",
          fiscal_year: null,
          fiscal_period: null,
          note_date: "2026-10-23",
        },
      }),
    );
  });

  it("keeps the statement when the links cannot load", async () => {
    links.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("391,035")).toBeVisible();
    expect(document.querySelector(".has-note")).toBeNull();
  });
});

describe("StatementView import", () => {
  it("opens the import sheet from the toolbar", async () => {
    renderView();
    await screen.findByText("391,035");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByText("Import statements")).toBeVisible();
  });
});

describe("StatementView import and custom lines", () => {
  const getStatement = vi.mocked(getStatementApiV1CompaniesTickerStatementsGet);
  const getCell = vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet);

  async function renderCustom() {
    getStatement.mockResolvedValue(okResult(customIncomeStatement()) as never);
    renderView();
    await screen.findByText("391,035");
    await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
    await screen.findByText("Products");
  }

  it("styles an imported value apart and explains it in the legend", async () => {
    await renderCustom();
    expect(cell("custom:products", "FY2024")).toHaveClass("prov-imported");
    expect(cell("revenue", "FY2024")).not.toHaveClass("prov-imported");
    expect(screen.getByText(/Imported: from your file/)).toBeInTheDocument();
  });

  it("nests custom lines under their parent with a custom marker", async () => {
    await renderCustom();
    const label = (code: string) =>
      document.querySelector(`[row-id="${code}"] [col-id="label"] span[style]`) as HTMLElement;
    const parentPad = parseInt(label("cost_of_revenue").style.paddingLeft);
    expect(parseInt(label("custom:products").style.paddingLeft)).toBeGreaterThan(parentPad);
    expect(within(label("custom:products")).getByText("custom")).toBeInTheDocument();
    expect(within(label("custom:services")).getByText("custom")).toBeInTheDocument();
    expect(within(label("cost_of_revenue")).queryByText("custom")).not.toBeInTheDocument();
    expect(within(label("other:cost_of_revenue")).queryByText("custom")).not.toBeInTheDocument();
  });

  it("collapses the breakdown with its parent", async () => {
    await renderCustom();
    await userEvent.click(screen.getByRole("button", { name: "Collapse Cost of revenue" }));
    await waitFor(() => expect(screen.queryByText("Products")).not.toBeInTheDocument());
    expect(screen.queryByText("Other Cost of revenue")).not.toBeInTheDocument();
  });

  it("opens the cell details of a custom line", async () => {
    getCell.mockResolvedValue(
      okResult({ ...cellDetail, code: "custom:products", label: "Products" }) as never,
    );
    await renderCustom();
    await userEvent.click(cell("custom:products", "FY2024"));
    await waitFor(() =>
      expect(getCell).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        query: { code: "custom:products", fiscal_year: 2024, fiscal_period: "FY" },
      }),
    );
  });

  it("leaves the Other row inert: it has no cell of its own", async () => {
    await renderCustom();
    expect(cell("other:cost_of_revenue", "FY2024")).not.toHaveClass("cursor-pointer");
    await userEvent.click(cell("other:cost_of_revenue", "FY2024"));
    expect(getCell).not.toHaveBeenCalled();
  });

  it("exports the custom lines and the Other row in the CSV", async () => {
    const download = captureDownload();
    await renderCustom();
    await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));
    const lines = (await readText(download.blobs[0]!)).trim().split(/\r?\n/);
    expect(lines).toContain('"Products","","150000"');
    expect(lines).toContain('"Services","","50000"');
    expect(lines).toContain('"Other Cost of revenue","","10352"');
  });
});
