import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

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
    // The redirect to /login unmounted RequireAuth, so the cached "not
    // authenticated" answer is inactive; a default invalidate would only mark it
    // stale and RequireAuth would bounce back to /login. Refetch it regardless.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: authQueryKey, refetchType: "all" }),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(logoutApiV1AuthLogoutPost()),
    onSuccess: () => {
      // RequireAuth sees the change and redirects to /login.
      queryClient.setQueryData(authQueryKey, false);
    },
  });
}
