import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { compsKey, guidanceKey } from "@/api/context";
import { ApiError, unwrap } from "@/api/errors";
import {
  createAdjustmentApiV1CompaniesTickerAdjustmentsPost,
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete,
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet,
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet,
  updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut,
} from "@/api/generated/sdk.gen";
import type { AdjustmentIn, AdjustmentOut, CorporateActionOut } from "@/api/generated/types.gen";

// The prefix of every ratios query of a company. S7's `analysis.ts` builds its ratio keys
// under it, so an adjustment change reaches them without this module knowing their shape.
export const ratiosKey = (ticker: string) => [...companyKey(ticker), "ratios"] as const;
export const adjustmentsKey = (ticker: string) => [...companyKey(ticker), "adjustments"] as const;
export const corporateActionsKey = (ticker: string) =>
  [...companyKey(ticker), "corporate-actions"] as const;

/**
 * GET …/adjustments (oldest fiscal year first, as the API orders it).
 * Rejects a 200 whose body is not an array with `ApiError(200, "Unexpected response")`
 * (Gotcha G2).
 */
export const adjustmentsQueryOptions = (ticker: string) =>
  queryOptions<AdjustmentOut[]>({
    queryKey: adjustmentsKey(ticker),
    queryFn: async () => {
      const list = await unwrap(
        listAdjustmentsApiV1CompaniesTickerAdjustmentsGet({ path: { ticker } }),
      );
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/**
 * GET …/corporate-actions (oldest first). Rejects a 200 whose body is not an array, as above.
 */
export const corporateActionsQueryOptions = (ticker: string) =>
  queryOptions<CorporateActionOut[]>({
    queryKey: corporateActionsKey(ticker),
    queryFn: async () => {
      const list = await unwrap(
        listCorporateActionsApiV1CompaniesTickerCorporateActionsGet({ path: { ticker } }),
      );
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/**
 * Marks stale everything an adjustment change can move for `ticker`: its statements (every
 * type, frequency and basis), cell details, the adjustments list, the ratios, the guidance log
 * and the comps comparisons. Nothing else (the company header, the list, the mapping gaps) is
 * touched.
 */
export function invalidateAdjustmentViews(queryClient: QueryClient, ticker: string): Promise<void> {
  const prefixes = [
    [...companyKey(ticker), "statements"],
    [...companyKey(ticker), "cell"],
    adjustmentsKey(ticker),
    ratiosKey(ticker),
    guidanceKey(ticker),
    compsKey(ticker),
  ];
  return Promise.all(prefixes.map((queryKey) => queryClient.invalidateQueries({ queryKey }))).then(
    () => undefined,
  );
}

/** POST …/adjustments with `body` (amount in USD units); on success invalidates as above. */
export function useCreateAdjustment(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<AdjustmentOut, Error, AdjustmentIn>({
    mutationFn: (body) =>
      unwrap(createAdjustmentApiV1CompaniesTickerAdjustmentsPost({ path: { ticker }, body })),
    onSuccess: () => invalidateAdjustmentViews(queryClient, ticker),
  });
}

/** PUT …/adjustments/{id} with `body`; on success invalidates as above. */
export function useUpdateAdjustment(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<AdjustmentOut, Error, { id: number; body: AdjustmentIn }>({
    mutationFn: ({ id, body }) =>
      unwrap(
        updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut({
          path: { ticker, adjustment_id: id },
          body,
        }),
      ),
    onSuccess: () => invalidateAdjustmentViews(queryClient, ticker),
  });
}

/** DELETE …/adjustments/{id}; on success invalidates as above. */
export function useDeleteAdjustment(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(
        deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete({
          path: { ticker, adjustment_id: id },
        }),
      ),
    onSuccess: () => invalidateAdjustmentViews(queryClient, ticker),
  });
}
