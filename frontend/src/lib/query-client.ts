import { QueryCache, QueryClient } from "@tanstack/react-query";

import { setAuthenticated } from "@/api/auth";
import { ApiError, isUnauthorized } from "@/api/errors";

const MAX_RETRIES = 3;
const STALE_MS = 5 * 60_000;

export function createQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // Any query hitting 401 means the session is gone (e.g. idle expiry).
      onError: (error) => {
        if (isUnauthorized(error)) {
          setAuthenticated(queryClient, false);
        }
      },
    }),
    defaultOptions: {
      queries: {
        // Data changes only through this app's mutations, which invalidate the keys they touch
        // (every company key starts with ["companies", ticker]), and the hourly price refresh.
        // A tab switch, a remount or a window focus must not re-run the backend's statement
        // builds and forecasts (NFR-02); price-driven figures may lag by up to STALE_MS.
        staleTime: STALE_MS,
        refetchOnWindowFocus: false,
        // Client errors will not change on retry; only retry network and 5xx.
        retry: (failureCount, error) =>
          failureCount < MAX_RETRIES &&
          !(error instanceof ApiError && error.status !== undefined && error.status < 500),
      },
    },
  });
  return queryClient;
}
