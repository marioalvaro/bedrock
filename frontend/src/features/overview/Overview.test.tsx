import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getMappingGapsApiV1CompaniesTickerMappingGapsGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { companyItem, mappingGaps } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import { Overview } from "./Overview";

vi.mock("@/api/generated/sdk.gen", () => ({
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
}));

function renderOverview() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <Overview company={companyItem()} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("Overview", () => {
  it("shows the key stats, with a dash for one that is missing", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    renderOverview();

    const stats = await screen.findByRole("region", { name: "Key stats" });
    expect(within(stats).getByText("Price")).toBeInTheDocument();
    expect(within(stats).getByText("231.40")).toBeInTheDocument();
    expect(within(stats).getByText("3.5T")).toBeInTheDocument();
    expect(within(stats).getByText("34.2x")).toBeInTheDocument();
    expect(within(stats).getByText("5.1%")).toBeInTheDocument();
    expect(within(stats).getByText("—")).toBeInTheDocument();
  });

  it("lists the missing items with their statement and fiscal years", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    renderOverview();

    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    const row = (await within(gaps).findByText("Short-term debt")).closest("tr") as HTMLElement;
    expect(within(row).getByText("BS")).toBeInTheDocument();
    expect(within(row).getByText("FY2008, FY2009, FY2010")).toBeInTheDocument();
  });

  it("lists the unmapped concepts with their latest value", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    renderOverview();

    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    const row = (
      await within(gaps).findByText("us-gaap:IncreaseDecreaseInOtherOperatingCapitalNet")
    ).closest("tr") as HTMLElement;
    expect(within(row).getByText("(1,200)")).toBeInTheDocument();
    expect(within(row).getByText("2025-09-27")).toBeInTheDocument();
  });

  it("says so when there are no gaps", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult({ missing_items: [], unmapped_concepts: [] }) as never,
    );
    renderOverview();

    expect(await screen.findByText("No missing items.")).toBeInTheDocument();
    expect(screen.getByText("No unmapped concepts.")).toBeInTheDocument();
  });

  it("shows an error when the gaps fail to load, and keeps the key stats", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      errorResult(500) as never,
    );
    renderOverview();

    expect(await screen.findByText("Could not load the data gaps.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Key stats" })).toBeInTheDocument();
  });

  it("shows an error for a 200 that is not a gaps report (G2/G4)", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult("<!doctype html>") as never,
    );
    renderOverview();

    expect(await screen.findByText("Could not load the data gaps.")).toBeInTheDocument();
  });
});
