import {
  infiniteQueryOptions,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  createSnapshotApiV1CompaniesTickerScenariosScenarioIdSnapshotsPost,
  getBacktestApiV1CompaniesTickerBacktestGet,
  getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet,
  listAuditApiV1CompaniesTickerAuditGet,
  listSnapshotsApiV1CompaniesTickerSnapshotsGet,
  runBacktestApiV1CompaniesTickerBacktestPost,
  setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch,
} from "@/api/generated/sdk.gen";
import type {
  AuditPageOut,
  AuditRowOut,
  BacktestOut,
  SnapshotDetailOut,
  SnapshotListOut,
  SnapshotOut,
} from "@/api/generated/types.gen";

export type AuditFilter = AuditRowOut["entity"] | "all";

export const snapshotsKey = (ticker: string) => [...companyKey(ticker), "snapshots"] as const;
export const backtestKey = (ticker: string) => [...companyKey(ticker), "backtest"] as const;
export const auditKey = (ticker: string) => [...companyKey(ticker), "audit"] as const;

const unexpected = () => new ApiError(200, "Unexpected response");

function checkedBacktest(view: BacktestOut): BacktestOut {
  if (!Array.isArray(view?.origins) || !Array.isArray(view?.summary)) throw unexpected();
  return view;
}

// All four reads are `staleTime: 0`: the writes that feed them (a driver edit, a refresh) happen
// on other tabs and do not invalidate them, so each view reloads on arrival.

/** GET …/snapshots: newest first, with the scores over all of them. Rejects a wrong-shape 200 (G2/G4). */
export const snapshotsQueryOptions = (ticker: string) =>
  queryOptions<SnapshotListOut>({
    queryKey: snapshotsKey(ticker),
    staleTime: 0,
    queryFn: async () => {
      const view = await unwrap(
        listSnapshotsApiV1CompaniesTickerSnapshotsGet({ path: { ticker } }),
      );
      if (!Array.isArray(view?.snapshots) || !Array.isArray(view?.summary)) throw unexpected();
      return view;
    },
  });

/** GET …/snapshots/{id}: the frozen cases, scored against the latest actuals. */
export const snapshotQueryOptions = (ticker: string, id: number) =>
  queryOptions<SnapshotDetailOut>({
    queryKey: [...snapshotsKey(ticker), id],
    staleTime: 0,
    queryFn: async () => {
      const view = await unwrap(
        getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet({
          path: { ticker, snapshot_id: id },
        }),
      );
      if (!Array.isArray(view?.cases)) throw unexpected();
      return view;
    },
  });

/** GET …/backtest: the last run's origins and scores; `ran_at` null before the first run. */
export const backtestQueryOptions = (ticker: string) =>
  queryOptions<BacktestOut>({
    queryKey: backtestKey(ticker),
    staleTime: 0,
    queryFn: async () =>
      checkedBacktest(
        await unwrap(getBacktestApiV1CompaniesTickerBacktestGet({ path: { ticker } })),
      ),
  });

/** GET …/audit, newest first, one page at a time through `next_before_id`. */
export const auditInfiniteOptions = (ticker: string, entity: AuditFilter) =>
  infiniteQueryOptions({
    queryKey: [...auditKey(ticker), entity],
    staleTime: 0,
    initialPageParam: null as number | null,
    getNextPageParam: (last: AuditPageOut) => last.next_before_id,
    queryFn: async ({ pageParam }): Promise<AuditPageOut> => {
      const page = await unwrap(
        listAuditApiV1CompaniesTickerAuditGet({
          path: { ticker },
          query: {
            ...(entity !== "all" && { entity }),
            ...(pageParam !== null && { before_id: pageParam }),
          },
        }),
      );
      if (!Array.isArray(page?.rows)) throw unexpected();
      return page;
    },
  });

/** POST …/scenarios/{id}/snapshots with an optional note. */
export function useCreateSnapshot(ticker: string, scenarioId: number) {
  const queryClient = useQueryClient();
  return useMutation<SnapshotOut, Error, string | null>({
    mutationFn: async (note) => {
      const saved = await unwrap(
        createSnapshotApiV1CompaniesTickerScenariosScenarioIdSnapshotsPost({
          path: { ticker, scenario_id: scenarioId },
          body: { note },
        }),
      );
      if (typeof saved?.id !== "number") throw unexpected();
      return saved;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: snapshotsKey(ticker) }),
  });
}

/** POST …/backtest (about 15 s); the reply replaces the backtest query. */
export function useRunBacktest(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<BacktestOut, Error, void>({
    mutationFn: async () =>
      checkedBacktest(
        await unwrap(runBacktestApiV1CompaniesTickerBacktestPost({ path: { ticker } })),
      ),
    onSuccess: (view) => queryClient.setQueryData(backtestKey(ticker), view),
  });
}

/** PATCH …/audit/{id}; a null rationale clears it. */
export function useSetRationale(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<AuditRowOut, Error, { id: number; rationale: string | null }>({
    mutationFn: async ({ id, rationale }) => {
      const row = await unwrap(
        setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch({
          path: { ticker, row_id: id },
          body: { rationale },
        }),
      );
      if (typeof row?.id !== "number") throw unexpected();
      return row;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: auditKey(ticker) }),
  });
}
