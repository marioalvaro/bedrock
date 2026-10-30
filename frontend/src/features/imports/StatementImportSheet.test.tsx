import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteImportApiV1CompaniesTickerImportsImportIdDelete,
  importStatementsApiV1CompaniesTickerImportsPost,
  listImportsApiV1CompaniesTickerImportsGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { cellChange, preview, statementImport } from "@/test/imports";
import { errorResult, okResult } from "@/test/responses";

import { StatementImportSheet } from "./StatementImportSheet";

vi.mock("@/api/generated/sdk.gen", () => ({
  listImportsApiV1CompaniesTickerImportsGet: vi.fn(),
  importStatementsApiV1CompaniesTickerImportsPost: vi.fn(),
  deleteImportApiV1CompaniesTickerImportsImportIdDelete: vi.fn(),
}));

const list = vi.mocked(listImportsApiV1CompaniesTickerImportsGet);
const post = vi.mocked(importStatementsApiV1CompaniesTickerImportsPost);
const remove = vi.mocked(deleteImportApiV1CompaniesTickerImportsImportIdDelete);

function renderSheet() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <StatementImportSheet ticker="AAPL" open scale="M" onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose, queryClient };
}

async function choose(name = "aapl-fill.xlsx") {
  await userEvent.upload(screen.getByLabelText("File"), new File(["x"], name));
}

async function previewFile(result = preview()) {
  post.mockResolvedValue(okResult(result) as never);
  await choose();
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  await screen.findByText(/would be filled/);
}

beforeEach(() => {
  list.mockResolvedValue(okResult([]) as never);
});
afterEach(() => vi.clearAllMocks());

describe("template download", () => {
  it("tells the user the template needs one fiscal year end and lists 20 years", () => {
    renderSheet();
    expect(screen.getByText(/fiscal_year_end/)).toHaveTextContent("20 fiscal years");
  });

  const link = () => screen.getByRole("link", { name: "Download template" });

  it("links the blank xlsx in millions by default", () => {
    renderSheet();
    expect(link()).toHaveAttribute(
      "href",
      "/api/v1/companies/AAPL/import-template?format=xlsx&prefill=false&scale=millions",
    );
  });

  it("follows the format, the prefill and the scale", async () => {
    renderSheet();
    await userEvent.selectOptions(screen.getByLabelText("Format"), "csv");
    await userEvent.click(screen.getByLabelText("Prefill with current values"));
    await userEvent.selectOptions(screen.getByLabelText("Scale"), "units");
    expect(link()).toHaveAttribute(
      "href",
      "/api/v1/companies/AAPL/import-template?format=csv&prefill=true&scale=units",
    );
  });
});

describe("preview", () => {
  it("asks for a file first", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a file first");
    expect(post).not.toHaveBeenCalled();
  });

  it("sends a dry run with the file and the chosen scale", async () => {
    renderSheet();
    await userEvent.selectOptions(screen.getByLabelText("Scale"), "thousands");
    await previewFile();
    const [call] = post.mock.calls[0]!;
    expect(call.path).toEqual({ ticker: "AAPL" });
    expect(call.body).toMatchObject({ dry_run: true, scale: "thousands" });
    expect((call.body.file as File).name).toBe("aapl-fill.xlsx");
  });

  it("counts the fills, the ignored cells and the unchanged ones", async () => {
    renderSheet();
    await previewFile(
      preview({
        fills: [cellChange(), cellChange({ code: "sga", label: "SG&A", period_key: "FY2009" })],
        unchanged: 7,
        ignored: [
          {
            statement: "IS",
            code: "revenue",
            label: "Revenue",
            period_key: "FY2024",
            existing_value: "391035000000",
            imported_value: "400000000000",
            reason: "sec",
            unit: "USD",
          },
        ],
      }),
    );
    expect(screen.getByText("2 cells would be filled")).toBeInTheDocument();
    expect(screen.getByText("1 ignored")).toBeInTheDocument();
    expect(screen.getByText("7 unchanged")).toBeInTheDocument();
  });

  it("lists a fill with its value in the page scale", async () => {
    renderSheet();
    await previewFile();
    const fills = screen.getByRole("table", { name: "Cells to fill" });
    const row = within(fills).getByText("Interest expense").closest("tr")!;
    expect(row).toHaveTextContent("IS");
    expect(row).toHaveTextContent("FY2008");
    expect(row).toHaveTextContent("1,500");
  });

  it("lists an ignored cell with both values and why", async () => {
    renderSheet();
    await previewFile(
      preview({
        ignored: [
          {
            statement: "IS",
            code: "revenue",
            label: "Revenue",
            period_key: "FY2024",
            existing_value: "391035000000",
            imported_value: "400000000000",
            reason: "sec",
            unit: "USD",
          },
          {
            statement: "IS",
            code: "gross_profit",
            label: "Gross profit",
            period_key: "FY2024",
            existing_value: "180683000000",
            imported_value: "1000000",
            reason: "derived",
            unit: "USD",
          },
        ],
      }),
    );
    const table = screen.getByRole("table", { name: "Ignored cells" });
    const sec = within(table).getByText("Revenue").closest("tr")!;
    expect(sec).toHaveTextContent("391,035");
    expect(sec).toHaveTextContent("400,000");
    expect(sec).toHaveTextContent("SEC has a value");
    const derived = within(table).getByText("Gross profit").closest("tr")!;
    expect(derived).toHaveTextContent("A formula gives another value");
  });

  it("shows the custom lines, the built parents and the warnings", async () => {
    renderSheet();
    await previewFile(
      preview({
        lines: [
          {
            statement: "IS",
            code: "custom:products",
            label: "Products",
            parent: "cost_of_revenue",
            parent_label: "Cost of revenue",
          },
        ],
        built: [
          {
            statement: "IS",
            code: "cost_of_revenue",
            label: "Cost of revenue",
            period_key: "FY2008",
            unit: "USD",
            value: "2000000000",
          },
        ],
        warnings: [
          { sheet: "BS", row: null, column: null, message: "Balance sheet does not foot" },
        ],
      }),
    );
    expect(screen.getByText(/Products/)).toHaveTextContent("under Cost of revenue");
    const built = screen.getByRole("table", { name: "Parents built from custom lines" });
    expect(built).toHaveTextContent("Cost of revenue");
    expect(built).toHaveTextContent("2,000");
    expect(screen.getByText(/Balance sheet does not foot/)).toHaveTextContent("BS");
  });

  it("lists every refused error with its sheet, row and column", async () => {
    renderSheet();
    post.mockResolvedValue(
      errorResult(422, {
        detail: "2 errors",
        errors: [
          { sheet: "IS", row: 12, column: "G", message: "not a number" },
          { sheet: null, row: null, column: null, message: "unknown sheet 'Foo'" },
        ],
      }) as never,
    );
    await choose();
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("IS, row 12, column G: not a number")).toBeInTheDocument();
    expect(screen.getByText("unknown sheet 'Foo'")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Import \d/ })).not.toBeInTheDocument();
  });

  it("shows the reason of another failure", async () => {
    renderSheet();
    post.mockResolvedValue(errorResult(413, { detail: "File too large" }) as never);
    await choose();
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("File too large");
  });

  it("drops the preview when another file is chosen", async () => {
    renderSheet();
    await previewFile();
    await choose("other.xlsx");
    expect(screen.queryByText(/would be filled/)).not.toBeInTheDocument();
  });
});

describe("confirm", () => {
  it("is offered only after a preview", async () => {
    renderSheet();
    expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();
    await previewFile();
    expect(screen.getByRole("button", { name: "Import 1 cell" })).toBeEnabled();
  });

  it("sends the real run with the same file and reports what was stored", async () => {
    renderSheet();
    await previewFile();
    post.mockResolvedValue(okResult(preview({ dry_run: false, import_id: 5 })) as never);
    await userEvent.click(screen.getByRole("button", { name: "Import 1 cell" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1]![0].body).toMatchObject({ dry_run: false });
    expect((post.mock.calls[1]![0].body.file as File).name).toBe("aapl-fill.xlsx");
    expect(await screen.findByText("Imported 1 cell.")).toBeInTheDocument();
    expect(screen.queryByText(/would be filled/)).not.toBeInTheDocument();
  });

  it("is not offered when the file would change nothing", async () => {
    renderSheet();
    await previewFile(preview({ fills: [], unchanged: 40 }));
    expect(screen.getByText("Nothing to import: the file changes no cell.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Import \d/ })).not.toBeInTheDocument();
  });

  it("is offered for a file that only adds custom lines", async () => {
    renderSheet();
    await previewFile(
      preview({
        fills: [],
        lines: [
          {
            statement: "IS",
            code: "custom:products",
            label: "Products",
            parent: "cost_of_revenue",
            parent_label: "Cost of revenue",
          },
        ],
      }),
    );
    expect(screen.getByRole("button", { name: "Import 0 cells" })).toBeEnabled();
  });

  it("shows the reason when the real run fails", async () => {
    renderSheet();
    await previewFile();
    post.mockResolvedValue(errorResult(404, { detail: "Unknown ticker" }) as never);
    await userEvent.click(screen.getByRole("button", { name: "Import 1 cell" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown ticker");
  });
});

describe("history", () => {
  it("lists the imports, newest first as the API sends them", async () => {
    list.mockResolvedValue(
      okResult([
        statementImport({ id: 4, filename: "second.csv", format: "csv", cells: 3 }),
        statementImport({ id: 3, filename: "first.xlsx", cells: 12 }),
      ]) as never,
    );
    renderSheet();
    const history = await screen.findByRole("table", { name: "Import history" });
    const rows = within(history).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("second.csv");
    expect(rows[0]).toHaveTextContent("3 cells");
    expect(rows[1]).toHaveTextContent("first.xlsx");
    expect(rows[1]).toHaveTextContent("2026-10-26");
  });

  it("says when there are none", async () => {
    renderSheet();
    expect(await screen.findByText("No imports yet.")).toBeInTheDocument();
  });

  it("shows Loading… while the history is pending", async () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderSheet();
    expect(await screen.findByText("Loading…")).toBeInTheDocument();
  });

  it("shows an error when the import history cannot load", async () => {
    list.mockResolvedValue(errorResult(500) as never);
    renderSheet();
    expect(await screen.findByText("Could not load the imports.")).toBeInTheDocument();
    expect(screen.queryByText("No imports yet.")).not.toBeInTheDocument();
  });

  it("asks before deleting and then deletes that import", async () => {
    list.mockResolvedValue(okResult([statementImport({ id: 3, filename: "first.xlsx" })]) as never);
    remove.mockResolvedValue(okResult(undefined, 204) as never);
    renderSheet();
    await userEvent.click(await screen.findByRole("button", { name: "Delete first.xlsx" }));
    expect(remove).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Delete first.xlsx?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", import_id: 3 } }),
    );
  });

  it("keeps the import when the dialog is cancelled", async () => {
    list.mockResolvedValue(okResult([statementImport({ filename: "first.xlsx" })]) as never);
    renderSheet();
    await userEvent.click(await screen.findByRole("button", { name: "Delete first.xlsx" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(remove).not.toHaveBeenCalled();
  });

  it("shows the reason when the delete fails", async () => {
    list.mockResolvedValue(okResult([statementImport({ filename: "first.xlsx" })]) as never);
    remove.mockResolvedValue(errorResult(404, { detail: "Unknown import" }) as never);
    renderSheet();
    await userEvent.click(await screen.findByRole("button", { name: "Delete first.xlsx" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByText("Unknown import")).toBeInTheDocument();
  });
});
