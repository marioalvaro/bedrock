import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import { getEarningsReviewApiV1CompaniesTickerEarningsReviewGet } from "@/api/generated/sdk.gen";
import { reviewKey, reviewQueryOptions } from "@/api/review";
import { earningsReview, emptyReview } from "@/test/review";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getEarningsReviewApiV1CompaniesTickerEarningsReviewGet: vi.fn(),
}));

const getReview = vi.mocked(getEarningsReviewApiV1CompaniesTickerEarningsReviewGet);
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

afterEach(() => vi.clearAllMocks());

describe("reviewQueryOptions", () => {
  it("sits under the company and is always stale", () => {
    expect(reviewKey("AAPL")).toEqual([...companyKey("AAPL"), "review"]);
    expect(reviewQueryOptions("AAPL").queryKey).toEqual(reviewKey("AAPL"));
    expect(reviewQueryOptions("AAPL").staleTime).toBe(0);
  });

  it("loads the review of the newest report", async () => {
    getReview.mockResolvedValue(okResult(earningsReview()) as never);
    const data = await client().fetchQuery(reviewQueryOptions("AAPL"));
    expect(getReview).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(data.lines).toHaveLength(1);
  });

  it("accepts the review of a company with no report", async () => {
    getReview.mockResolvedValue(okResult(emptyReview()) as never);
    const data = await client().fetchQuery(reviewQueryOptions("AAPL"));
    expect(data.filing).toBeNull();
  });

  it.each([
    ["an HTML shell", "<!doctype html><html></html>"],
    ["no lines", { ...earningsReview(), lines: undefined }],
    ["no restated rows", { ...earningsReview(), restated: undefined }],
    ["no checkpoints", { ...earningsReview(), checkpoints: undefined }],
  ])("rejects a 200 with %s (G2/G4)", async (_name, body) => {
    getReview.mockResolvedValue(okResult(body) as never);
    await expect(client().fetchQuery(reviewQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 200,
    });
  });

  it("carries the API's detail", async () => {
    getReview.mockResolvedValue(errorResult(404, { detail: "Company not found" }) as never);
    await expect(client().fetchQuery(reviewQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 404,
      detail: "Company not found",
    });
  });
});
