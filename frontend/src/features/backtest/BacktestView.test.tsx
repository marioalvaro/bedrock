// The Backtest tab: its three views, kept in ?view.
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBacktestApiV1CompaniesTickerBacktestGet,
  listAuditApiV1CompaniesTickerAuditGet,
  listSnapshotsApiV1CompaniesTickerSnapshotsGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";

import { BacktestView } from "./BacktestView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getBacktestApiV1CompaniesTickerBacktestGet: vi.fn(),
  listAuditApiV1CompaniesTickerAuditGet: vi.fn(),
  listSnapshotsApiV1CompaniesTickerSnapshotsGet: vi.fn(),
}));

const getBacktest = vi.mocked(getBacktestApiV1CompaniesTickerBacktestGet);
const listAudit = vi.mocked(listAuditApiV1CompaniesTickerAuditGet);
const listSnapshots = vi.mocked(listSnapshotsApiV1CompaniesTickerSnapshotsGet);

beforeEach(() => {
  for (const call of [getBacktest, listAudit, listSnapshots]) {
    call.mockReturnValue(new Promise(() => {}) as never);
  }
});
afterEach(() => vi.clearAllMocks());

let seen = { search: "", type: "" };
function Probe() {
  const { search } = useLocation();
  const type = useNavigationType();
  useEffect(() => {
    seen = { search, type };
  }, [search, type]);
  return null;
}

function renderView(path: string) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="c/:ticker/:tab"
            element={
              <>
                <BacktestView ticker="AAPL" />
                <Probe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const radio = (name: string) => screen.getByRole("radio", { name });
const checked = (name: string) => expect(radio(name)).toHaveAttribute("aria-checked", "true");

describe("BacktestView", () => {
  it("opens on the Backtest view", async () => {
    renderView("/c/AAPL/backtest");
    checked("Backtest");
    await waitFor(() => expect(getBacktest).toHaveBeenCalled());
    expect(listSnapshots).not.toHaveBeenCalled();
    expect(listAudit).not.toHaveBeenCalled();
  });

  it.each([
    ["snapshots", "Snapshots", listSnapshots],
    ["audit", "Audit log", listAudit],
  ])("opens ?view=%s", async (view, name, call) => {
    renderView(`/c/AAPL/backtest?view=${view}`);
    checked(name);
    await waitFor(() => expect(call).toHaveBeenCalled());
    expect(getBacktest).not.toHaveBeenCalled();
  });

  it("falls back to Backtest from an unknown view", async () => {
    renderView("/c/AAPL/backtest?view=nope");
    checked("Backtest");
    await waitFor(() => expect(getBacktest).toHaveBeenCalled());
  });

  it("writes the view with replace, keeping the other parameters", async () => {
    renderView("/c/AAPL/backtest?metric=cash");
    await userEvent.click(radio("Audit log"));
    const params = new URLSearchParams(seen.search);
    expect(params.get("view")).toBe("audit");
    expect(params.get("metric")).toBe("cash");
    expect(seen.type).toBe("REPLACE");
    checked("Audit log");
  });

  it("stays put when the current view is clicked again", async () => {
    renderView("/c/AAPL/backtest?view=snapshots");
    await userEvent.click(radio("Snapshots"));
    checked("Snapshots");
  });
});
