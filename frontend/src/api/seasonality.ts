import { queryOptions } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import { getSeasonalityApiV1CompaniesTickerSeasonalityGet } from "@/api/generated/sdk.gen";
import type { SeasonalityOut } from "@/api/generated/types.gen";

export const seasonalityKey = (ticker: string) => [...companyKey(ticker), "seasonality"] as const;

const LISTS = ["lines", "periods", "observed", "trend", "seasonal", "residual", "factors"] as const;

/**
 * GET /companies/{ticker}/seasonality?code=: the STL decomposition of one quarterly IS or CF line.
 * While another line of the same company loads, the previous one stays as placeholder data, so
 * the charts stay mounted (G32). Rejects a 200 without its lists (G2/G4); a 422 rejects with its
 * `detail`.
 */
export const seasonalityQueryOptions = (ticker: string, code: string) => {
  const scope = seasonalityKey(ticker);
  return queryOptions<SeasonalityOut>({
    queryKey: [...scope, code],
    placeholderData: (previous, previousQuery) =>
      scope.every((part, index) => previousQuery?.queryKey[index] === part) ? previous : undefined,
    queryFn: async () => {
      const view = await unwrap(
        getSeasonalityApiV1CompaniesTickerSeasonalityGet({ path: { ticker }, query: { code } }),
      );
      if (LISTS.some((key) => !Array.isArray(view?.[key])) || typeof view?.strength !== "number") {
        throw new ApiError(200, "Unexpected response");
      }
      return view;
    },
  });
};
