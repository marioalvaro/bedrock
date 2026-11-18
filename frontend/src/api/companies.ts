import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, unwrap } from "@/api/errors";
import {
  addCompanyApiV1CompaniesPost,
  addManualCompanyApiV1CompaniesManualPost,
  archiveCompanyApiV1CompaniesTickerArchivePost,
  backfillFilingsApiV1CompaniesTickerBackfillFilingsPost,
  deletionImpactApiV1CompaniesTickerDeletionImpactGet,
  getCompaniesApiV1CompaniesGet,
  getCompanyApiV1CompaniesTickerGet,
  refreshApiV1CompaniesTickerRefreshPost,
  removeCompanyApiV1CompaniesTickerDelete,
  restoreCompanyApiV1CompaniesTickerRestorePost,
} from "@/api/generated/sdk.gen";
import type {
  CompanyListItem,
  DeletionImpactOut,
  ManualCompanyCreate,
} from "@/api/generated/types.gen";

// Every company-scoped query key starts with ["companies", ticker], so one prefix
// invalidation after a refresh reaches the list, the header, the statements and the gaps.
export const companiesQueryKey = ["companies"] as const;
export const companyKey = (ticker: string) => ["companies", ticker] as const;

// The backend refreshes prices hourly in US market hours (core/scheduler.py): an open page polls
// so the shown price follows. React Query pauses the poll while the tab is in the background.
const PRICE_POLL_MS = 15 * 60_000;

export const companiesQueryOptions = queryOptions({
  queryKey: companiesQueryKey,
  queryFn: () => unwrap(getCompaniesApiV1CompaniesGet()),
  refetchInterval: PRICE_POLL_MS,
});

/** GET /companies?archived=true (FR-WS-07): the archived companies, under the companies prefix
 * so every list invalidation reaches it. Rejects a 200 that is not a list (G2/G4). */
export const archivedCompaniesQueryOptions = queryOptions<CompanyListItem[]>({
  queryKey: [...companiesQueryKey, "archived"],
  queryFn: async () => {
    const list = await unwrap(getCompaniesApiV1CompaniesGet({ query: { archived: true } }));
    if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
    return list;
  },
});

/** GET …/deletion-impact (FR-WS-07): the row counts a permanent delete removes, read fresh each
 * time the dialog opens. Rejects a 200 without the counts (G2/G4). */
export const deletionImpactQueryOptions = (ticker: string) =>
  queryOptions<DeletionImpactOut>({
    queryKey: [...companyKey(ticker), "deletion-impact"],
    staleTime: 0,
    queryFn: async () => {
      const counts = await unwrap(
        deletionImpactApiV1CompaniesTickerDeletionImpactGet({ path: { ticker } }),
      );
      if (typeof counts?.facts !== "number") throw new ApiError(200, "Unexpected response");
      return counts;
    },
  });

export const companyQueryOptions = (ticker: string) =>
  queryOptions({
    queryKey: companyKey(ticker),
    queryFn: () => unwrap(getCompanyApiV1CompaniesTickerGet({ path: { ticker } })),
    refetchInterval: PRICE_POLL_MS,
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
      // The followed and the archived list both sit under the prefix.
      return queryClient.invalidateQueries({ queryKey: companiesQueryKey });
    },
  });
}

/** POST …/archive (FR-WS-07): the company leaves the list and its refreshes stop; nothing is
 * deleted. The companies prefix covers both lists. */
export function useArchiveCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) =>
      unwrap(archiveCompanyApiV1CompaniesTickerArchivePost({ path: { ticker } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companiesQueryKey }),
  });
}

/** POST …/restore (FR-WS-07): back on the followed list, with no re-ingestion. */
export function useRestoreCompany() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) =>
      unwrap(restoreCompanyApiV1CompaniesTickerRestorePost({ path: { ticker } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companiesQueryKey }),
  });
}

export function useRefreshCompany(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(refreshApiV1CompaniesTickerRefreshPost({ path: { ticker } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companiesQueryKey }),
  });
}

/** POST …/backfill-filings (202): reads every 10-K and 10-Q not read yet, in a worker thread. A 409
 * means a backfill already runs for the company; either way, progress is `filings_parsed`. */
export function useBackfillFilings(ticker: string) {
  return useMutation({
    mutationFn: () =>
      unwrap(backfillFilingsApiV1CompaniesTickerBackfillFilingsPost({ path: { ticker } })),
  });
}
