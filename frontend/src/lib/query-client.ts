import { QueryCache, QueryClient } from "@tanstack/react-query";

import { setAuthenticated } from "@/api/auth";
import { ApiError, isUnauthorized } from "@/api/errors";

const MAX_RETRIES = 3;

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
        // Client errors will not change on retry; only retry network and 5xx.
        retry: (failureCount, error) =>
          failureCount < MAX_RETRIES &&
          !(error instanceof ApiError && error.status !== undefined && error.status < 500),
      },
    },
  });
  return queryClient;
}
