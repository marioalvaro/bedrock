import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { meApiV1AuthMeGet } from "@/api/generated/sdk.gen";

import { RequireAuth } from "./RequireAuth";

vi.mock("@/api/generated/sdk.gen", () => ({
  meApiV1AuthMeGet: vi.fn(),
}));

function renderWithProviders() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/login" element={<div>Login page</div>} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <div>Protected content</div>
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RequireAuth", () => {
  it("redirects to /login when the session check returns 401", async () => {
    vi.mocked(meApiV1AuthMeGet).mockResolvedValue({ response: { status: 401 } } as never);

    renderWithProviders();

    expect(await screen.findByText("Login page")).toBeInTheDocument();
  });

  it("redirects to /login when a 200 response is not an authenticated session", async () => {
    // e.g. the dev server's SPA fallback answering a mis-routed request with index.html
    vi.mocked(meApiV1AuthMeGet).mockResolvedValue({
      data: "<!doctype html>",
      response: { status: 200 },
    } as never);

    renderWithProviders();

    expect(await screen.findByText("Login page")).toBeInTheDocument();
  });

  it("renders children when the session check confirms authentication", async () => {
    vi.mocked(meApiV1AuthMeGet).mockResolvedValue({
      data: { authenticated: true },
      response: { status: 200 },
    } as never);

    renderWithProviders();

    expect(await screen.findByText("Protected content")).toBeInTheDocument();
  });
});
