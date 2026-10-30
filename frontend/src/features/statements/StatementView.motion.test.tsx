import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getStatementApiV1CompaniesTickerStatementsGet,
  listLinksApiV1CompaniesTickerNotesLinksGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { okResult } from "@/test/responses";
import { incomeStatement } from "@/test/statements";

import { StatementView } from "./StatementView";

// Toggles and refetches must update the grid in place: the same row and header elements
// stay mounted, so the numbers do not jump (S4e).
vi.mock("@/api/generated/sdk.gen", () => ({
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
}));

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <StatementView ticker="AAPL" cik="0000320193" type="IS" />
    </QueryClientProvider>,
  );
}

const row = (id: string) => document.querySelector(`[row-id="${id}"]`) as HTMLElement | null;
const header = (id: string) => document.querySelector(`.ag-header-cell[col-id="${id}"]`);

beforeEach(() => {
  setScale("M");
  vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockResolvedValue(
    okResult(incomeStatement()) as never,
  );
  vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet).mockResolvedValue(okResult([]) as never);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("StatementView stays put while it changes", () => {
  it("keeps the existing rows and headers mounted when YoY is toggled", async () => {
    renderView();
    await screen.findByText("Revenue");
    const revenue = row("revenue");
    const fy2024 = header("FY2024");

    await userEvent.click(screen.getByRole("button", { name: "YoY" }));

    await waitFor(() => expect(row("revenue:yoy")).not.toBeNull());
    expect(row("revenue")).toBe(revenue);
    expect(header("FY2024")).toBe(fy2024);
  });

  it("keeps the existing rows mounted when a breakdown opens", async () => {
    renderView();
    await screen.findByText("Revenue");
    const revenue = row("revenue");
    const eps = row("eps_diluted");

    await userEvent.click(screen.getByRole("button", { name: "Expand Gross profit" }));

    expect(await screen.findByText("Cost of revenue")).toBeInTheDocument();
    expect(row("revenue")).toBe(revenue);
    expect(row("eps_diluted")).toBe(eps);
  });

  it("keeps the grid on screen while another frequency loads", async () => {
    renderView();
    await screen.findByText("Revenue");
    const revenue = row("revenue");
    let resolve: (value: never) => void = () => {};
    vi.mocked(getStatementApiV1CompaniesTickerStatementsGet).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }) as never,
    );

    await userEvent.click(screen.getByRole("radio", { name: "Quarterly" }));

    await waitFor(() =>
      expect(getStatementApiV1CompaniesTickerStatementsGet).toHaveBeenCalledTimes(2),
    );
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(row("revenue")).toBe(revenue);
    // The rows are still the old frequency's, so they must not be exported under the new name.
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeDisabled();

    resolve(okResult(incomeStatement({ freq: "quarterly" })) as never);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Download CSV" })).toBeEnabled(),
    );
  });
});
