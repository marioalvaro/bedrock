import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createNoteApiV1CompaniesTickerNotesPost,
  deleteNoteApiV1CompaniesTickerNotesNoteIdDelete,
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet,
  getFlagsApiV1CompaniesTickerFlagsGet,
  getRatiosApiV1CompaniesTickerRatiosGet,
  getStatementApiV1CompaniesTickerStatementsGet,
  listNotesApiV1CompaniesTickerNotesGet,
  updateNoteApiV1CompaniesTickerNotesNoteIdPut,
} from "@/api/generated/sdk.gen";
import type { NoteOut } from "@/api/generated/types.gen";
import { createQueryClient } from "@/lib/query-client";
import { capitalAllocation, flags, ratios } from "@/test/analysis";
import { note } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import { balanceStatement, incomeStatement } from "@/test/statements";

import { NotesView } from "./NotesView";

vi.mock("@/api/generated/sdk.gen", () => ({
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
  createNoteApiV1CompaniesTickerNotesPost: vi.fn(),
  updateNoteApiV1CompaniesTickerNotesNoteIdPut: vi.fn(),
  deleteNoteApiV1CompaniesTickerNotesNoteIdDelete: vi.fn(),
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  getRatiosApiV1CompaniesTickerRatiosGet: vi.fn(),
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet: vi.fn(),
  getFlagsApiV1CompaniesTickerFlagsGet: vi.fn(),
}));

const list = vi.mocked(listNotesApiV1CompaniesTickerNotesGet);
const create = vi.mocked(createNoteApiV1CompaniesTickerNotesPost);
const update = vi.mocked(updateNoteApiV1CompaniesTickerNotesNoteIdPut);
const remove = vi.mocked(deleteNoteApiV1CompaniesTickerNotesNoteIdDelete);
const statement = vi.mocked(getStatementApiV1CompaniesTickerStatementsGet);

const NOTES: NoteOut[] = [
  note({ id: 2, body_md: "# Thesis\n\nServices **mix** is rising.", note_date: "2024-11-02" }),
  note({
    id: 1,
    body_md: "Plain journal entry",
    canonical_code: null,
    label: null,
    fiscal_year: null,
    fiscal_period: null,
    note_date: "2024-10-01",
  }),
];

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <NotesView ticker="AAPL" />
    </QueryClientProvider>,
  );
}

async function renderLoaded(notes: NoteOut[] = NOTES) {
  list.mockResolvedValue(okResult(notes) as never);
  renderView();
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
}

beforeEach(() => {
  list.mockResolvedValue(okResult(NOTES) as never);
  create.mockResolvedValue(okResult(note({ id: 9 }), 201) as never);
  update.mockResolvedValue(okResult(note()) as never);
  remove.mockResolvedValue(okResult(null, 204) as never);
  // Each statement has its own lines, so no option is listed twice.
  const cashFlow = incomeStatement({
    statement: "CF",
    rows: [{ ...incomeStatement().rows[0]!, code: "cfo", label: "Operating cash flow" }],
  });
  vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet).mockResolvedValue(okResult(ratios()) as never);
  vi.mocked(getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet).mockResolvedValue(
    okResult(capitalAllocation()) as never,
  );
  vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(okResult(flags()) as never);
  const annual = incomeStatement();
  const quarter = (period: "Q1" | "Q2") => ({
    ...annual.periods[1]!,
    key: `${period}2024`,
    label: `${period} FY24`,
    fiscal_period: period,
  });
  // FY2024 has two quarters, FY2023 only its annual column.
  const quarterly = incomeStatement({ freq: "quarterly", periods: [quarter("Q1"), quarter("Q2")] });
  statement.mockImplementation((async ({ query }: { query: { type: string; freq: string } }) =>
    okResult(
      query.freq === "quarterly"
        ? quarterly
        : query.type === "BS"
          ? balanceStatement()
          : query.type === "CF"
            ? cashFlow
            : incomeStatement(),
    )) as never);
});

afterEach(() => vi.clearAllMocks());

describe("NotesView list", () => {
  it("lists the notes in the API's order with date and link", async () => {
    await renderLoaded();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText("2024-11-02")).toBeVisible();
    expect(within(items[0]!).getByText("Revenue · FY2024")).toBeVisible();
    expect(within(items[1]!).getByText("Plain journal entry")).toBeVisible();
    expect(within(items[1]!).queryByText(/·/)).toBeNull();
  });

  it("labels a line note, a period note and a quarter note", async () => {
    await renderLoaded([
      note({ id: 3, fiscal_year: null, fiscal_period: null }),
      note({ id: 4, canonical_code: null, label: null, fiscal_year: 2024, fiscal_period: "FY" }),
      note({ id: 5, fiscal_year: 2024, fiscal_period: "Q1" }),
    ]);
    const items = screen.getAllByRole("listitem");
    expect(within(items[0]!).getByText("Revenue")).toBeVisible();
    expect(within(items[1]!).getByText("FY2024")).toBeVisible();
    expect(within(items[2]!).getByText("Revenue · Q1 FY2024")).toBeVisible();
  });

  it("renders the body as Markdown", async () => {
    await renderLoaded();
    expect(screen.getByRole("heading", { name: "Thesis" })).toBeVisible();
    expect(screen.getByText("mix").tagName).toBe("STRONG");
  });

  it("does not render HTML in a body", async () => {
    await renderLoaded([
      note({ body_md: "before <script>window.pwned = 1</script> <b>bold</b> after" }),
    ]);
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByText(/before/)).toBeVisible();
  });

  it("opens links in a new tab", async () => {
    await renderLoaded([note({ body_md: "[10-K](https://www.sec.gov/)" })]);
    const link = screen.getByRole("link", { name: "10-K" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("does not make a javascript: link clickable", async () => {
    await renderLoaded([note({ body_md: "[x](javascript:alert(1))" })]);
    const link = screen.queryByRole("link", { name: "x" });
    expect(link?.getAttribute("href") ?? "").not.toContain("javascript:");
  });

  it("shows an empty state", async () => {
    await renderLoaded([]);
    expect(screen.getByText("No notes yet.")).toBeVisible();
  });

  it("shows an error when the list cannot load", async () => {
    list.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("Could not load the notes.")).toBeVisible();
  });

  it("shows loading first", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(screen.getByText("Loading…")).toBeVisible();
  });
});

describe("NotesView filters", () => {
  it("sends the line filter", async () => {
    await renderLoaded();
    await screen.findByRole("option", { name: "Gross profit" });
    await userEvent.selectOptions(screen.getByLabelText("Filter by subject"), "line:revenue");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { code: "revenue" },
      }),
    );
  });

  it("sends the period filter only once year and period are both set", async () => {
    await renderLoaded();
    await userEvent.type(screen.getByLabelText("Filter by year"), "2024");
    expect(list).toHaveBeenLastCalledWith({ path: { ticker: "AAPL" }, query: {} });
    await userEvent.selectOptions(screen.getByLabelText("Filter by period"), "Q4");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { fiscal_year: 2024, fiscal_period: "Q4" },
      }),
    );
  });

  it("sends the line and the period together", async () => {
    await renderLoaded();
    await screen.findByRole("option", { name: "Gross profit" });
    await userEvent.selectOptions(screen.getByLabelText("Filter by subject"), "line:gross_profit");
    await userEvent.type(screen.getByLabelText("Filter by year"), "2023");
    await userEvent.selectOptions(screen.getByLabelText("Filter by period"), "FY");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { code: "gross_profit", fiscal_year: 2023, fiscal_period: "FY" },
      }),
    );
  });

  it("offers the subjects grouped: the statements, then ratios, capital and quality", async () => {
    await renderLoaded();
    await screen.findByRole("option", { name: "Accruals ratio" });
    const groups = within(screen.getByLabelText("Filter by subject"))
      .getAllByRole("group")
      .map((group) => group.getAttribute("label"));
    expect(groups).toEqual(["Income", "Balance", "Cash flow", "Ratios", "Capital", "Quality"]);
  });

  it("sends a metric filter as its kind and code", async () => {
    await renderLoaded();
    await screen.findByRole("option", { name: "Return on equity" });
    await userEvent.selectOptions(screen.getByLabelText("Filter by subject"), "ratio:roe");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { metric_kind: "ratio", metric_code: "roe" },
      }),
    );
  });

  it("sends a quality metric and a period together", async () => {
    await renderLoaded();
    await screen.findByRole("option", { name: "Accruals ratio" });
    await userEvent.selectOptions(
      screen.getByLabelText("Filter by subject"),
      "quality:accruals_ratio",
    );
    await userEvent.type(screen.getByLabelText("Filter by year"), "2024");
    await userEvent.selectOptions(screen.getByLabelText("Filter by period"), "FY");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: {
          metric_kind: "quality",
          metric_code: "accruals_ratio",
          fiscal_year: 2024,
          fiscal_period: "FY",
        },
      }),
    );
  });

  it("labels a metric note and a metric cell note, and falls back to the code", async () => {
    const metric = { canonical_code: null, metric_kind: "ratio" as const, metric_code: "roe" };
    await renderLoaded([
      note({ id: 3, ...metric, label: "Return on equity", fiscal_year: null, fiscal_period: null }),
      note({ id: 4, ...metric, label: "Return on equity" }),
      note({
        id: 5,
        canonical_code: null,
        metric_kind: "quality",
        metric_code: "custom_9",
        label: null,
        fiscal_year: 2024,
        fiscal_period: "Q1",
      }),
    ]);
    const items = screen.getAllByRole("listitem");
    expect(within(items[0]!).getByText("Return on equity")).toBeVisible();
    expect(within(items[1]!).getByText("Return on equity · FY2024")).toBeVisible();
    expect(within(items[2]!).getByText("custom_9 · Q1 FY2024")).toBeVisible();
  });
});

describe("NotesView form", () => {
  const open = () => userEvent.click(screen.getByRole("button", { name: "New note" }));
  const save = () => userEvent.click(screen.getByRole("button", { name: "Save" }));
  const optionsOf = (label: string) =>
    within(screen.getByLabelText(label))
      .getAllByRole("option")
      .map((option) => option.textContent);

  // Only Date is faked, so timers and userEvent run as usual. 22:30 local, so a UTC date would
  // already be tomorrow in most time zones east of Greenwich.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 23, 22, 30));
  });
  afterEach(() => vi.useRealTimers());

  it("starts a new note dated today and sends that date", async () => {
    await renderLoaded();
    await open();
    expect(screen.getByLabelText("Note date")).toHaveValue("2026-10-23");
    await userEvent.type(screen.getByLabelText("Note"), "Thesis");
    await save();
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: {
        body_md: "Thesis",
        canonical_code: null,
        metric_kind: null,
        metric_code: null,
        fiscal_year: null,
        fiscal_period: null,
        note_date: "2026-10-23",
      },
    });
  });

  it("sends no date when the date is cleared", async () => {
    await renderLoaded();
    await open();
    await userEvent.clear(screen.getByLabelText("Note date"));
    await userEvent.type(screen.getByLabelText("Note"), "Thesis");
    await save();
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: {
        body_md: "Thesis",
        canonical_code: null,
        metric_kind: null,
        metric_code: null,
        fiscal_year: null,
        fiscal_period: null,
      },
    });
  });

  it("offers only the company's fiscal years, newest first", async () => {
    await renderLoaded();
    await open();
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    expect(optionsOf("Fiscal year")).toEqual(["None", "2024", "2023"]);
  });

  it("offers a year only the periods that year has", async () => {
    await renderLoaded();
    await open();
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    expect(optionsOf("Period")).toEqual(["None"]);
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "2024");
    expect(optionsOf("Period")).toEqual(["None", "FY", "Q1", "Q2"]);
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "2023");
    expect(optionsOf("Period")).toEqual(["None", "FY"]);
  });

  it("drops a picked period that the new year does not have", async () => {
    await renderLoaded();
    await open();
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "2024");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "Q2");
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "2023");
    expect(screen.getByLabelText("Period")).toHaveValue("");
  });

  it("keeps a stored year the company lacks visible, so the user must change it", async () => {
    await renderLoaded([note({ id: 7, fiscal_year: 2031, fiscal_period: "FY" })]);
    await userEvent.click(screen.getByRole("button", { name: "Edit note 7" }));
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    expect(screen.getByLabelText("Fiscal year")).toHaveValue("2031");
    expect(optionsOf("Fiscal year")).toContain("2031 (no statements)");
  });

  it("creates a note linked to a cell with a date", async () => {
    await renderLoaded();
    await open();
    await within(screen.getByLabelText("Subject")).findByRole("option", { name: "Gross profit" });
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    await userEvent.type(screen.getByLabelText("Note"), "Margin up");
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "line:gross_profit");
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "2024");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "FY");
    await userEvent.clear(screen.getByLabelText("Note date"));
    await userEvent.type(screen.getByLabelText("Note date"), "2024-11-05");
    await save();
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: {
        body_md: "Margin up",
        canonical_code: "gross_profit",
        metric_kind: null,
        metric_code: null,
        fiscal_year: 2024,
        fiscal_period: "FY",
        note_date: "2024-11-05",
      },
    });
  });

  it("creates a note linked to a ratio and a period", async () => {
    await renderLoaded();
    await open();
    await within(screen.getByLabelText("Subject")).findByRole("option", {
      name: "Return on equity",
    });
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    await userEvent.type(screen.getByLabelText("Note"), "ROE up on buybacks");
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "ratio:roe");
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "2024");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "FY");
    await save();
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: {
        body_md: "ROE up on buybacks",
        canonical_code: null,
        metric_kind: "ratio",
        metric_code: "roe",
        fiscal_year: 2024,
        fiscal_period: "FY",
        note_date: "2026-10-23",
      },
    });
  });

  it("edits a metric note with its subject prefilled and can move it to a line", async () => {
    const metricNote = note({
      id: 8,
      canonical_code: null,
      metric_kind: "capital",
      metric_code: "capex",
      label: "Capital expenditures",
      fiscal_year: null,
      fiscal_period: null,
    });
    await renderLoaded([metricNote]);
    await userEvent.click(screen.getByRole("button", { name: "Edit note 8" }));
    await within(screen.getByLabelText("Subject")).findByRole("option", { name: "Gross profit" });
    expect(screen.getByLabelText("Subject")).toHaveValue("capital:capex");
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "line:gross_profit");
    await save();
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", note_id: 8 },
      body: expect.objectContaining({
        canonical_code: "gross_profit",
        metric_kind: null,
        metric_code: null,
      }),
    });
  });

  it("keeps a stored subject that is no longer listed, so it is not silently dropped", async () => {
    await renderLoaded([
      note({
        id: 9,
        canonical_code: null,
        metric_kind: "quality",
        metric_code: "custom_9",
        label: "Gone rule",
        fiscal_year: null,
        fiscal_period: null,
      }),
    ]);
    await userEvent.click(screen.getByRole("button", { name: "Edit note 9" }));
    await within(screen.getByLabelText("Subject")).findByRole("option", { name: "Gross profit" });
    expect(screen.getByLabelText("Subject")).toHaveValue("quality:custom_9");
    expect(optionsOf("Subject")).toContain("Gone rule");
  });

  it("refuses a blank note without a request", async () => {
    await renderLoaded();
    await open();
    await save();
    expect(await screen.findByText("Enter a note")).toBeVisible();
    expect(create).not.toHaveBeenCalled();
  });

  it("refuses a year without a period without a request", async () => {
    await renderLoaded();
    await open();
    await userEvent.type(screen.getByLabelText("Note"), "x");
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "2024");
    await save();
    expect(await screen.findByText("Pick both a fiscal year and a period")).toBeVisible();
    expect(create).not.toHaveBeenCalled();
  });

  it("shows the API's reason when saving fails", async () => {
    create.mockResolvedValue(errorResult(422, { detail: "body too long" }) as never);
    await renderLoaded();
    await open();
    await userEvent.type(screen.getByLabelText("Note"), "x");
    await save();
    expect(await screen.findByText("body too long")).toBeVisible();
  });

  it("edits a note with its body, link and date prefilled", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Edit note 2" }));
    await within(screen.getByLabelText("Subject")).findByRole("option", { name: "Gross profit" });
    expect(screen.getByLabelText("Note")).toHaveValue("# Thesis\n\nServices **mix** is rising.");
    expect(screen.getByLabelText("Subject")).toHaveValue("line:revenue");
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    expect(screen.getByLabelText("Fiscal year")).toHaveValue("2024");
    expect(screen.getByLabelText("Period")).toHaveValue("FY");
    expect(screen.getByLabelText("Note date")).toHaveValue("2024-11-02"); // not today
    await userEvent.clear(screen.getByLabelText("Note"));
    await userEvent.type(screen.getByLabelText("Note"), "Changed");
    await save();
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", note_id: 2 },
      body: {
        body_md: "Changed",
        canonical_code: "revenue",
        metric_kind: null,
        metric_code: null,
        fiscal_year: 2024,
        fiscal_period: "FY",
        note_date: "2024-11-02",
      },
    });
  });

  it("can unlink a note when editing", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Edit note 2" }));
    await within(screen.getByLabelText("Subject")).findByRole("option", { name: "Gross profit" });
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "");
    await within(screen.getByLabelText("Fiscal year")).findByRole("option", { name: "2024" });
    await userEvent.selectOptions(screen.getByLabelText("Fiscal year"), "");
    await save();
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", note_id: 2 },
      body: expect.objectContaining({
        canonical_code: null,
        metric_kind: null,
        metric_code: null,
        fiscal_year: null,
        fiscal_period: null,
      }),
    });
  });

  it("closes the form on Cancel without a request", async () => {
    await renderLoaded();
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Note")).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });
});

describe("NotesView delete", () => {
  it("deletes only after confirmation", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Delete note 2" }));
    expect(remove).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", note_id: 2 } });
  });

  it("keeps the note when cancelled", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Delete note 2" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(remove).not.toHaveBeenCalled();
  });

  it("shows the API's reason when the delete fails", async () => {
    remove.mockResolvedValue(errorResult(404, { detail: "Note not found" }) as never);
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Delete note 2" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Note not found")).toBeVisible();
  });
});
