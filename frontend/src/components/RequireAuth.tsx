import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate } from "react-router";

import { meQueryOptions } from "@/api/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: authenticated, isLoading } = useQuery(meQueryOptions);

  if (isLoading) {
    return null;
  }

  if (!authenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}
