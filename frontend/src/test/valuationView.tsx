// The Valuation tab's test harness: a render on a query client and a router. Each test file mocks
// `@/api/generated/sdk.gen` itself (vi.mock is per file).
import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";

import { createQueryClient } from "@/lib/query-client";
import { LocationProbe } from "@/test/LocationProbe";

// The URL's query, as the view last left it.
export const seen = { search: "" };
const onSearch = (search: string) => {
  seen.search = search;
};

export function renderWithClient(ui: ReactNode, path = "/c/AAPL/valuation") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="c/:ticker/:tab?"
            element={
              <>
                {ui}
                <LocationProbe onSearch={onSearch} />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}
