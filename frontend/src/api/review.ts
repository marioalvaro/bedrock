import { queryOptions } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import { getEarningsReviewApiV1CompaniesTickerEarningsReviewGet } from "@/api/generated/sdk.gen";
import type { EarningsReviewOut } from "@/api/generated/types.gen";

// Under `companyKey`, so the refresh's invalidation of the companies prefix reloads it.
export const reviewKey = (ticker: string) => [...companyKey(ticker), "review"] as const;

/** GET …/earnings-review: the newest 10-K or 10-Q against the snapshot taken before it. `staleTime`
 * 0: a refresh or a guidance entry made elsewhere shows on arrival. Rejects a wrong-shape 200
 * (G2/G4). */
export const reviewQueryOptions = (ticker: string) =>
  queryOptions<EarningsReviewOut>({
    queryKey: reviewKey(ticker),
    staleTime: 0,
    queryFn: async () => {
      const view = await unwrap(
        getEarningsReviewApiV1CompaniesTickerEarningsReviewGet({ path: { ticker } }),
      );
      const lists = [view?.lines, view?.drivers, view?.restated, view?.flags, view?.checkpoints];
      if (!lists.every(Array.isArray)) throw new ApiError(200, "Unexpected response");
      return view;
    },
  });
