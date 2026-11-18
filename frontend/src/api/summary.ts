import { queryOptions } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import { getSummaryApiV1CompaniesTickerSummaryGet } from "@/api/generated/sdk.gen";
import type { CompanySummaryOut } from "@/api/generated/types.gen";

// Under `companyKey`, so the refresh's invalidation of the companies prefix reloads it.
export const summaryKey = (ticker: string) => [...companyKey(ticker), "summary"] as const;

/** GET …/summary (FR-WS-04): the Overview's blocks, computed on read. Rejects a wrong-shape 200
 * (G2/G4). */
export const summaryQueryOptions = (ticker: string) =>
  queryOptions<CompanySummaryOut>({
    queryKey: summaryKey(ticker),
    queryFn: async () => {
      const summary = await unwrap(getSummaryApiV1CompaniesTickerSummaryGet({ path: { ticker } }));
      const lists = [summary?.metrics, summary?.flags, summary?.notes, summary?.warnings];
      // A block that could not run is null; a missing key is not a summary.
      const blocks = [summary?.valuation, summary?.forecast];
      if (!lists.every(Array.isArray) || blocks.some((block) => block === undefined)) {
        throw new ApiError(200, "Unexpected response");
      }
      return summary;
    },
  });
