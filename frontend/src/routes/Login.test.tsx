import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { loginApiV1AuthLoginPost, meApiV1AuthMeGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

import { Login } from "./Login";

vi.mock("@/api/generated/sdk.gen", () => ({
  loginApiV1AuthLoginPost: vi.fn(),
  meApiV1AuthMeGet: vi.fn(),
}));

function renderLogin() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<div>Home page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function submit(password = "pw") {
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Log in" }));
}

describe("Login", () => {
  beforeEach(() => {
    vi.mocked(meApiV1AuthMeGet).mockResolvedValue(okResult({ authenticated: true }) as never);
  });

  it("navigates home after a successful login", async () => {
    vi.mocked(loginApiV1AuthLoginPost).mockResolvedValue(okResult(undefined, 204) as never);
    renderLogin();

    await submit("secret");

    expect(await screen.findByText("Home page")).toBeInTheDocument();
    expect(loginApiV1AuthLoginPost).toHaveBeenCalledWith({ body: { password: "secret" } });
  });

  it("says the password is wrong on 401", async () => {
    vi.mocked(loginApiV1AuthLoginPost).mockResolvedValue(
      errorResult(401, { detail: "Unauthorized" }) as never,
    );
    renderLogin();

    await submit();

    expect(await screen.findByText("Incorrect password.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log in" })).toBeEnabled();
  });

  it("says to wait on 429", async () => {
    vi.mocked(loginApiV1AuthLoginPost).mockResolvedValue(
      errorResult(429, { detail: "Too Many Requests" }) as never,
    );
    renderLogin();

    await submit();

    expect(await screen.findByText("Too many attempts. Try again later.")).toBeInTheDocument();
  });

  it("does not blame the password for a server error", async () => {
    vi.mocked(loginApiV1AuthLoginPost).mockResolvedValue(
      errorResult(500, { detail: "Internal Server Error" }) as never,
    );
    renderLogin();

    await submit();

    expect(await screen.findByText("Could not log in. Try again.")).toBeInTheDocument();
    expect(screen.queryByText("Incorrect password.")).not.toBeInTheDocument();
  });

  it("reports a network failure and re-enables the button", async () => {
    vi.mocked(loginApiV1AuthLoginPost).mockResolvedValue(networkErrorResult() as never);
    renderLogin();

    await submit();

    expect(await screen.findByText("Could not log in. Try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log in" })).toBeEnabled();
  });

  it("re-enables the button even if the request itself rejects", async () => {
    vi.mocked(loginApiV1AuthLoginPost).mockRejectedValue(new TypeError("Failed to fetch"));
    renderLogin();

    await submit();

    expect(await screen.findByText("Could not log in. Try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log in" })).toBeEnabled();
  });
});
