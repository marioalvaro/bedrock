import {
  QueryClient,
  QueryClientProvider,
  type FetchQueryOptions,
  type UseMutationResult,
} from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { invalidateAdjustmentViews, ratiosKey } from "@/api/adjustments";
import {
  capitalAllocationKey,
  capitalAllocationQueryOptions,
  flagsKey,
  flagsQueryOptions,
  invalidateOffBalanceViews,
  invalidateThresholdViews,
  offBalanceItemsKey,
  offBalanceItemsQueryOptions,
  customRulesQueryOptions,
  qoeCustomRulesKey,
  qoeRulesKey,
  qoeRulesQueryOptions,
  useCreateQoeCustomRule,
  useDeleteQoeCustomRule,
  useUpdateQoeCustomRule,
  ratiosQueryOptions,
  useCreateOffBalanceItem,
  useDeleteOffBalanceItem,
  useResetQoeThresholds,
  useSetQoeThresholds,
  useUpdateOffBalanceItem,
} from "@/api/analysis";
import { companyKey } from "@/api/companies";
import { ApiError } from "@/api/errors";
import {
  createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost,
  deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete,
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet,
  getFlagsApiV1CompaniesTickerFlagsGet,
  getRatiosApiV1CompaniesTickerRatiosGet,
  listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet,
  listQoeRulesApiV1QoeRulesGet,
  createCustomRuleApiV1QoeCustomRulesPost,
  deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete,
  listCustomRulesApiV1QoeCustomRulesGet,
  resetQoeThresholdsApiV1QoeRulesCodeDelete,
  setQoeThresholdsApiV1QoeRulesCodePut,
  updateCustomRuleApiV1QoeCustomRulesRuleIdPut,
  updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut,
} from "@/api/generated/sdk.gen";
import {
  capitalAllocation,
  flags,
  offBalanceItem,
  offBalanceItems,
  qoeCustomRule,
  qoeRule,
  qoeRules,
  ratios,
} from "@/test/analysis";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getRatiosApiV1CompaniesTickerRatiosGet: vi.fn(),
  getFlagsApiV1CompaniesTickerFlagsGet: vi.fn(),
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet: vi.fn(),
  listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet: vi.fn(),
  createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost: vi.fn(),
  updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut: vi.fn(),
  deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete: vi.fn(),
  listQoeRulesApiV1QoeRulesGet: vi.fn(),
  setQoeThresholdsApiV1QoeRulesCodePut: vi.fn(),
  resetQoeThresholdsApiV1QoeRulesCodeDelete: vi.fn(),
  listCustomRulesApiV1QoeCustomRulesGet: vi.fn(),
  createCustomRuleApiV1QoeCustomRulesPost: vi.fn(),
  updateCustomRuleApiV1QoeCustomRulesRuleIdPut: vi.fn(),
  deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete: vi.fn(),
}));

const getRatios = vi.mocked(getRatiosApiV1CompaniesTickerRatiosGet);
const getFlags = vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet);
const getCapital = vi.mocked(getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet);
const listItems = vi.mocked(listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet);
const createItem = vi.mocked(createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost);
const updateItem = vi.mocked(updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut);
const deleteItem = vi.mocked(deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete);
const listRules = vi.mocked(listQoeRulesApiV1QoeRulesGet);
const setRule = vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut);
const resetRule = vi.mocked(resetQoeThresholdsApiV1QoeRulesCodeDelete);
const listCustom = vi.mocked(listCustomRulesApiV1QoeCustomRulesGet);
const createCustom = vi.mocked(createCustomRuleApiV1QoeCustomRulesPost);
const updateCustom = vi.mocked(updateCustomRuleApiV1QoeCustomRulesRuleIdPut);
const deleteCustom = vi.mocked(deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete);

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

afterEach(() => vi.clearAllMocks());

const itemBody = {
  kind: "purchase_commitment",
  description: "Unconditional purchase obligations",
  amount: "12500000000",
  as_of: "2024-09-28",
  source_note: "10-K Note 12",
} as never;
const thresholds = { warn: "0.05", alert: null } as never;

// Every query: key, SDK call, body, G2 garbage body, 404 and 422.
const queries = [
  {
    name: "ratiosQueryOptions",
    options: () => ratiosQueryOptions("DE", "ttm", "normalized"),
    key: [...ratiosKey("DE"), "ttm", "normalized"],
    sdk: getRatios,
    args: { path: { ticker: "DE" }, query: { freq: "ttm", basis: "normalized" } },
    body: ratios(),
    bad: [{ periods: [] }, "<html></html>"],
  },
  {
    name: "flagsQueryOptions",
    options: () => flagsQueryOptions("AAPL", "annual"),
    key: [...flagsKey("AAPL"), "annual"],
    sdk: getFlags,
    args: { path: { ticker: "AAPL" }, query: { freq: "annual" } },
    body: flags(),
    bad: [{ periods: [], rules: [] }, "<html></html>"],
  },
  {
    name: "capitalAllocationQueryOptions",
    options: () => capitalAllocationQueryOptions("AAPL", "ttm"),
    key: [...capitalAllocationKey("AAPL"), "ttm"],
    sdk: getCapital,
    args: { path: { ticker: "AAPL" }, query: { freq: "ttm" } },
    body: capitalAllocation(),
    bad: [{ periods: [] }, "<html></html>"],
  },
  {
    name: "offBalanceItemsQueryOptions",
    options: () => offBalanceItemsQueryOptions("AAPL"),
    key: offBalanceItemsKey("AAPL"),
    sdk: listItems,
    args: { path: { ticker: "AAPL" } },
    body: offBalanceItems(),
    bad: [{}, "<html></html>"],
  },
  {
    name: "qoeRulesQueryOptions",
    options: () => qoeRulesQueryOptions(),
    key: qoeRulesKey,
    sdk: listRules,
    args: undefined,
    body: qoeRules(),
    bad: [{}, "<html></html>"],
  },
  {
    name: "customRulesQueryOptions",
    options: () => customRulesQueryOptions(),
    key: qoeCustomRulesKey,
    sdk: listCustom,
    args: undefined,
    body: [qoeCustomRule()],
    bad: [{}, "<html></html>"],
  },
];

describe.each(queries)("$name", ({ options: makeOptions, key, sdk, args, body, bad }) => {
  const options = makeOptions as () => FetchQueryOptions;
  it("has the contract key", () => {
    expect(options().queryKey).toEqual(key);
  });

  it("calls the SDK and returns the body", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(okResult(body) as never);
    const { queryClient } = setup();
    expect(await queryClient.fetchQuery(options())).toEqual(body);
    if (args) expect(sdk).toHaveBeenCalledWith(args);
    else expect(sdk).toHaveBeenCalledTimes(1);
  });

  it.each(bad)("rejects a 200 with a malformed body %j", async (garbage) => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(okResult(garbage) as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(options())).rejects.toMatchObject({
      status: 200,
      detail: "Unexpected response",
    });
  });

  it.each([404, 422])("rejects a %i with status and detail", async (status) => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(
      errorResult(status, { detail: "nope" }) as never,
    );
    const { queryClient } = setup();
    const err = await queryClient.fetchQuery(options()).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status, detail: "nope" });
  });
});

describe("ratios key", () => {
  it("is marked stale by invalidateAdjustmentViews", async () => {
    const { queryClient } = setup();
    const key = ratiosQueryOptions("DE", "annual", "reported").queryKey;
    queryClient.setQueryData(key, ratios());
    await invalidateAdjustmentViews(queryClient, "DE");
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
  });
});

describe("invalidateOffBalanceViews", () => {
  it("marks stale the company's list and flags only", async () => {
    const { queryClient } = setup();
    const stale = [
      offBalanceItemsKey("AAPL"),
      [...flagsKey("AAPL"), "annual"],
      [...flagsKey("AAPL"), "ttm"],
    ];
    const fresh = [
      [...flagsKey("MSFT"), "annual"],
      offBalanceItemsKey("MSFT"),
      [...ratiosKey("AAPL"), "annual", "reported"],
      [...capitalAllocationKey("AAPL"), "annual"],
      [...companyKey("AAPL"), "statements", "IS", "annual", "total", "reported"],
      qoeRulesKey,
    ];
    for (const key of [...stale, ...fresh]) queryClient.setQueryData(key, {});
    await invalidateOffBalanceViews(queryClient, "AAPL");
    for (const key of stale) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    for (const key of fresh) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });
});

describe("invalidateThresholdViews", () => {
  it("marks stale the rules and every company's flags only", async () => {
    const { queryClient } = setup();
    const stale = [
      qoeRulesKey,
      qoeCustomRulesKey,
      [...flagsKey("AAPL"), "annual"],
      [...flagsKey("AAPL"), "ttm"],
      [...flagsKey("MSFT"), "annual"],
    ];
    const fresh = [
      [...ratiosKey("AAPL"), "annual", "reported"],
      [...capitalAllocationKey("AAPL"), "annual"],
      offBalanceItemsKey("AAPL"),
      [...companyKey("AAPL"), "statements", "IS", "annual", "total", "reported"],
    ];
    for (const key of [...stale, ...fresh]) queryClient.setQueryData(key, {});
    await invalidateThresholdViews(queryClient);
    for (const key of stale) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    for (const key of fresh) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });
});

function useCreateCase() {
  return useCreateOffBalanceItem("AAPL");
}
function useUpdateCase() {
  return useUpdateOffBalanceItem("AAPL");
}
function useDeleteCase() {
  return useDeleteOffBalanceItem("AAPL");
}
function useSetCase() {
  return useSetQoeThresholds();
}
function useResetCase() {
  return useResetQoeThresholds();
}
function useCreateCustomCase() {
  return useCreateQoeCustomRule();
}
function useUpdateCustomCase() {
  return useUpdateQoeCustomRule();
}
function useDeleteCustomCase() {
  return useDeleteQoeCustomRule();
}
const customBody = {
  label: "Accruals (mine)",
  formula: "(net_income - cfo) / avg(total_assets)",
  direction: "above" as const,
  unit: "pct" as const,
  warn: "0.05",
  alert: "prev(sbc / revenue) + 1%",
};

// Mutations: hook, trigger, SDK mock, expected call, success payload, and which group goes stale.
type AnyMutation = UseMutationResult<unknown, Error, never>;
const offBalanceStale = () => [offBalanceItemsKey("AAPL"), [...flagsKey("AAPL"), "annual"]];
const thresholdStale = () => [
  qoeRulesKey,
  qoeCustomRulesKey,
  [...flagsKey("AAPL"), "annual"],
];

const mutations = [
  {
    name: "create",
    sdk: createItem,
    ok: () => okResult(offBalanceItem(), 201),
    hook: useCreateCase,
    vars: itemBody,
    call: { path: { ticker: "AAPL" }, body: itemBody },
    stale: offBalanceStale,
  },
  {
    name: "update",
    sdk: updateItem,
    ok: () => okResult(offBalanceItem()),
    hook: useUpdateCase,
    vars: { id: 3, body: itemBody },
    call: { path: { ticker: "AAPL", item_id: 3 }, body: itemBody },
    stale: offBalanceStale,
  },
  {
    name: "delete",
    sdk: deleteItem,
    ok: () => okResult(null, 204),
    hook: useDeleteCase,
    vars: 3,
    call: { path: { ticker: "AAPL", item_id: 3 } },
    stale: offBalanceStale,
  },
  {
    name: "set thresholds",
    sdk: setRule,
    ok: () => okResult(qoeRule()),
    hook: useSetCase,
    vars: { code: "accruals_ratio", body: thresholds },
    call: { path: { code: "accruals_ratio" }, body: thresholds },
    stale: thresholdStale,
  },
  {
    name: "reset thresholds",
    sdk: resetRule,
    ok: () => okResult(null, 204),
    hook: useResetCase,
    vars: "accruals_ratio",
    call: { path: { code: "accruals_ratio" } },
    stale: thresholdStale,
  },
  {
    name: "create custom rule",
    sdk: createCustom,
    ok: () => okResult(qoeCustomRule(), 201),
    hook: useCreateCustomCase,
    vars: customBody,
    call: { body: customBody },
    stale: thresholdStale,
  },
  {
    name: "update custom rule",
    sdk: updateCustom,
    ok: () => okResult(qoeCustomRule()),
    hook: useUpdateCustomCase,
    vars: { id: 4, body: customBody },
    call: { path: { rule_id: 4 }, body: customBody },
    stale: thresholdStale,
  },
  {
    name: "delete custom rule",
    sdk: deleteCustom,
    ok: () => okResult(null, 204),
    hook: useDeleteCustomCase,
    vars: 4,
    call: { path: { rule_id: 4 } },
    stale: thresholdStale,
  },
];

describe.each(mutations)("mutation $name", ({ sdk, ok, hook, vars, call, stale }) => {
  it("calls the SDK and invalidates on success", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(ok() as never);
    const { wrapper, queryClient } = setup();
    for (const key of stale()) queryClient.setQueryData(key, {});
    const { result } = renderHook(hook as () => AnyMutation, { wrapper });
    result.current.mutate(vars as never);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(sdk).toHaveBeenCalledWith(call);
    for (const key of stale()) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
  });

  it("surfaces a 422 detail and does not invalidate", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(
      errorResult(422, { detail: "bad input" }) as never,
    );
    const { wrapper, queryClient } = setup();
    for (const key of stale()) queryClient.setQueryData(key, {});
    const { result } = renderHook(hook as () => AnyMutation, { wrapper });
    result.current.mutate(vars as never);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).detail).toBe("bad input");
    for (const key of stale()) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });
});

describe("mutations on a network error", () => {
  it("fail with no status", async () => {
    createItem.mockResolvedValue(networkErrorResult() as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useCreateOffBalanceItem("AAPL"), { wrapper });
    result.current.mutate(itemBody);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).status).toBeUndefined();
  });
});
