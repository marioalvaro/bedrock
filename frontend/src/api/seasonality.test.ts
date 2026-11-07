import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import { ApiError } from "@/api/errors";
import { getSeasonalityApiV1CompaniesTickerSeasonalityGet } from "@/api/generated/sdk.gen";
import { seasonalityKey, seasonalityQueryOptions } from "@/api/seasonality";
import { errorResult, okResult } from "@/test/responses";
import { seasonality } from "@/test/seasonality";

vi.mock("@/api/generated/sdk.gen", () => ({
  getSeasonalityApiV1CompaniesTickerSeasonalityGet: vi.fn(),
}));

const getSeasonality = vi.mocked(getSeasonalityApiV1CompaniesTickerSeasonalityGet);

afterEach(() => vi.clearAllMocks());

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

describe("seasonalityQueryOptions", () => {
  it("sits under the company's seasonality key, by line", () => {
    expect(seasonalityKey("COST")).toEqual([...companyKey("COST"), "seasonality"]);
    expect(seasonalityQueryOptions("COST", "net_income").queryKey).toEqual([
      ...companyKey("COST"),
      "seasonality",
      "net_income",
    ]);
  });

  it("sends the line code as a query parameter", async () => {
    getSeasonality.mockResolvedValue(okResult(seasonality()) as never);
    const { queryClient } = setup();
    const data = await queryClient.fetchQuery(seasonalityQueryOptions("COST", "revenue"));
    expect(getSeasonality).toHaveBeenCalledWith({
      path: { ticker: "COST" },
      query: { code: "revenue" },
    });
    expect(data.strength).toBe(0.9769);
  });

  it("rejects a 200 of the wrong shape (an HTML shell, G2)", async () => {
    getSeasonality.mockResolvedValue(okResult("<!doctype html><html></html>") as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(seasonalityQueryOptions("COST", "revenue")),
    ).rejects.toMatchObject({ status: 200 });
  });

  it.each(["lines", "periods", "observed", "trend", "seasonal", "residual", "factors"] as const)(
    "rejects a 200 without its %s list",
    async (key) => {
      const { [key]: _dropped, ...rest } = seasonality();
      getSeasonality.mockResolvedValue(okResult(rest) as never);
      const { queryClient } = setup();
      await expect(
        queryClient.fetchQuery(seasonalityQueryOptions("COST", "revenue")),
      ).rejects.toBeInstanceOf(ApiError);
    },
  );

  it("rejects a 422 with its detail", async () => {
    getSeasonality.mockResolvedValue(
      errorResult(422, { detail: "Revenue has fewer than 12 consecutive quarters" }) as never,
    );
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(seasonalityQueryOptions("COST", "revenue")),
    ).rejects.toMatchObject({
      status: 422,
      detail: "Revenue has fewer than 12 consecutive quarters",
    });
  });

  it("keeps the previous line as placeholder data while another loads (G32)", async () => {
    getSeasonality.mockResolvedValueOnce(okResult(seasonality()) as never);
    let release: (value: unknown) => void = () => {};
    getSeasonality.mockReturnValueOnce(new Promise((resolve) => (release = resolve)) as never);
    const { wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ code }: { code: string }) => useQuery(seasonalityQueryOptions("COST", code)),
      { wrapper, initialProps: { code: "revenue" } },
    );
    await waitFor(() => expect(result.current.data?.code).toBe("revenue"));

    rerender({ code: "net_income" });
    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data?.code).toBe("revenue");

    release(okResult(seasonality({ code: "net_income", label: "Net income" })));
    await waitFor(() => expect(result.current.data?.code).toBe("net_income"));
    expect(result.current.isPlaceholderData).toBe(false);
  });

  it("does not carry another company's line as placeholder", async () => {
    getSeasonality.mockResolvedValueOnce(okResult(seasonality()) as never);
    getSeasonality.mockReturnValueOnce(new Promise(() => {}) as never);
    const { wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ ticker }: { ticker: string }) => useQuery(seasonalityQueryOptions(ticker, "revenue")),
      { wrapper, initialProps: { ticker: "COST" } },
    );
    await waitFor(() => expect(result.current.data?.code).toBe("revenue"));

    rerender({ ticker: "AAPL" });
    expect(result.current.data).toBeUndefined();
  });
});
