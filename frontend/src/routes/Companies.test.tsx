import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addCompanyApiV1CompaniesPost,
  addManualCompanyApiV1CompaniesManualPost,
  archiveCompanyApiV1CompaniesTickerArchivePost,
  deletionImpactApiV1CompaniesTickerDeletionImpactGet,
  getCompaniesApiV1CompaniesGet,
  removeCompanyApiV1CompaniesTickerDelete,
  restoreCompanyApiV1CompaniesTickerRestorePost,
} from "@/api/generated/sdk.gen";
import type { CompanyListItem } from "@/api/generated/types.gen";
import { createQueryClient } from "@/lib/query-client";
import { companyItem, deletionImpact } from "@/test/companies";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

import { Companies } from "./Companies";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
  addCompanyApiV1CompaniesPost: vi.fn(),
  addManualCompanyApiV1CompaniesManualPost: vi.fn(),
  removeCompanyApiV1CompaniesTickerDelete: vi.fn(),
  archiveCompanyApiV1CompaniesTickerArchivePost: vi.fn(),
  restoreCompanyApiV1CompaniesTickerRestorePost: vi.fn(),
  deletionImpactApiV1CompaniesTickerDeletionImpactGet: vi.fn(),
}));

const archive = vi.mocked(archiveCompanyApiV1CompaniesTickerArchivePost);
const restore = vi.mocked(restoreCompanyApiV1CompaniesTickerRestorePost);
const impact = vi.mocked(deletionImpactApiV1CompaniesTickerDeletionImpactGet);
const remove = vi.mocked(removeCompanyApiV1CompaniesTickerDelete);

/** GET /companies answers the followed list, and with `archived=true` the archived one. */
function lists(followed: CompanyListItem[], archived: CompanyListItem[] = []) {
  vi.mocked(getCompaniesApiV1CompaniesGet).mockImplementation(
    (options) => Promise.resolve(okResult(options?.query?.archived ? archived : followed)) as never,
  );
}

const cost = companyItem({
  id: 3,
  ticker: "COST",
  name: "Costco Wholesale Corporation",
  archived_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
});

function renderCompanies() {
  const queryClient = createQueryClient();
  // The app retries a 5xx with backoff; the error states are read at once here.
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Companies />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  lists([companyItem()]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("Companies list", () => {
  it("shows each company's key stats", async () => {
    renderCompanies();

    const row = (await screen.findByRole("link", { name: "AAPL" })).closest("tr") as HTMLElement;
    expect(within(row).getByText("Apple Inc.")).toBeInTheDocument();
    expect(within(row).getByText("231.40")).toBeInTheDocument();
    expect(within(row).getByText("3.5T")).toBeInTheDocument();
    expect(within(row).getByText("34.2x")).toBeInTheDocument();
    expect(within(row).getByText("5.1%")).toBeInTheDocument();
    expect(within(row).getByText("2h ago")).toBeInTheDocument();
  });

  it("shows a dash for a stat the API could not compute", async () => {
    renderCompanies();

    const row = (await screen.findByRole("link", { name: "AAPL" })).closest("tr") as HTMLElement;
    // EV/EBITDA is null for AAPL in M1.
    expect(within(row).getAllByText("—")).toHaveLength(1);
  });

  it("marks a company with a filing not loaded yet under its name (FR-DATA-23)", async () => {
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(
      okResult([
        companyItem({
          new_filings: [{ form: "10-K", filed_at: "2026-10-31", period_end: "2026-09-26" }],
        }),
      ]) as never,
    );
    renderCompanies();

    const row = (await screen.findByRole("link", { name: "AAPL" })).closest("tr") as HTMLElement;
    const nameCell = within(row).getByText("Apple Inc.").closest("td") as HTMLElement;
    expect(within(nameCell).getByText("10-K filed Oct 31")).toBeInTheDocument();
  });

  it("links a company to its page", async () => {
    renderCompanies();

    expect(await screen.findByRole("link", { name: "AAPL" })).toHaveAttribute("href", "/c/AAPL");
  });

  it("shows the empty state", async () => {
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(okResult([]) as never);
    renderCompanies();

    expect(await screen.findByText("No companies yet. Add a ticker above.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Ticker" })).toBeInTheDocument();
  });
});

describe("adding a company", () => {
  it("sends the ticker upper-cased and clears the box", async () => {
    vi.mocked(addCompanyApiV1CompaniesPost).mockResolvedValue(
      okResult(companyItem({ ticker: "MSFT", name: "Microsoft" }), 201) as never,
    );
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });

    await userEvent.type(screen.getByRole("textbox", { name: "Ticker" }), " msft ");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(addCompanyApiV1CompaniesPost).toHaveBeenCalledWith({ body: { ticker: "MSFT" } });
    expect(screen.getByRole("textbox", { name: "Ticker" })).toHaveValue("");
  });

  it("refetches the list after adding", async () => {
    vi.mocked(addCompanyApiV1CompaniesPost).mockResolvedValue(
      okResult(companyItem(), 201) as never,
    );
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(
      okResult([companyItem(), companyItem({ id: 2, ticker: "MSFT", name: "Microsoft" })]) as never,
    );

    await userEvent.type(screen.getByRole("textbox", { name: "Ticker" }), "MSFT{Enter}");

    expect(await screen.findByRole("link", { name: "MSFT" })).toBeInTheDocument();
  });

  it.each([
    [404, "Unknown ticker ZZZZ."],
    [409, "AAPL is already followed."],
    [503, "SEC_USER_AGENT is not configured."],
    [502, "SEC EDGAR is unavailable."],
  ])("shows the API's reason for a %s", async (status, detail) => {
    vi.mocked(addCompanyApiV1CompaniesPost).mockResolvedValue(
      errorResult(status, { detail }) as never,
    );
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });

    await userEvent.type(screen.getByRole("textbox", { name: "Ticker" }), "AAPL{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
  });

  it("falls back to a generic message when no response arrived", async () => {
    vi.mocked(addCompanyApiV1CompaniesPost).mockResolvedValue(networkErrorResult() as never);
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });

    await userEvent.type(screen.getByRole("textbox", { name: "Ticker" }), "AAPL{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not add the company.");
  });

  it("does not submit an empty ticker", async () => {
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });

    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(addCompanyApiV1CompaniesPost).not.toHaveBeenCalled();
  });
});

describe("archiving a company (FR-WS-07)", () => {
  it("archives from the row with no dialog, and the row leaves the list", async () => {
    archive.mockImplementation(() => {
      lists([], [cost]);
      return Promise.resolve(okResult(undefined, 204)) as never;
    });
    lists([companyItem(), cost]);
    renderCompanies();

    await userEvent.click(await screen.findByRole("button", { name: "Archive COST" }));

    expect(archive).toHaveBeenCalledWith({ path: { ticker: "COST" } });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "COST" })).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Archived COST.")).toHaveClass("text-muted-foreground");
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(remove).not.toHaveBeenCalled();
  });

  it("undoes an archive by restoring the company", async () => {
    archive.mockResolvedValue(okResult(undefined, 204) as never);
    restore.mockResolvedValue(okResult(undefined, 204) as never);
    renderCompanies();
    await userEvent.click(await screen.findByRole("button", { name: "Archive AAPL" }));

    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));

    expect(restore).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    await waitFor(() => expect(screen.queryByText("Archived AAPL.")).not.toBeInTheDocument());
  });

  it.each([
    ["restored", "Restore COST"],
    ["deleted", "Delete COST permanently…"],
  ])("drops the Undo line once the company is %s from the archived list", async (_name, button) => {
    lists([companyItem(), cost]);
    archive.mockImplementation(() => {
      lists([companyItem()], [cost]);
      return Promise.resolve(okResult(undefined, 204)) as never;
    });
    restore.mockImplementation(() => {
      lists([companyItem(), cost], []);
      return Promise.resolve(okResult(undefined, 204)) as never;
    });
    remove.mockImplementation(() => {
      lists([companyItem()], []);
      return Promise.resolve(okResult(undefined, 204)) as never;
    });
    impact.mockResolvedValue(okResult(deletionImpact()) as never);
    renderCompanies();
    await userEvent.click(await screen.findByRole("button", { name: "Archive COST" }));
    await userEvent.click(await screen.findByRole("button", { name: "Archived (1)" }));

    await userEvent.click(screen.getByRole("button", { name: button }));
    const dialog = screen.queryByRole("alertdialog");
    if (dialog) {
      await within(dialog).findByText(/12 filings/);
      await userEvent.type(within(dialog).getByRole("textbox"), "COST");
      await userEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));
    }

    await waitFor(() => expect(screen.queryByText("Archived COST.")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it.each([
    ["the API's reason", errorResult(404, { detail: "Company not found" }), "Company not found"],
    ["a fallback with no response", networkErrorResult(), "Could not archive AAPL."],
  ])("shows %s when archiving fails", async (_name, result, message) => {
    archive.mockResolvedValue(result as never);
    renderCompanies();

    await userEvent.click(await screen.findByRole("button", { name: "Archive AAPL" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText("Archived AAPL.")).not.toBeInTheDocument();
  });
});

describe("the archived list (FR-WS-07)", () => {
  async function openArchived() {
    const toggle = await screen.findByRole("button", { name: "Archived (1)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    return screen.getByRole("table", { name: "Archived companies" });
  }

  it("is collapsed under the table, with its count", async () => {
    lists([companyItem()], [cost]);
    renderCompanies();

    await screen.findByRole("button", { name: "Archived (1)" });

    expect(screen.queryByRole("table", { name: "Archived companies" })).not.toBeInTheDocument();
    expect(getCompaniesApiV1CompaniesGet).toHaveBeenCalledWith({ query: { archived: true } });
  });

  it("is not offered when nothing is archived", async () => {
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });

    expect(screen.queryByRole("button", { name: /^Archived/ })).not.toBeInTheDocument();
  });

  it("lists each archived company with when it was archived", async () => {
    lists([companyItem()], [cost]);
    renderCompanies();

    const table = await openArchived();

    const row = within(table).getByRole("link", { name: "COST" }).closest("tr") as HTMLElement;
    expect(within(row).getByText("Costco Wholesale Corporation")).toBeInTheDocument();
    expect(within(row).getByText("2d ago")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Restore COST" })).toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "Delete COST permanently…" }),
    ).toBeInTheDocument();
  });

  it("restores a company to the followed list", async () => {
    lists([companyItem()], [cost]);
    restore.mockImplementation(() => {
      lists([companyItem(), cost], []);
      return Promise.resolve(okResult(undefined, 204)) as never;
    });
    renderCompanies();
    const table = await openArchived();

    await userEvent.click(within(table).getByRole("button", { name: "Restore COST" }));

    expect(restore).toHaveBeenCalledWith({ path: { ticker: "COST" } });
    expect(await screen.findByRole("button", { name: "Archive COST" })).toBeInTheDocument();
  });

  it("says so when the archived list fails to load", async () => {
    vi.mocked(getCompaniesApiV1CompaniesGet).mockImplementation(
      (options) =>
        Promise.resolve(
          options?.query?.archived ? errorResult(500) : okResult([companyItem()]),
        ) as never,
    );
    renderCompanies();

    expect(await screen.findByText("Could not load the archived companies.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AAPL" })).toBeInTheDocument();
  });
});

describe("deleting a company permanently (FR-WS-07)", () => {
  async function openDialog() {
    lists([companyItem()], [cost]);
    renderCompanies();
    await userEvent.click(await screen.findByRole("button", { name: "Archived (1)" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete COST permanently…" }));
    return screen.findByRole("alertdialog");
  }

  beforeEach(() => {
    impact.mockResolvedValue(okResult(deletionImpact()) as never);
  });

  it("names every count that is not zero and says it cannot be undone", async () => {
    const dialog = await openDialog();

    expect(dialog).toHaveTextContent("Delete COST permanently?");
    expect(
      await within(dialog).findByText(
        "12 filings, 48,210 facts, 7 notes, 3 scenarios, 5 snapshots, 2 guidance items, 1 checkpoint",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("This cannot be undone.")).toBeInTheDocument();
    expect(impact).toHaveBeenCalledWith({ path: { ticker: "COST" } });
  });

  it("uses the singular for one of a kind", async () => {
    impact.mockResolvedValue(
      okResult(
        deletionImpact({
          filings: 1,
          facts: 1,
          notes: 0,
          scenarios: 0,
          snapshots: 0,
          guidance: 1,
          checkpoints: 0,
          comps_sets: 1,
          imports: 1,
          adjustments: 1,
        }),
      ) as never,
    );
    const dialog = await openDialog();

    expect(
      await within(dialog).findByText(
        "1 filing, 1 fact, 1 guidance item, 1 adjustment, 1 comps set, 1 import",
      ),
    ).toBeInTheDocument();
  });

  it("says so when nothing else is stored", async () => {
    impact.mockResolvedValue(
      okResult(
        deletionImpact({
          filings: 0,
          facts: 0,
          notes: 0,
          scenarios: 0,
          snapshots: 0,
          guidance: 0,
          checkpoints: 0,
        }),
      ) as never,
    );
    const dialog = await openDialog();

    expect(await within(dialog).findByText("Nothing else is stored for COST.")).toBeInTheDocument();
  });

  it.each([
    ["while the counts load", () => new Promise(() => {}), "Loading…"],
    [
      "when the counts fail",
      () => Promise.resolve(errorResult(500)),
      "Could not load what would be deleted.",
    ],
  ])("says so %s", async (_name, answer, text) => {
    impact.mockImplementation(answer as never);
    const dialog = await openDialog();

    expect(await within(dialog).findByText(text)).toBeInTheDocument();
  });

  it.each([
    ["load", () => new Promise(() => {})],
    ["fail", () => Promise.resolve(errorResult(500))],
  ])(
    "keeps the delete button disabled while the counts %s, the ticker typed",
    async (_name, answer) => {
      impact.mockImplementation(answer as never);
      const dialog = await openDialog();

      await userEvent.type(
        within(dialog).getByRole("textbox", { name: "Type COST to confirm" }),
        "COST",
      );

      expect(within(dialog).getByRole("button", { name: "Delete permanently" })).toBeDisabled();
    },
  );

  it("enables the delete button only once the ticker is typed exactly", async () => {
    const dialog = await openDialog();
    const button = within(dialog).getByRole("button", { name: "Delete permanently" });
    const input = within(dialog).getByRole("textbox", { name: "Type COST to confirm" });
    expect(button).toBeDisabled();

    await userEvent.type(input, "cost");
    expect(button).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "COS");
    expect(button).toBeDisabled();
    await userEvent.type(input, "T");
    expect(button).toBeEnabled();
  });

  it("deletes the company once confirmed", async () => {
    remove.mockImplementation(() => {
      lists([companyItem()], []);
      return Promise.resolve(okResult(undefined, 204)) as never;
    });
    const dialog = await openDialog();

    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Type COST to confirm" }),
      "COST",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));

    expect(remove).toHaveBeenCalledWith({ path: { ticker: "COST" } });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^Archived/ })).not.toBeInTheDocument(),
    );
  });

  it("shows the API's detail when the delete is refused", async () => {
    remove.mockResolvedValue(
      errorResult(409, { detail: "Archive COST before deleting it permanently." }) as never,
    );
    const dialog = await openDialog();

    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Type COST to confirm" }),
      "COST",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Archive COST before deleting it permanently.",
    );
  });

  it("keeps the company when cancelled, and starts the confirmation over next time", async () => {
    const dialog = await openDialog();
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Type COST to confirm" }),
      "COST",
    );

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete COST permanently…" }));

    const again = await screen.findByRole("alertdialog");
    expect(within(again).getByRole("textbox", { name: "Type COST to confirm" })).toHaveValue("");
    expect(remove).not.toHaveBeenCalled();
  });
});

describe("adding a manual company", () => {
  const addManual = vi.mocked(addManualCompanyApiV1CompaniesManualPost);

  async function openForm() {
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });
    await userEvent.click(screen.getByRole("button", { name: "Add manual company" }));
    return screen.getByRole("form", { name: "Add manual company" });
  }

  async function fill(form: HTMLElement, ticker: string, name: string, sic = "") {
    await userEvent.type(within(form).getByLabelText("Ticker"), ticker);
    await userEvent.type(within(form).getByLabelText("Name"), name);
    if (sic) await userEvent.type(within(form).getByLabelText("SIC (optional)"), sic);
  }

  it("keeps the form closed until asked", async () => {
    renderCompanies();
    await screen.findByRole("link", { name: "AAPL" });
    expect(screen.queryByRole("form", { name: "Add manual company" })).not.toBeInTheDocument();
  });

  it("sends the company with its fiscal year end month and closes the form", async () => {
    addManual.mockResolvedValue(
      okResult(
        companyItem({ ticker: "ACME", name: "Acme Corp", source: "manual", cik: null }),
        201,
      ) as never,
    );
    const form = await openForm();
    await fill(form, " acme ", " Acme Corp ", "3571");
    await userEvent.selectOptions(within(form).getByLabelText("Fiscal year ends"), "6");
    await userEvent.click(within(form).getByRole("button", { name: "Create" }));

    expect(addManual).toHaveBeenCalledWith({
      body: { ticker: "ACME", name: "Acme Corp", fiscal_year_end_month: 6, sic: "3571" },
    });
    await waitFor(() =>
      expect(screen.queryByRole("form", { name: "Add manual company" })).not.toBeInTheDocument(),
    );
  });

  it("defaults to December and leaves the SIC out when blank", async () => {
    addManual.mockResolvedValue(okResult(companyItem({ ticker: "ACME" }), 201) as never);
    const form = await openForm();
    await fill(form, "ACME", "Acme Corp");
    await userEvent.click(within(form).getByRole("button", { name: "Create" }));
    expect(addManual).toHaveBeenCalledWith({
      body: { ticker: "ACME", name: "Acme Corp", fiscal_year_end_month: 12 },
    });
  });

  it.each([
    ["", "Acme Corp", "", "Enter a ticker"],
    ["ACME", "  ", "", "Enter a name"],
    ["ACME", "Acme Corp", "35", "SIC must be 4 digits"],
  ])("refuses %j / %j / %j with %j and sends nothing", async (ticker, name, sic, message) => {
    const form = await openForm();
    if (ticker) await userEvent.type(within(form).getByLabelText("Ticker"), ticker);
    await userEvent.type(within(form).getByLabelText("Name"), name || " ");
    if (sic) await userEvent.type(within(form).getByLabelText("SIC (optional)"), sic);
    await userEvent.click(within(form).getByRole("button", { name: "Create" }));
    expect(within(form).getByRole("alert")).toHaveTextContent(message);
    expect(addManual).not.toHaveBeenCalled();
  });

  it("shows the API's reason when the ticker is already followed", async () => {
    addManual.mockResolvedValue(errorResult(409, { detail: "AAPL is already followed." }) as never);
    const form = await openForm();
    await fill(form, "AAPL", "Apple");
    await userEvent.click(within(form).getByRole("button", { name: "Create" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("AAPL is already followed.");
    expect(screen.getByRole("form", { name: "Add manual company" })).toBeInTheDocument();
  });

  it("refetches the list and marks the manual company", async () => {
    addManual.mockResolvedValue(okResult(companyItem({ ticker: "ACME" }), 201) as never);
    const form = await openForm();
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(
      okResult([
        companyItem(),
        companyItem({ id: 2, ticker: "ACME", name: "Acme Corp", source: "manual", cik: null }),
      ]) as never,
    );
    await fill(form, "ACME", "Acme Corp");
    await userEvent.click(within(form).getByRole("button", { name: "Create" }));
    const row = (await screen.findByRole("link", { name: "ACME" })).closest("tr") as HTMLElement;
    expect(within(row).getByText("manual")).toBeInTheDocument();
    const sec = screen.getByRole("link", { name: "AAPL" }).closest("tr") as HTMLElement;
    expect(within(sec).queryByText("manual")).not.toBeInTheDocument();
  });

  it("cancels without sending", async () => {
    const form = await openForm();
    await userEvent.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("form", { name: "Add manual company" })).not.toBeInTheDocument();
    expect(addManual).not.toHaveBeenCalled();
  });
});
