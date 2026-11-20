import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import { getSummaryApiV1CompaniesTickerSummaryGet } from "@/api/generated/sdk.gen";
import { summaryKey, summaryQueryOptions } from "@/api/summary";
import { errorResult, okResult } from "@/test/responses";
import { companySummary } from "@/test/summary";

vi.mock("@/api/generated/sdk.gen", () => ({
  getSummaryApiV1CompaniesTickerSummaryGet: vi.fn(),
}));

const getSummary = vi.mocked(getSummaryApiV1CompaniesTickerSummaryGet);
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

afterEach(() => vi.clearAllMocks());

describe("summaryQueryOptions", () => {
  it("sits under the company, so a refresh reloads it", () => {
    expect(summaryKey("AAPL")).toEqual([...companyKey("AAPL"), "summary"]);
    expect(summaryQueryOptions("AAPL").queryKey).toEqual(["companies", "AAPL", "summary"]);
  });

  it("loads the company's summary", async () => {
    getSummary.mockResolvedValue(okResult(companySummary()) as never);

    const data = await client().fetchQuery(summaryQueryOptions("AAPL"));

    expect(getSummary).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(data.metrics).toHaveLength(7);
  });

  it("accepts a summary with every optional block empty", async () => {
    getSummary.mockResolvedValue(
      okResult(
        companySummary({ metrics: [], flags: [], notes: [], valuation: null, forecast: null }),
      ) as never,
    );

    const data = await client().fetchQuery(summaryQueryOptions("AAPL"));

    expect(data.valuation).toBeNull();
    expect(data.forecast).toBeNull();
  });

  it.each([
    ["an HTML shell", "<!doctype html><html></html>"],
    ["no metrics", { ...companySummary(), metrics: undefined }],
    ["no flags", { ...companySummary(), flags: undefined }],
    ["no notes", { ...companySummary(), notes: undefined }],
    ["no warnings", { ...companySummary(), warnings: undefined }],
    // A missing block is not a null one: the views read a null block as "none yet".
    ["no valuation key", { ...companySummary(), valuation: undefined }],
    ["no forecast key", { ...companySummary(), forecast: undefined }],
  ])("rejects a 200 with %s (G2/G4)", async (_name, body) => {
    getSummary.mockResolvedValue(okResult(body) as never);

    await expect(client().fetchQuery(summaryQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 200,
    });
  });

  it("carries the API's detail", async () => {
    getSummary.mockResolvedValue(errorResult(404, { detail: "Company not found" }) as never);

    await expect(client().fetchQuery(summaryQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 404,
      detail: "Company not found",
    });
  });
});
