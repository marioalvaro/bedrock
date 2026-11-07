import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  adjustmentsKey,
  adjustmentsQueryOptions,
  corporateActionsKey,
  corporateActionsQueryOptions,
  invalidateAdjustmentViews,
  ratiosKey,
  useCreateAdjustment,
  useDeleteAdjustment,
  useUpdateAdjustment,
} from "@/api/adjustments";
import { companyKey } from "@/api/companies";
import { ApiError } from "@/api/errors";
import {
  createAdjustmentApiV1CompaniesTickerAdjustmentsPost,
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete,
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet,
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet,
  updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut,
} from "@/api/generated/sdk.gen";
import { adjustment, corporateActions } from "@/test/adjustments";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet: vi.fn(),
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet: vi.fn(),
  createAdjustmentApiV1CompaniesTickerAdjustmentsPost: vi.fn(),
  updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut: vi.fn(),
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete: vi.fn(),
}));

const listAdj = vi.mocked(listAdjustmentsApiV1CompaniesTickerAdjustmentsGet);
const listActions = vi.mocked(listCorporateActionsApiV1CompaniesTickerCorporateActionsGet);
const create = vi.mocked(createAdjustmentApiV1CompaniesTickerAdjustmentsPost);
const update = vi.mocked(updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut);
const remove = vi.mocked(deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete);

const body = {
  canonical_code: "sga",
  fiscal_year: 2024,
  fiscal_period: "FY",
  amount: "-25000000",
  category: "one-off",
  reason: "Legal settlement",
} as never;

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

afterEach(() => vi.clearAllMocks());

const viewKeys = (ticker: string) => [
  [...companyKey(ticker), "statements", "IS", "annual", "total", "reported"],
  [...companyKey(ticker), "cell", "sga", 2024, "FY"],
  adjustmentsKey(ticker),
  [...ratiosKey(ticker), "annual"],
];
const controlKeys = () => [
  [...companyKey("AAPL"), "mapping-gaps"],
  [...companyKey("MSFT"), "statements", "IS", "annual", "total", "reported"],
];

function seedViews(queryClient: QueryClient) {
  for (const key of [...viewKeys("AAPL"), ...controlKeys()]) queryClient.setQueryData(key, {});
}

function expectViewsInvalidated(queryClient: QueryClient, invalidated: boolean) {
  for (const key of viewKeys("AAPL")) {
    expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(invalidated);
  }
  for (const key of controlKeys()) {
    expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
  }
}

describe("adjustmentsQueryOptions", () => {
  it("returns the list", async () => {
    listAdj.mockResolvedValue(okResult([adjustment()]) as never);
    const { queryClient } = setup();
    const data = await queryClient.fetchQuery(adjustmentsQueryOptions("AAPL"));
    expect(data).toEqual([adjustment()]);
    expect(listAdj).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
  });

  it("rejects a 200 whose body is not an array", async () => {
    listAdj.mockResolvedValue(okResult("<html></html>") as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(adjustmentsQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 200,
      detail: "Unexpected response",
    });
  });

  it("rejects a 404 with its status", async () => {
    listAdj.mockResolvedValue(errorResult(404, { detail: "Unknown ticker" }) as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(adjustmentsQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 404,
    });
  });

  it("rejects on a network error", async () => {
    listAdj.mockResolvedValue(networkErrorResult() as never);
    const { queryClient } = setup();
    const err = await queryClient.fetchQuery(adjustmentsQueryOptions("AAPL")).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBeUndefined();
  });
});

describe("corporateActionsQueryOptions", () => {
  it("returns the list", async () => {
    listActions.mockResolvedValue(okResult(corporateActions()) as never);
    const { queryClient } = setup();
    const data = await queryClient.fetchQuery(corporateActionsQueryOptions("AAPL"));
    expect(data).toEqual(corporateActions());
    expect(listActions).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
  });

  it("rejects a 200 whose body is not an array", async () => {
    listActions.mockResolvedValue(okResult("<html></html>") as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(corporateActionsQueryOptions("AAPL")),
    ).rejects.toMatchObject({ status: 200, detail: "Unexpected response" });
  });

  it("rejects a 404 with its status", async () => {
    listActions.mockResolvedValue(errorResult(404) as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(corporateActionsQueryOptions("AAPL")),
    ).rejects.toMatchObject({ status: 404 });
  });
});

describe("mutations", () => {
  it("create POSTs the body for the ticker", async () => {
    create.mockResolvedValue(okResult(adjustment(), 201) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useCreateAdjustment("AAPL"), { wrapper });
    result.current.mutate(body);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(create).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, body });
    expect(result.current.data).toEqual(adjustment());
  });

  it("create surfaces a 422 detail", async () => {
    create.mockResolvedValue(errorResult(422, { detail: "reason must not be blank" }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useCreateAdjustment("AAPL"), { wrapper });
    result.current.mutate(body);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).detail).toBe("reason must not be blank");
  });

  it("create fails on a network error without invalidating", async () => {
    create.mockResolvedValue(networkErrorResult() as never);
    const { wrapper, queryClient } = setup();
    queryClient.setQueryData(adjustmentsKey("AAPL"), []);
    const { result } = renderHook(() => useCreateAdjustment("AAPL"), { wrapper });
    result.current.mutate(body);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).status).toBeUndefined();
    expect(queryClient.getQueryState(adjustmentsKey("AAPL"))?.isInvalidated).toBe(false);
  });

  it("update PUTs to the adjustment id", async () => {
    update.mockResolvedValue(okResult(adjustment()) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useUpdateAdjustment("AAPL"), { wrapper });
    result.current.mutate({ id: 7, body });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(update).toHaveBeenCalledWith({ path: { ticker: "AAPL", adjustment_id: 7 }, body });
  });

  it("update surfaces a 404", async () => {
    update.mockResolvedValue(errorResult(404, { detail: "Adjustment not found" }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useUpdateAdjustment("AAPL"), { wrapper });
    result.current.mutate({ id: 7, body });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).status).toBe(404);
    expect((result.current.error as ApiError).detail).toBe("Adjustment not found");
  });

  it("delete DELETEs by id", async () => {
    remove.mockResolvedValue(okResult(null, 204) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useDeleteAdjustment("AAPL"), { wrapper });
    result.current.mutate(7);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", adjustment_id: 7 } });
  });

  it("delete surfaces a 404", async () => {
    remove.mockResolvedValue(errorResult(404) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useDeleteAdjustment("AAPL"), { wrapper });
    result.current.mutate(7);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).status).toBe(404);
  });

  it("a successful create invalidates the ticker's views", async () => {
    create.mockResolvedValue(okResult(adjustment(), 201) as never);
    const { wrapper, queryClient } = setup();
    seedViews(queryClient);
    const { result } = renderHook(() => useCreateAdjustment("AAPL"), { wrapper });
    result.current.mutate(body);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectViewsInvalidated(queryClient, true);
  });

  it("a successful update invalidates the ticker's views", async () => {
    update.mockResolvedValue(okResult(adjustment()) as never);
    const { wrapper, queryClient } = setup();
    seedViews(queryClient);
    const { result } = renderHook(() => useUpdateAdjustment("AAPL"), { wrapper });
    result.current.mutate({ id: 7, body });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectViewsInvalidated(queryClient, true);
  });

  it("a failed update leaves the views alone", async () => {
    update.mockResolvedValue(errorResult(422, { detail: "reason must not be blank" }) as never);
    const { wrapper, queryClient } = setup();
    seedViews(queryClient);
    const { result } = renderHook(() => useUpdateAdjustment("AAPL"), { wrapper });
    result.current.mutate({ id: 7, body });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expectViewsInvalidated(queryClient, false);
  });

  it("a successful delete invalidates the ticker's views", async () => {
    remove.mockResolvedValue(okResult(null, 204) as never);
    const { wrapper, queryClient } = setup();
    seedViews(queryClient);
    const { result } = renderHook(() => useDeleteAdjustment("AAPL"), { wrapper });
    result.current.mutate(7);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectViewsInvalidated(queryClient, true);
  });
});

describe("invalidateAdjustmentViews", () => {
  it("invalidates the ticker's statements, cells, adjustments, ratios, guidance, comps, scenarios and seasonality only", async () => {
    const { queryClient } = setup();
    const aapl = companyKey("AAPL");
    const stale = [
      [...aapl, "statements", "IS", "annual", "total", "reported"],
      [...aapl, "statements", "BS", "quarterly", "parent", "normalized"],
      [...aapl, "cell", "sga", 2024, "FY"],
      adjustmentsKey("AAPL"),
      [...ratiosKey("AAPL"), "annual"],
      [...aapl, "guidance"],
      [...aapl, "comps", 3, "normalized"],
      [...aapl, "scenarios"],
      [...aapl, "scenarios", 1, "forecast", "IS", "annual"],
      [...aapl, "scenarios", "compare", "annual"],
      [...aapl, "seasonality", "revenue"],
    ];
    const fresh = [
      aapl,
      [...aapl, "guidance-metrics"],
      [...aapl, "comps-sets"],
      [...aapl, "peer-suggestions", 3],
      [...aapl, "segments", "annual"],
      [...aapl, "notes", {}],
      [...aapl, "note-links"],
      [...companyKey("MSFT"), "guidance"],
      [...aapl, "mapping-gaps"],
      corporateActionsKey("AAPL"),
      ["companies"],
      [...companyKey("MSFT"), "statements", "IS", "annual", "total", "reported"],
      adjustmentsKey("MSFT"),
      [...companyKey("MSFT"), "scenarios"],
      [...companyKey("MSFT"), "seasonality", "revenue"],
    ];
    for (const key of [...stale, ...fresh]) queryClient.setQueryData(key, {});

    await invalidateAdjustmentViews(queryClient, "AAPL");

    for (const key of stale) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    for (const key of fresh) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });
});
