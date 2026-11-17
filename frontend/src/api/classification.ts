import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  answerApiV1CompaniesTickerClassificationsPut,
  decideApiV1CompaniesTickerClassificationsClassificationIdPut,
  getClassificationsOfApiV1CompaniesTickerClassificationsGet,
  getStatusApiV1ClassificationStatusGet,
  setModeApiV1CompaniesTickerClassificationModePut,
  startRunApiV1CompaniesTickerClassificationsRunPost,
} from "@/api/generated/sdk.gen";
import type {
  AnswerIn,
  ClassificationOut,
  ClassificationRunOut,
  ClassificationsOut,
  ClassificationStatusOut,
  CompanyListItem,
  DecisionIn,
  ModeIn,
  RunIn,
} from "@/api/generated/types.gen";

// M7d S5 (docs/erd/face-tree.md "Frontend (S5)"). No GET here calls a classifier: only
// `useStartRun` does, from the user's confirmation (principle 3).

// The usage and budgets belong to the app, not to a company.
export const classificationStatusKey = ["classification-status"] as const;
export const classificationsKey = (ticker: string) =>
  [...companyKey(ticker), "classifications"] as const;

// While the newest run is `running`, the panel refetches every 2 seconds.
export const RUN_POLL_MS = 2_000;

/** GET /classification/status: which classifiers have a key, and the tokens used and allowed. */
export const classificationStatusQueryOptions = () =>
  queryOptions<ClassificationStatusOut>({
    queryKey: classificationStatusKey,
    queryFn: async () => {
      const status = await unwrap(getStatusApiV1ClassificationStatusGet());
      if (!Array.isArray(status?.classifiers)) throw new ApiError(200, "Unexpected response");
      return status;
    },
  });

/** GET …/classifications: the open lines with their answers; with `classifier`, also what a
 * run of it would ask now (`to_ask`) and its estimate. Polls while the newest run is running. */
export const classificationsQueryOptions = (
  ticker: string,
  classifier: string | null,
  pollMs: number = RUN_POLL_MS,
) =>
  queryOptions<ClassificationsOut>({
    queryKey: [...classificationsKey(ticker), classifier],
    queryFn: async () => {
      const list = await unwrap(
        getClassificationsOfApiV1CompaniesTickerClassificationsGet({
          path: { ticker },
          query: classifier === null ? {} : { classifier },
        }),
      );
      if (!Array.isArray(list?.lines)) throw new ApiError(200, "Unexpected response");
      return list;
    },
    refetchInterval: (query) => (query.state.data?.run?.status === "running" ? pollMs : false),
  });

/** Marks stale every view of the company (an accepted answer or a mode change can fill cells
 * anywhere the actuals are read) and the app's usage. Another company's views stay. */
export function invalidateClassificationViews(
  queryClient: QueryClient,
  ticker: string,
): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: companyKey(ticker) }),
    queryClient.invalidateQueries({ queryKey: classificationStatusKey }),
  ]).then(() => undefined);
}

/** POST …/classifications/run (202). Success or not, the list and the usage are refetched: a
 * 409 means what would be asked has changed since the confirmation. */
export function useStartRun(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<ClassificationRunOut, Error, RunIn>({
    mutationFn: (body) =>
      unwrap(startRunApiV1CompaniesTickerClassificationsRunPost({ path: { ticker }, body })),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: classificationsKey(ticker) }),
        queryClient.invalidateQueries({ queryKey: classificationStatusKey }),
      ]),
  });
}

/** PUT …/classifications/{id}: accept, reject or reopen one answer. */
export function useDecideClassification(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<ClassificationOut, Error, { id: number } & DecisionIn>({
    mutationFn: ({ id, status }) =>
      unwrap(
        decideApiV1CompaniesTickerClassificationsClassificationIdPut({
          path: { ticker, classification_id: id },
          body: { status },
        }),
      ),
    onSuccess: () => invalidateClassificationViews(queryClient, ticker),
  });
}

/** PUT …/classifications: the user's own answer for a line, stored accepted. */
export function useAnswerLine(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<ClassificationOut, Error, AnswerIn>({
    mutationFn: (body) =>
      unwrap(answerApiV1CompaniesTickerClassificationsPut({ path: { ticker }, body })),
    onSuccess: () => invalidateClassificationViews(queryClient, ticker),
  });
}

/** PUT …/classification-mode: what of the classifications the company's statements use. */
export function useSetClassificationMode(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<CompanyListItem, Error, ModeIn>({
    mutationFn: (body) =>
      unwrap(setModeApiV1CompaniesTickerClassificationModePut({ path: { ticker }, body })),
    onSuccess: () => invalidateClassificationViews(queryClient, ticker),
  });
}
