import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getCompaniesApiV1CompaniesGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { companyItem } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import { CompanySwitcher } from "./CompanySwitcher";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
}));

const listCompanies = vi.mocked(getCompaniesApiV1CompaniesGet);

const COMPANIES = [
  companyItem(),
  companyItem({ id: 2, ticker: "MSFT", name: "Microsoft Corporation" }),
  companyItem({ id: 3, ticker: "COST", name: "Costco Wholesale Corporation" }),
];

beforeEach(() => {
  listCompanies.mockResolvedValue(okResult(COMPANIES) as never);
});

afterEach(() => {
  vi.clearAllMocks();
});

function Where() {
  const { pathname, search } = useLocation();
  return <output data-testid="where">{pathname + search}</output>;
}

function renderAt(path: string, slug: string) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="c/:ticker/:tab?"
            element={
              <>
                <CompanySwitcher ticker="AAPL" slug={slug} />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function open() {
  await userEvent.click(screen.getByRole("button", { name: "Switch company" }));
  return screen.findByRole("dialog", { name: "Switch company" });
}

const optionNames = (popover: HTMLElement) =>
  within(popover)
    .queryAllByRole("option")
    .map((option) => within(option).getByTestId("option-ticker").textContent);

describe("CompanySwitcher (FR-WS-06)", () => {
  it("is a button holding the ticker heading", () => {
    renderAt("/c/AAPL", "overview");

    const button = screen.getByRole("button", { name: "Switch company" });
    expect(within(button).getByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(listCompanies).not.toHaveBeenCalled();
  });

  it("lists the followed companies with the current one marked", async () => {
    renderAt("/c/AAPL", "overview");

    const popover = await open();

    expect(await within(popover).findAllByRole("option")).toHaveLength(3);
    expect(optionNames(popover)).toEqual(["AAPL", "MSFT", "COST"]);
    const current = within(popover).getByRole("option", { name: /AAPL/ });
    expect(within(current).getByText("(current)")).toBeInTheDocument();
    const other = within(popover).getByRole("option", { name: /MSFT/ });
    expect(within(other).queryByText("(current)")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter companies" })).toHaveFocus();
  });

  it.each([
    ["m", ["MSFT"]],
    ["MS", ["MSFT"]],
    ["micro", ["MSFT"]],
    ["co", ["COST"]],
    ["APPLE", ["AAPL"]],
    // A prefix of the ticker or the name, not any substring.
    ["corp", []],
    ["sft", []],
  ])("filters by a ticker or name prefix, ignoring case (%s)", async (typed, expected) => {
    renderAt("/c/AAPL", "overview");
    const popover = await open();
    await within(popover).findAllByRole("option");

    await userEvent.type(screen.getByRole("combobox", { name: "Filter companies" }), typed);

    expect(optionNames(popover)).toEqual(expected);
    if (expected.length === 0) {
      expect(within(popover).getByText("No matching company.")).toBeInTheDocument();
    }
  });

  it("opens the typed company on the same tab with Enter, dropping ?scenario and ?case", async () => {
    renderAt("/c/AAPL/forecast?scenario=2&case=bull", "forecast");
    const popover = await open();
    await within(popover).findAllByRole("option");

    await userEvent.type(screen.getByRole("combobox", { name: "Filter companies" }), "ms{Enter}");

    expect(screen.getByTestId("where")).toHaveTextContent("/c/MSFT/forecast");
    expect(screen.getByTestId("where").textContent).toBe("/c/MSFT/forecast");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the company's overview at its bare path from the Overview", async () => {
    renderAt("/c/AAPL", "overview");
    const popover = await open();
    await within(popover).findAllByRole("option");

    await userEvent.type(screen.getByRole("combobox", { name: "Filter companies" }), "cost{Enter}");

    expect(screen.getByTestId("where").textContent).toBe("/c/COST");
  });

  it("moves with the arrow keys, staying within the list", async () => {
    renderAt("/c/AAPL/ratios", "ratios");
    const popover = await open();
    await within(popover).findAllByRole("option");
    const input = screen.getByRole("combobox", { name: "Filter companies" });
    const active = () =>
      within(popover)
        .getAllByRole("option")
        .find((option) => option.id === input.getAttribute("aria-activedescendant"));

    expect(active()).toHaveAccessibleName(/AAPL/);
    await userEvent.keyboard("{ArrowUp}");
    expect(active()).toHaveAccessibleName(/AAPL/);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(active()).toHaveAccessibleName(/COST/);
    await userEvent.keyboard("{ArrowUp}{Enter}");

    expect(screen.getByTestId("where").textContent).toBe("/c/MSFT/ratios");
  });

  it("opens a company on click", async () => {
    renderAt("/c/AAPL/notes", "notes");
    const popover = await open();

    await userEvent.click(await within(popover).findByRole("option", { name: /COST/ }));

    expect(screen.getByTestId("where").textContent).toBe("/c/COST/notes");
  });

  it("does nothing on Enter when no company matches", async () => {
    renderAt("/c/AAPL/notes", "notes");
    const popover = await open();
    await within(popover).findAllByRole("option");

    await userEvent.type(screen.getByRole("combobox", { name: "Filter companies" }), "zz{Enter}");

    expect(screen.getByTestId("where").textContent).toBe("/c/AAPL/notes");
    expect(screen.getByRole("dialog", { name: "Switch company" })).toBeInTheDocument();
  });

  it("closes with Escape and stays on the page", async () => {
    renderAt("/c/AAPL/notes", "notes");
    await open();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("where").textContent).toBe("/c/AAPL/notes");
  });

  it("starts a new filter each time it opens", async () => {
    renderAt("/c/AAPL/notes", "notes");
    let popover = await open();
    await within(popover).findAllByRole("option");
    await userEvent.type(screen.getByRole("combobox", { name: "Filter companies" }), "ms");
    await userEvent.keyboard("{Escape}");

    popover = await open();

    expect(screen.getByRole("combobox", { name: "Filter companies" })).toHaveValue("");
    expect(optionNames(popover)).toEqual(["AAPL", "MSFT", "COST"]);
  });

  it("says so while the companies load", async () => {
    listCompanies.mockReturnValue(new Promise(() => {}) as never);
    renderAt("/c/AAPL", "overview");

    const popover = await open();

    expect(within(popover).getByText("Loading…")).toBeInTheDocument();
  });

  it("says so when the companies fail to load", async () => {
    listCompanies.mockResolvedValue(errorResult(500) as never);
    renderAt("/c/AAPL", "overview");

    const popover = await open();

    expect(await within(popover).findByText("Could not load the companies.")).toBeInTheDocument();
  });
});
