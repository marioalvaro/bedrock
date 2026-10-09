import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addCompanyApiV1CompaniesPost,
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
