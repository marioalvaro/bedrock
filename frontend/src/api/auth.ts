import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { ApiError, unwrap } from "@/api/errors";
import {
  loginApiV1AuthLoginPost,
  logoutApiV1AuthLogoutPost,
  meApiV1AuthMeGet,
} from "@/api/generated/sdk.gen";

export const authQueryKey = ["auth", "me"] as const;

export const meQueryOptions = queryOptions({
  queryKey: authQueryKey,
  queryFn: async () => {
    const { data } = await meApiV1AuthMeGet();
    // Decide from the body, not the status: see Gotcha G2.
    return data?.authenticated === true;
  },
  retry: false,
});

// The one place the cached session state changes outside /me: a login's 204, a
// logout, or any 401. RequireAuth re-renders from it and redirects as needed.
export function setAuthenticated(queryClient: QueryClient, authenticated: boolean): void {
  queryClient.setQueryData(authQueryKey, authenticated);
}

export function loginErrorMessage(error: unknown): string {
  const status = error instanceof ApiError ? error.status : undefined;
  if (status === 401) return "Incorrect password.";
  if (status === 429) return "Too many attempts. Try again later.";
  return "Could not log in. Try again.";
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => unwrap(loginApiV1AuthLoginPost({ body: { password } })),
    // A 204 to a POST is the server's answer (G2's 200 fallback only hits GETs).
    onSuccess: () => setAuthenticated(queryClient, true),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(logoutApiV1AuthLogoutPost()),
    onSuccess: () => setAuthenticated(queryClient, false),
  });
}
