import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addCompanyApiV1CompaniesPost,
  addManualCompanyApiV1CompaniesManualPost,
  getCompaniesApiV1CompaniesGet,
  removeCompanyApiV1CompaniesTickerDelete,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { companyItem } from "@/test/companies";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

import { Companies } from "./Companies";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
  addCompanyApiV1CompaniesPost: vi.fn(),
  addManualCompanyApiV1CompaniesManualPost: vi.fn(),
  removeCompanyApiV1CompaniesTickerDelete: vi.fn(),
}));

function renderCompanies() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Companies />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(okResult([companyItem()]) as never);
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

describe("removing a company", () => {
  it("asks for confirmation, then removes", async () => {
    vi.mocked(removeCompanyApiV1CompaniesTickerDelete).mockResolvedValue(
      okResult(undefined, 204) as never,
    );
    renderCompanies();

    await userEvent.click(await screen.findByRole("button", { name: "Remove AAPL" }));
    expect(removeCompanyApiV1CompaniesTickerDelete).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Remove AAPL?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    expect(removeCompanyApiV1CompaniesTickerDelete).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
    });
  });

  it("keeps the company when the confirmation is cancelled", async () => {
    renderCompanies();

    await userEvent.click(await screen.findByRole("button", { name: "Remove AAPL" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );

    expect(removeCompanyApiV1CompaniesTickerDelete).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "AAPL" })).toBeInTheDocument();
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
