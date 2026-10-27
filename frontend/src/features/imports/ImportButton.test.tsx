import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listImportsApiV1CompaniesTickerImportsGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { okResult } from "@/test/responses";

import { ImportButton } from "./ImportButton";

vi.mock("@/api/generated/sdk.gen", () => ({
  listImportsApiV1CompaniesTickerImportsGet: vi.fn(),
  importStatementsApiV1CompaniesTickerImportsPost: vi.fn(),
  deleteImportApiV1CompaniesTickerImportsImportIdDelete: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(listImportsApiV1CompaniesTickerImportsGet).mockResolvedValue(okResult([]) as never);
});
afterEach(() => vi.clearAllMocks());

describe("ImportButton", () => {
  it("opens the import sheet and closes it again", async () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <ImportButton ticker="AAPL" />
      </QueryClientProvider>,
    );
    expect(screen.queryByText("Import statements")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByText("Import statements")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByText("Import statements")).not.toBeInTheDocument();
  });
});
