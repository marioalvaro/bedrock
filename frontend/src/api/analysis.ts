import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { ratiosKey } from "@/api/adjustments";
import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  createCustomRuleApiV1QoeCustomRulesPost,
  createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost,
  deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete,
  deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete,
  getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet,
  getFlagsApiV1CompaniesTickerFlagsGet,
  getMultiplesApiV1CompaniesTickerMultiplesGet,
  getRatiosApiV1CompaniesTickerRatiosGet,
  listCustomRulesApiV1QoeCustomRulesGet,
  listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet,
  listQoeRulesApiV1QoeRulesGet,
  resetQoeThresholdsApiV1QoeRulesCodeDelete,
  setQoeThresholdsApiV1QoeRulesCodePut,
  updateCustomRuleApiV1QoeCustomRulesRuleIdPut,
  updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut,
} from "@/api/generated/sdk.gen";
import type {
  CapitalAllocationOut,
  FlagsOut,
  MultiplesOut,
  OffBalanceItemIn,
  OffBalanceItemOut,
  QoeCustomRuleIn,
  QoeCustomRuleOut,
  QoeRuleOut,
  QoeThresholdsIn,
  RatiosOut,
} from "@/api/generated/types.gen";
import type { Basis } from "@/api/statements";

// Ratios, flags and capital allocation are offered annual and TTM only (no quarterly).
export type AnalysisFreq = "annual" | "ttm";

const hasArrays = (body: unknown, fields: string[]): boolean =>
  typeof body === "object" &&
  body !== null &&
  fields.every((f) => Array.isArray((body as Record<string, unknown>)[f]));

export const flagsKey = (ticker: string) => [...companyKey(ticker), "flags"] as const;
export const capitalAllocationKey = (ticker: string) =>
  [...companyKey(ticker), "capital-allocation"] as const;
export const offBalanceItemsKey = (ticker: string) =>
  [...companyKey(ticker), "off-balance-items"] as const;
// Valuation multiples sit under the ratios key, so `invalidateAdjustmentViews` reaches them.
export const multiplesKey = (ticker: string) => [...ratiosKey(ticker), "multiples"] as const;
// QoE rules are global (not per company).
export const qoeRulesKey = ["qoe-rules"] as const;
// Custom QoE rules are global too.
export const qoeCustomRulesKey = ["qoe-custom-rules"] as const;

/**
 * GET …/ratios?freq&basis. Key `[...ratiosKey(ticker), freq, basis]`, so an adjustment change
 * (`invalidateAdjustmentViews`) reaches it. Rejects a 200 whose body lacks the `periods` and
 * `rows` arrays with `ApiError(200, "Unexpected response")` (Gotcha G2).
 */
export const ratiosQueryOptions = (ticker: string, freq: AnalysisFreq, basis: Basis) =>
  queryOptions<RatiosOut>({
    queryKey: [...ratiosKey(ticker), freq, basis],
    queryFn: async () => {
      const body = await unwrap(
        getRatiosApiV1CompaniesTickerRatiosGet({ path: { ticker }, query: { freq, basis } }),
      );
      if (!hasArrays(body, ["periods", "rows"])) throw new ApiError(200, "Unexpected response");
      return body;
    },
  });

/**
 * GET …/multiples?basis. Key `[...multiplesKey(ticker), basis]`. Rejects a 200 whose body lacks the
 * `rows` array, as above.
 */
export const multiplesQueryOptions = (ticker: string, basis: Basis) =>
  queryOptions<MultiplesOut>({
    queryKey: [...multiplesKey(ticker), basis],
    queryFn: async () => {
      const body = await unwrap(
        getMultiplesApiV1CompaniesTickerMultiplesGet({ path: { ticker }, query: { basis } }),
      );
      if (!hasArrays(body, ["rows"])) throw new ApiError(200, "Unexpected response");
      return body;
    },
  });

/**
 * GET …/flags?freq. Key `[...flagsKey(ticker), freq]`. Rejects a 200 whose body lacks the
 * `periods`, `rules` and `off_balance_items` arrays, as above.
 */
export const flagsQueryOptions = (ticker: string, freq: AnalysisFreq) =>
  queryOptions<FlagsOut>({
    queryKey: [...flagsKey(ticker), freq],
    queryFn: async () => {
      const body = await unwrap(
        getFlagsApiV1CompaniesTickerFlagsGet({ path: { ticker }, query: { freq } }),
      );
      if (!hasArrays(body, ["periods", "rules", "off_balance_items"])) {
        throw new ApiError(200, "Unexpected response");
      }
      return body;
    },
  });

/**
 * GET …/capital-allocation?freq. Key `[...capitalAllocationKey(ticker), freq]`. Rejects a 200
 * whose body lacks the `periods` and `rows` arrays, as above.
 */
export const capitalAllocationQueryOptions = (ticker: string, freq: AnalysisFreq) =>
  queryOptions<CapitalAllocationOut>({
    queryKey: [...capitalAllocationKey(ticker), freq],
    queryFn: async () => {
      const body = await unwrap(
        getCapitalAllocationApiV1CompaniesTickerCapitalAllocationGet({
          path: { ticker },
          query: { freq },
        }),
      );
      if (!hasArrays(body, ["periods", "rows"])) throw new ApiError(200, "Unexpected response");
      return body;
    },
  });

/**
 * GET …/off-balance-items (newest `as_of` first, as the API orders it). Key
 * `offBalanceItemsKey(ticker)`. Rejects a 200 whose body is not an array, as above.
 */
export const offBalanceItemsQueryOptions = (ticker: string) =>
  queryOptions<OffBalanceItemOut[]>({
    queryKey: offBalanceItemsKey(ticker),
    queryFn: async () => {
      const list = await unwrap(
        listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet({ path: { ticker } }),
      );
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/** GET /qoe-rules. Key `qoeRulesKey`. Rejects a 200 whose body is not an array, as above. */
export const qoeRulesQueryOptions = () =>
  queryOptions<QoeRuleOut[]>({
    queryKey: qoeRulesKey,
    queryFn: async () => {
      const list = await unwrap(listQoeRulesApiV1QoeRulesGet());
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/**
 * Marks stale what an off-balance item change moves for `ticker`: its off-balance list and its
 * flags (every frequency; `FlagsOut` carries the items). Nothing else.
 */
export function invalidateOffBalanceViews(queryClient: QueryClient, ticker: string): Promise<void> {
  const prefixes = [offBalanceItemsKey(ticker), flagsKey(ticker)];
  return Promise.all(prefixes.map((queryKey) => queryClient.invalidateQueries({ queryKey }))).then(
    () => undefined,
  );
}

/** GET /qoe-custom-rules. Key `qoeCustomRulesKey`. Rejects a 200 whose body is not an array. */
export const customRulesQueryOptions = () =>
  queryOptions<QoeCustomRuleOut[]>({
    queryKey: qoeCustomRulesKey,
    queryFn: async () => {
      const list = await unwrap(listCustomRulesApiV1QoeCustomRulesGet());
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/**
 * Marks stale what a threshold or custom-rule change moves: the QoE rules, the custom rules and
 * every company's flags (any key
 * `["companies", <ticker>, "flags", …]`). Nothing else.
 */
export function invalidateThresholdViews(queryClient: QueryClient): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: qoeRulesKey }),
    queryClient.invalidateQueries({ queryKey: qoeCustomRulesKey }),
    queryClient.invalidateQueries({
      predicate: (query) => query.queryKey[0] === "companies" && query.queryKey[2] === "flags",
    }),
  ]).then(() => undefined);
}

/** POST …/off-balance-items with `body`; on success `invalidateOffBalanceViews`. */
export function useCreateOffBalanceItem(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<OffBalanceItemOut, Error, OffBalanceItemIn>({
    mutationFn: (body) =>
      unwrap(
        createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost({ path: { ticker }, body }),
      ),
    onSuccess: () => invalidateOffBalanceViews(queryClient, ticker),
  });
}

/** PUT …/off-balance-items/{id} with `body`; on success `invalidateOffBalanceViews`. */
export function useUpdateOffBalanceItem(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<OffBalanceItemOut, Error, { id: number; body: OffBalanceItemIn }>({
    mutationFn: ({ id, body }) =>
      unwrap(
        updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut({
          path: { ticker, item_id: id },
          body,
        }),
      ),
    onSuccess: () => invalidateOffBalanceViews(queryClient, ticker),
  });
}

/** DELETE …/off-balance-items/{id}; on success `invalidateOffBalanceViews`. */
export function useDeleteOffBalanceItem(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(
        deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete({
          path: { ticker, item_id: id },
        }),
      ),
    onSuccess: () => invalidateOffBalanceViews(queryClient, ticker),
  });
}

/**
 * PUT /qoe-rules/{code} with `body` (both keys; levels as fractions for a `pct` rule, null
 * removes a level); on success `invalidateThresholdViews`.
 */
export function useSetQoeThresholds() {
  const queryClient = useQueryClient();
  return useMutation<QoeRuleOut, Error, { code: string; body: QoeThresholdsIn }>({
    mutationFn: ({ code, body }) =>
      unwrap(setQoeThresholdsApiV1QoeRulesCodePut({ path: { code }, body })),
    onSuccess: () => invalidateThresholdViews(queryClient),
  });
}

/** DELETE /qoe-rules/{code} (back to the default); on success `invalidateThresholdViews`. */
export function useResetQoeThresholds() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (code) => unwrap(resetQoeThresholdsApiV1QoeRulesCodeDelete({ path: { code } })),
    onSuccess: () => invalidateThresholdViews(queryClient),
  });
}

/** POST /qoe-custom-rules with `body`; on success `invalidateThresholdViews`. */
export function useCreateQoeCustomRule() {
  const queryClient = useQueryClient();
  return useMutation<QoeCustomRuleOut, Error, QoeCustomRuleIn>({
    mutationFn: (body) => unwrap(createCustomRuleApiV1QoeCustomRulesPost({ body })),
    onSuccess: () => invalidateThresholdViews(queryClient),
  });
}

/** PUT /qoe-custom-rules/{id} with `body`; on success `invalidateThresholdViews`. */
export function useUpdateQoeCustomRule() {
  const queryClient = useQueryClient();
  return useMutation<QoeCustomRuleOut, Error, { id: number; body: QoeCustomRuleIn }>({
    mutationFn: ({ id, body }) =>
      unwrap(updateCustomRuleApiV1QoeCustomRulesRuleIdPut({ path: { rule_id: id }, body })),
    onSuccess: () => invalidateThresholdViews(queryClient),
  });
}

/** DELETE /qoe-custom-rules/{id}; on success `invalidateThresholdViews`. */
export function useDeleteQoeCustomRule() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete({ path: { rule_id: id } })),
    onSuccess: () => invalidateThresholdViews(queryClient),
  });
}
