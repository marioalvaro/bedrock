import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCompaniesApiV1CompaniesGet,
  loginApiV1AuthLoginPost,
  logoutApiV1AuthLogoutPost,
  meApiV1AuthMeGet,
} from "@/api/generated/sdk.gen";
import { AppRoutes } from "@/App";
import { createQueryClient } from "@/lib/query-client";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
  loginApiV1AuthLoginPost: vi.fn(),
  logoutApiV1AuthLogoutPost: vi.fn(),
  meApiV1AuthMeGet: vi.fn(),
}));

function renderAt(path: string, queryClient = createQueryClient()) {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const loginButton = () => screen.findByRole("button", { name: "Log in" });

describe("protected routes", () => {
  beforeEach(() => {
    vi.mocked(meApiV1AuthMeGet).mockResolvedValue(okResult({ authenticated: true }) as never);
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(okResult([]) as never);
  });

  it.each(["/", "/settings", "/c/AAPL"])(
    "redirects %s to /login without a session",
    async (path) => {
      vi.mocked(meApiV1AuthMeGet).mockResolvedValue(errorResult(401) as never);

      renderAt(path);

      expect(await loginButton()).toBeInTheDocument();
    },
  );

  it("renders the header around the protected page", async () => {
    renderAt("/settings");

    expect(await screen.findByText("Theme")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Companies" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
  });

  it("renders the company page for a ticker", async () => {
    renderAt("/c/AAPL");

    expect(await screen.findByText("AAPL overview arrives in M1.")).toBeInTheDocument();
  });

  it("sends the user to /login when a data query gets a 401", async () => {
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(errorResult(401) as never);

    renderAt("/");

    expect(await loginButton()).toBeInTheDocument();
    expect(screen.queryByText(/No companies yet/)).not.toBeInTheDocument();
  });

  it("shows an error instead of an empty list when companies fail to load", async () => {
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(errorResult(500) as never);
    // 5xx is retried with backoff in the app; skip the wait here.
    const queryClient = createQueryClient();
    queryClient.setQueryDefaults(["companies"], { retry: false });

    renderAt("/", queryClient);

    expect(await screen.findByText("Could not load companies.")).toBeInTheDocument();
    expect(screen.queryByText(/No companies yet/)).not.toBeInTheDocument();
  });

  it("lists companies from the API", async () => {
    vi.mocked(getCompaniesApiV1CompaniesGet).mockResolvedValue(
      okResult([
        {
          id: 1,
          ticker: "AAPL",
          cik: "0000320193",
          name: "Apple Inc.",
          fiscal_year_end_month: 9,
          currency: "USD",
          sic: "3571",
          last_refreshed_at: null,
        },
      ]) as never,
    );

    renderAt("/");

    expect(await screen.findByRole("link", { name: "AAPL — Apple Inc." })).toBeInTheDocument();
  });

  it("logs out and lands on /login", async () => {
    vi.mocked(logoutApiV1AuthLogoutPost).mockResolvedValue(okResult(undefined, 204) as never);
    renderAt("/settings");

    await userEvent.click(await screen.findByRole("button", { name: "Log out" }));

    expect(await loginButton()).toBeInTheDocument();
    expect(logoutApiV1AuthLogoutPost).toHaveBeenCalled();
  });

  it("reaches the app on the first login after being redirected to /login", async () => {
    // The redirect leaves a cached "not authenticated" answer with no observer;
    // login must refresh it before RequireAuth reads it again.
    vi.mocked(meApiV1AuthMeGet).mockResolvedValue(errorResult(401) as never);
    renderAt("/settings");
    await loginButton();

    vi.mocked(loginApiV1AuthLoginPost).mockResolvedValue(okResult(undefined, 204) as never);
    vi.mocked(meApiV1AuthMeGet).mockResolvedValue(okResult({ authenticated: true }) as never);
    await userEvent.type(screen.getByLabelText("Password"), "secret");
    await userEvent.click(await loginButton());

    expect(await screen.findByRole("button", { name: "Log out" })).toBeInTheDocument();
  });
});
