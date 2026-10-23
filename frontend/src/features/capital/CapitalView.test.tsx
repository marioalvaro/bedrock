import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createNoteApiV1CompaniesTickerNotesPost,
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { capitalAllocation } from "@/test/analysis";
import { note, noteLink } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";

import { CapitalView } from "./CapitalView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
  createNoteApiV1CompaniesTickerNotesPost: vi.fn(),
}));

const mockedGet = vi.mocked(getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet);
const links = vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet);
const listNotes = vi.mocked(listNotesApiV1CompaniesTickerNotesGet);
const createNote = vi.mocked(createNoteApiV1CompaniesTickerNotesPost);

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <CapitalView ticker="AAPL" />
    </QueryClientProvider>,
  );
}

const cell = (row: string, period: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${period}"]`) as HTMLElement;
const row = (id: string) => document.querySelector(`[row-id="${id}"]`);
// AG Grid appends new rows to the DOM: order them by their position in the grid.
const rowIds = () =>
  Array.from(document.querySelectorAll("[row-id]"))
    .sort((a, b) => Number(a.getAttribute("row-index")) - Number(b.getAttribute("row-index")))
    .map((el) => el.getAttribute("row-id"));
const lastQuery = () => mockedGet.mock.calls.at(-1)![0]!.query;
const percentToggle = () => screen.getByRole("button", { name: "% of CFO / FCF" });

const PCT_PARENTS = ["capex", "buybacks", "dividends_paid", "shareholder_returns"];
const NO_PCT = ["cfo", "free_cash_flow", "d_and_a", "capex_to_da", "net_share_change"];

function captureDownload() {
  const blobs: Blob[] = [];
  const names: string[] = [];
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn((blob: Blob | MediaSource) => {
      blobs.push(blob as Blob);
      return "blob:csv";
    }),
    revokeObjectURL: vi.fn(),
  });
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
  mockedGet.mockResolvedValue(okResult(capitalAllocation()) as never);
  links.mockResolvedValue(okResult([]) as never);
  listNotes.mockResolvedValue(okResult([]) as never);
  createNote.mockResolvedValue(okResult(note({ id: 9 }), 201) as never);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("CapitalView", () => {
  it("lists the payload rows in order, with the scale in the label header", async () => {
    renderView();
    await screen.findByText("Cash from operations");

    expect(rowIds()).toEqual(capitalAllocation().rows.map((r) => r.code));
    expect(screen.getByText("USD millions")).toBeInTheDocument();
    expect(screen.getByText("FY2023")).toBeInTheDocument();
    expect(screen.getByText("FY2024")).toBeInTheDocument();
  });

  it("requests annual by default and ttm after the toggle", async () => {
    renderView();
    await screen.findByText("Free cash flow");
    expect(mockedGet).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { freq: "annual" },
    });
    expect(screen.getByRole("radio", { name: "Annual" })).toBeChecked();

    await userEvent.click(screen.getByRole("radio", { name: "TTM" }));

    await waitFor(() => expect(lastQuery()).toEqual({ freq: "ttm" }));
    expect(screen.getByRole("radio", { name: "TTM" })).toBeChecked();
  });

  it("cannot deselect the active frequency", async () => {
    renderView();
    await screen.findByText("Free cash flow");
    const calls = mockedGet.mock.calls.length;

    await userEvent.click(screen.getByRole("radio", { name: "Annual" }));

    expect(screen.getByRole("radio", { name: "Annual" })).toBeChecked();
    expect(mockedGet.mock.calls.length).toBe(calls);
  });

  describe("formatting", () => {
    it("formats USD in the page scale, negatives in parentheses, null as a dash", async () => {
      renderView();
      await screen.findByText("Cash from operations");

      expect(cell("cfo", "FY2024")).toHaveTextContent("118,254");
      expect(cell("capex", "FY2023")).toHaveTextContent("(10,959)");
      expect(cell("buybacks", "FY2024")).toHaveTextContent("(94,949)");
      expect(cell("acquisitions", "FY2023")).toHaveTextContent("—");
      expect(cell("acquisitions", "FY2024")).toHaveTextContent("—");
    });

    it("rescales USD rows with the page scale but not x or pct rows", async () => {
      renderView();
      await screen.findByText("Cash from operations");

      await userEvent.click(screen.getByRole("radio", { name: "B" }));

      expect(cell("cfo", "FY2024")).toHaveTextContent("118.3");
      expect(cell("capex", "FY2023")).toHaveTextContent("(11.0)");
      expect(cell("capex_to_da", "FY2023")).toHaveTextContent("1.0x");
      expect(cell("net_share_change", "FY2023")).toHaveTextContent("(2.4%)");
      expect(screen.getByText("USD billions")).toBeInTheDocument();
    });

    it("formats x rows as multiples and pct rows as percents, with a unit hint", async () => {
      renderView();
      await screen.findByText("Capex / D&A");

      expect(cell("capex_to_da", "FY2023")).toHaveTextContent("1.0x");
      expect(cell("capex_to_da", "FY2024")).toHaveTextContent("0.8x");
      expect(cell("net_share_change", "FY2023")).toHaveTextContent("(2.4%)");
      expect(cell("net_share_change", "FY2024")).toHaveTextContent("(2.6%)");
      expect(row("capex_to_da")).toHaveTextContent("Capex / D&A· x");
      expect(row("net_share_change")).toHaveTextContent("Net share-count change· %");
      expect(row("cfo")).not.toHaveTextContent("·");
    });

    it("right-aligns the period columns", async () => {
      renderView();
      const heading = (await screen.findByText("FY2024")).closest(".ag-header-cell");
      expect(heading).toHaveClass("ag-right-aligned-header");
      expect(cell("cfo", "FY2024")).toHaveClass("ag-right-aligned-cell");
    });
  });

  describe("% of CFO / FCF", () => {
    it("is off by default: no sub-rows", async () => {
      renderView();
      await screen.findByText("Cash from operations");

      expect(percentToggle()).toHaveAttribute("aria-pressed", "false");
      expect(rowIds().some((id) => id!.includes(":"))).toBe(false);
    });

    // jsdom has no viewport, so AG Grid renders only the first ~10 rows: each test below keeps
    // its payload within that, and the two subsets together cover every line of the table.
    const subset = (codes: string[]) => {
      const payload = capitalAllocation();
      payload.rows = codes.map((code) => payload.rows.find((r) => r.code === code)!);
      mockedGet.mockResolvedValue(okResult(payload) as never);
    };
    const WITH_PCT_A = ["capex", "acquisitions", "buybacks", "d_and_a"];
    const WITH_PCT_B = [
      "dividends_paid",
      "shareholder_returns",
      "cfo",
      "free_cash_flow",
      "capex_to_da",
      "net_share_change",
    ];

    it.each([{ codes: WITH_PCT_A }, { codes: WITH_PCT_B }])(
      "adds two sub-rows under each row with percentages, and none under the others (#$#)",
      async ({ codes }) => {
        subset(codes);
        renderView();
        await waitFor(() => expect(rowIds()).toEqual(codes));
        expect(percentToggle()).toHaveAttribute("aria-pressed", "false");

        await userEvent.click(percentToggle());

        const expected = codes.flatMap((code) =>
          PCT_PARENTS.includes(code) ? [code, `${code}:pct_of_cfo`, `${code}:pct_of_fcf`] : [code],
        );
        await waitFor(() => expect(rowIds()).toEqual(expected));
        for (const code of NO_PCT) {
          expect(row(`${code}:pct_of_cfo`)).toBeNull();
          expect(row(`${code}:pct_of_fcf`)).toBeNull();
        }
      },
    );

    it("adds a % sub-row only when its array has a non-null value, CFO and FCF independently", async () => {
      const payload = capitalAllocation();
      const capex = payload.rows.find((r) => r.code === "capex")!;
      capex.pct_of_fcf = null;
      payload.rows = ["capex", "acquisitions", "buybacks"].map((code) =>
        payload.rows.find((r) => r.code === code)!,
      );
      mockedGet.mockResolvedValue(okResult(payload) as never);
      renderView();
      await screen.findByText("Capital expenditures");

      await userEvent.click(percentToggle());

      await waitFor(() =>
        expect(rowIds()).toEqual([
          "capex",
          "capex:pct_of_cfo",
          "acquisitions",
          "buybacks",
          "buybacks:pct_of_cfo",
          "buybacks:pct_of_fcf",
        ]),
      );
    });

    it("shows the percentages, labels the sub-rows muted and indented", async () => {
      subset(WITH_PCT_A);
      renderView();
      await screen.findByText("Capital expenditures");
      await userEvent.click(percentToggle());
      await waitFor(() => expect(rowIds()).toHaveLength(8));

      expect(cell("capex:pct_of_cfo", "FY2023")).toHaveTextContent("9.9%");
      expect(cell("capex:pct_of_fcf", "FY2024")).toHaveTextContent("8.7%");
      expect(cell("buybacks:pct_of_cfo", "FY2024")).toHaveTextContent("80.3%");
      expect(cell("buybacks:pct_of_fcf", "FY2024")).toHaveTextContent("87.3%");
      expect(row("acquisitions:pct_of_cfo")).toBeNull();
      expect(row("acquisitions:pct_of_fcf")).toBeNull();
      const label = row("capex:pct_of_cfo")!.querySelector('[col-id="label"]')!;
      expect(label).toHaveTextContent("% of CFO");
      expect(label).toHaveClass("text-muted-foreground");
      expect(row("capex:pct_of_fcf")!.querySelector('[col-id="label"]')).toHaveTextContent(
        "% of FCF",
      );
    });

    it("shows the shareholder-returns percentages above 100%", async () => {
      subset(WITH_PCT_B);
      renderView();
      await screen.findByText("Cash from operations");
      await userEvent.click(percentToggle());

      await waitFor(() =>
        expect(cell("shareholder_returns:pct_of_fcf", "FY2024")).toHaveTextContent("101.3%"),
      );
      expect(cell("dividends_paid:pct_of_cfo", "FY2023")).toHaveTextContent("13.6%");
    });

    it("removes the sub-rows when toggled off", async () => {
      subset(WITH_PCT_A);
      renderView();
      await screen.findByText("Capital expenditures");
      await userEvent.click(percentToggle());
      await waitFor(() => expect(row("capex:pct_of_cfo")).not.toBeNull());

      await userEvent.click(percentToggle());

      await waitFor(() => expect(row("capex:pct_of_cfo")).toBeNull());
      expect(percentToggle()).toHaveAttribute("aria-pressed", "false");
      expect(rowIds()).toEqual(WITH_PCT_A);
    });

    it("stays on across a frequency change", async () => {
      subset(WITH_PCT_A);
      renderView();
      await screen.findByText("Capital expenditures");
      await userEvent.click(percentToggle());

      await userEvent.click(screen.getByRole("radio", { name: "TTM" }));
      await waitFor(() => expect(lastQuery()).toEqual({ freq: "ttm" }));

      expect(percentToggle()).toHaveAttribute("aria-pressed", "true");
      await waitFor(() => expect(rowIds()).toHaveLength(8));
      expect(row("capex:pct_of_cfo")).not.toBeNull();
    });
  });

  describe("states", () => {
    it("shows Loading… while pending", () => {
      mockedGet.mockReturnValue(new Promise(() => {}) as never);
      renderView();
      expect(screen.getByText("Loading…")).toBeInTheDocument();
    });

    it("shows an error line when the API fails", async () => {
      mockedGet.mockResolvedValue(errorResult(500) as never);
      renderView();

      const message = await screen.findByText("Could not load the capital allocation.");
      expect(message).toHaveClass("text-destructive");
    });

    it("shows the error line for a 200 whose body is not a payload", async () => {
      mockedGet.mockResolvedValue(okResult("<!doctype html><html></html>") as never);
      renderView();

      expect(await screen.findByText("Could not load the capital allocation.")).toBeInTheDocument();
    });

    it("shows the empty state when there are no rows", async () => {
      mockedGet.mockResolvedValue(okResult(capitalAllocation({ rows: [] })) as never);
      renderView();

      expect(
        await screen.findByText("No capital allocation for this company."),
      ).toBeInTheDocument();
    });

    it("shows the empty state when there are no periods", async () => {
      mockedGet.mockResolvedValue(okResult(capitalAllocation({ periods: [] })) as never);
      renderView();

      expect(
        await screen.findByText("No capital allocation for this company."),
      ).toBeInTheDocument();
      expect(screen.queryByText("Cash from operations")).not.toBeInTheDocument();
    });
  });

  describe("CSV export", () => {
    it("exports every row in the scale, with plain signs and unit formats", async () => {
      const download = captureDownload();
      renderView();
      await screen.findByText("Cash from operations");

      await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));

      expect(download.names).toEqual(["AAPL_capital_annual.csv"]);
      const lines = (await readText(download.blobs[0]!)).trim().split(/\r?\n/);
      expect(lines[0]).toBe('"USD millions","FY2023","FY2024"');
      expect(lines).toContain('"Cash from operations","110543","118254"');
      expect(lines).toContain('"Capital expenditures","-10959","-9447"');
      expect(lines).toContain('"Acquisitions","",""');
      expect(lines).toContain('"Capex / D&A","1.0","0.8"');
      expect(lines).toContain('"Net share-count change","-2.4%","-2.6%"');
      expect(lines).toHaveLength(11);
      expect(lines.some((line) => line.includes("% of CFO"))).toBe(false);
    });

    it("includes the visible sub-rows, named after their line, and the frequency in the file name", async () => {
      const download = captureDownload();
      renderView();
      await screen.findByText("Cash from operations");
      await userEvent.click(percentToggle());
      await userEvent.click(screen.getByRole("radio", { name: "TTM" }));
      await waitFor(() => expect(lastQuery()).toEqual({ freq: "ttm" }));
      await screen.findByText("Cash from operations");

      await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));

      expect(download.names).toEqual(["AAPL_capital_ttm.csv"]);
      const lines = (await readText(download.blobs[0]!)).trim().split(/\r?\n/);
      expect(lines).toContain('"Capital expenditures % of CFO","9.9%","8.0%"');
      expect(lines).toContain('"Capital expenditures % of FCF","11.0%","8.7%"');
      expect(lines.some((line) => line.includes("Acquisitions %"))).toBe(false);
      expect(lines).toHaveLength(11 + PCT_PARENTS.length * 2);
    });
  });
});

describe("CapitalView notes", () => {
  const capex = (overrides = {}) =>
    noteLink({ metric_kind: "capital", metric_code: "capex", ...overrides });

  it("marks a cell with a capital note, not one with a line note of the same code", async () => {
    links.mockResolvedValue(
      okResult([
        capex({ fiscal_year: 2024, fiscal_period: "FY" }),
        noteLink({ canonical_code: "cfo", fiscal_year: 2023, fiscal_period: "FY" }),
      ]) as never,
    );
    renderView();
    await screen.findByText("Cash from operations");
    await waitFor(() => expect(cell("capex", "FY2024")).toHaveClass("has-note"));
    expect(cell("capex", "FY2023")).not.toHaveClass("has-note");
    expect(cell("cfo", "FY2023")).not.toHaveClass("has-note");
  });

  it("shows a marker on the label of a metric with notes and opens its notes", async () => {
    links.mockResolvedValue(okResult([capex()]) as never);
    listNotes.mockResolvedValue(
      okResult([
        note({
          id: 3,
          body_md: "Capex guided down",
          canonical_code: null,
          metric_kind: "capital",
          metric_code: "capex",
          label: "Capital expenditures",
          fiscal_year: null,
          fiscal_period: null,
        }),
      ]) as never,
    );
    renderView();
    await userEvent.click(
      await screen.findByRole("button", { name: "Notes on Capital expenditures" }),
    );
    expect(await screen.findByText("Capex guided down")).toBeVisible();
    expect(listNotes).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { metric_kind: "capital", metric_code: "capex" },
    });
  });

  it("shows no label marker without metric notes", async () => {
    renderView();
    await screen.findByText("Cash from operations");
    expect(screen.queryByRole("button", { name: /^Notes on/ })).not.toBeInTheDocument();
  });

  it("opens the cell's notes on a click and adds a note linked to metric and period", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 23, 22, 30));
    renderView();
    await screen.findByText("Cash from operations");
    await userEvent.click(cell("capex", "FY2024"));

    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText("Capital expenditures")).toBeVisible();
    expect(listNotes).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: {
        metric_kind: "capital",
        metric_code: "capex",
        fiscal_year: 2024,
        fiscal_period: "FY",
      },
    });
    await userEvent.click(await within(sheet).findByRole("button", { name: "Add note" }));
    expect(within(sheet).getByText("Linked to Capital expenditures · FY2024")).toBeVisible();
    await userEvent.type(within(sheet).getByLabelText("Note"), "Lower on plant sale");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(createNote).toHaveBeenCalledTimes(1));
    expect(createNote).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: {
        body_md: "Lower on plant sale",
        canonical_code: null,
        metric_kind: "capital",
        metric_code: "capex",
        fiscal_year: 2024,
        fiscal_period: "FY",
        note_date: "2026-10-23",
      },
    });
  });

  it("opens no sheet from a % sub-row, the label cell or a TTM column", async () => {
    renderView();
    await screen.findByText("Cash from operations");
    await userEvent.click(percentToggle());
    await userEvent.click(cell("capex:pct_of_cfo", "FY2024"));
    await userEvent.click(cell("capex", "label"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    mockedGet.mockResolvedValue(
      okResult(
        capitalAllocation({
          freq: "ttm",
          periods: capitalAllocation().periods.map((p) => ({ ...p, key: `TTM-${p.key}` })),
        }),
      ) as never,
    );
    await userEvent.click(screen.getByRole("radio", { name: "TTM" }));
    await waitFor(() => expect(lastQuery()).toEqual({ freq: "ttm" }));
    await userEvent.click(await waitFor(() => cell("capex", "TTM-FY2024")));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the grid without markers when the links cannot load", async () => {
    links.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("Cash from operations")).toBeVisible();
    expect(document.querySelector(".has-note")).toBeNull();
  });
});
