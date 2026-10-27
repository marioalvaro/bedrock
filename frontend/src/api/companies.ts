import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, unwrap } from "@/api/errors";
import {
  addCompanyApiV1CompaniesPost,
  addManualCompanyApiV1CompaniesManualPost,
  getCompaniesApiV1CompaniesGet,
  getCompanyApiV1CompaniesTickerGet,
  refreshApiV1CompaniesTickerRefreshPost,
  removeCompanyApiV1CompaniesTickerDelete,
} from "@/api/generated/sdk.gen";
import type { ManualCompanyCreate } from "@/api/generated/types.gen";

// Every company-scoped query key starts with ["companies", ticker], so one prefix
// invalidation after a refresh reaches the list, the header, the statements and the gaps.
export const companiesQueryKey = ["companies"] as const;
export const companyKey = (ticker: string) => ["companies", ticker] as const;

export const companiesQueryOptions = queryOptions({
  queryKey: companiesQueryKey,
  queryFn: () => unwrap(getCompaniesApiV1CompaniesGet()),
});

export const companyQueryOptions = (ticker: string) =>
  queryOptions({
    queryKey: companyKey(ticker),
    queryFn: () => unwrap(getCompanyApiV1CompaniesTickerGet({ path: { ticker } })),
  });

// The API's reason for a failed company action (404/409/503/502 carry one), else a fallback.
export function companyErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

export function useAddCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) =>
      unwrap(addCompanyApiV1CompaniesPost({ body: { ticker: ticker.trim().toUpperCase() } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companiesQueryKey }),
  });
}

/** POST /companies/manual: a company SEC does not cover, filled by import (USD only). */
export function useAddManualCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ManualCompanyCreate) =>
      unwrap(addManualCompanyApiV1CompaniesManualPost({ body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companiesQueryKey }),
  });
}

export function useRemoveCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) =>
      unwrap(removeCompanyApiV1CompaniesTickerDelete({ path: { ticker } })),
    onSuccess: (_data, ticker) => {
      queryClient.removeQueries({ queryKey: companyKey(ticker) });
      return queryClient.invalidateQueries({ queryKey: companiesQueryKey });
    },
  });
}

export function useRefreshCompany(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(refreshApiV1CompaniesTickerRefreshPost({ path: { ticker } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companiesQueryKey }),
  });
}
