import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  createCheckpointApiV1CompaniesTickerCheckpointsPost,
  deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete,
  listCheckpointsApiV1CompaniesTickerCheckpointsGet,
  updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut,
} from "@/api/generated/sdk.gen";
import type { CheckpointIn, CheckpointListOut, CheckpointOut } from "@/api/generated/types.gen";

// Under `companyKey`, so the refresh's invalidation of the companies prefix reloads it.
export const checkpointsKey = (ticker: string) => [...companyKey(ticker), "checkpoints"] as const;

const unexpected = () => new ApiError(200, "Unexpected response");

function checked(saved: CheckpointOut): CheckpointOut {
  if (typeof saved?.id !== "number") throw unexpected();
  return saved;
}

/** GET …/checkpoints: each checkpoint with its state now and before the newest report. */
export const checkpointsQueryOptions = (ticker: string) =>
  queryOptions<CheckpointListOut>({
    queryKey: checkpointsKey(ticker),
    staleTime: 0,
    queryFn: async () => {
      const view = await unwrap(
        listCheckpointsApiV1CompaniesTickerCheckpointsGet({ path: { ticker } }),
      );
      if (!Array.isArray(view?.checkpoints)) throw unexpected();
      return view;
    },
  });

/** POST …/checkpoints; a statement that does not parse is a 422 whose detail names the position. */
export function useCreateCheckpoint(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<CheckpointOut, Error, CheckpointIn>({
    mutationFn: async (body) =>
      checked(
        await unwrap(
          createCheckpointApiV1CompaniesTickerCheckpointsPost({ path: { ticker }, body }),
        ),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: checkpointsKey(ticker) }),
  });
}

/** PUT …/checkpoints/{id} with the whole body. */
export function useUpdateCheckpoint(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<CheckpointOut, Error, { id: number; body: CheckpointIn }>({
    mutationFn: async ({ id, body }) =>
      checked(
        await unwrap(
          updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut({
            path: { ticker, checkpoint_id: id },
            body,
          }),
        ),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: checkpointsKey(ticker) }),
  });
}

/** DELETE …/checkpoints/{id} (204). */
export function useDeleteCheckpoint(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await unwrap(
        deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete({
          path: { ticker, checkpoint_id: id },
        }),
      );
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: checkpointsKey(ticker) }),
  });
}
