import { QueryClient, QueryClientProvider, useInfiniteQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  auditInfiniteOptions,
  auditKey,
  backtestKey,
  backtestQueryOptions,
  snapshotQueryOptions,
  snapshotsKey,
  snapshotsQueryOptions,
  useCreateSnapshot,
  useRunBacktest,
  useSetRationale,
} from "@/api/accountability";
import { companyKey } from "@/api/companies";
import {
  createSnapshotApiV1CompaniesTickerScenariosScenarioIdSnapshotsPost,
  getBacktestApiV1CompaniesTickerBacktestGet,
  getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet,
  listAuditApiV1CompaniesTickerAuditGet,
  listSnapshotsApiV1CompaniesTickerSnapshotsGet,
  runBacktestApiV1CompaniesTickerBacktestPost,
  setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch,
} from "@/api/generated/sdk.gen";
import {
  auditPage,
  auditRow,
  backtest,
  noBacktest,
  snapshotDetail,
  snapshotList,
  snapshotOut,
} from "@/test/accountability";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  createSnapshotApiV1CompaniesTickerScenariosScenarioIdSnapshotsPost: vi.fn(),
  getBacktestApiV1CompaniesTickerBacktestGet: vi.fn(),
  getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet: vi.fn(),
  listAuditApiV1CompaniesTickerAuditGet: vi.fn(),
  listSnapshotsApiV1CompaniesTickerSnapshotsGet: vi.fn(),
  runBacktestApiV1CompaniesTickerBacktestPost: vi.fn(),
  setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch: vi.fn(),
}));

const createSnapshot = vi.mocked(
  createSnapshotApiV1CompaniesTickerScenariosScenarioIdSnapshotsPost,
);
const getBacktest = vi.mocked(getBacktestApiV1CompaniesTickerBacktestGet);
const getSnapshot = vi.mocked(getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet);
const listAudit = vi.mocked(listAuditApiV1CompaniesTickerAuditGet);
const listSnapshots = vi.mocked(listSnapshotsApiV1CompaniesTickerSnapshotsGet);
const runBacktest = vi.mocked(runBacktestApiV1CompaniesTickerBacktestPost);
const setRationale = vi.mocked(setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch);

afterEach(() => vi.clearAllMocks());

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

const HTML = "<!doctype html><html></html>";

describe("keys", () => {
  it("sit under the company", () => {
    expect(snapshotsKey("AAPL")).toEqual([...companyKey("AAPL"), "snapshots"]);
    expect(backtestKey("AAPL")).toEqual([...companyKey("AAPL"), "backtest"]);
    expect(auditKey("AAPL")).toEqual([...companyKey("AAPL"), "audit"]);
    expect(snapshotsQueryOptions("AAPL").queryKey).toEqual(snapshotsKey("AAPL"));
    expect(snapshotQueryOptions("AAPL", 7).queryKey).toEqual([...snapshotsKey("AAPL"), 7]);
    expect(backtestQueryOptions("AAPL").queryKey).toEqual(backtestKey("AAPL"));
    expect(auditInfiniteOptions("AAPL", "driver").queryKey).toEqual([
      ...auditKey("AAPL"),
      "driver",
    ]);
  });

  it("are always stale, so a change made on another tab shows on arrival", () => {
    expect(snapshotsQueryOptions("AAPL").staleTime).toBe(0);
    expect(snapshotQueryOptions("AAPL", 7).staleTime).toBe(0);
    expect(backtestQueryOptions("AAPL").staleTime).toBe(0);
    expect(auditInfiniteOptions("AAPL", "all").staleTime).toBe(0);
  });
});

describe("reads", () => {
  it("loads the snapshots of the company", async () => {
    listSnapshots.mockResolvedValue(okResult(snapshotList()) as never);
    const data = await setup().queryClient.fetchQuery(snapshotsQueryOptions("AAPL"));
    expect(listSnapshots).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(data.snapshots).toHaveLength(2);
  });

  it("loads one snapshot by id", async () => {
    getSnapshot.mockResolvedValue(okResult(snapshotDetail()) as never);
    const data = await setup().queryClient.fetchQuery(snapshotQueryOptions("AAPL", 7));
    expect(getSnapshot).toHaveBeenCalledWith({ path: { ticker: "AAPL", snapshot_id: 7 } });
    expect(data.cases).toHaveLength(3);
  });

  it("loads the backtest, also before the first run", async () => {
    getBacktest.mockResolvedValue(okResult(noBacktest()) as never);
    const data = await setup().queryClient.fetchQuery(backtestQueryOptions("AAPL"));
    expect(getBacktest).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(data.ran_at).toBeNull();
  });

  it.each([
    ["an HTML shell", HTML],
    ["no summary", { snapshots: [] }],
    ["no snapshots", { summary: [] }],
  ])("rejects a 200 of snapshots with %s (G2/G4)", async (_name, body) => {
    listSnapshots.mockResolvedValue(okResult(body) as never);
    await expect(
      setup().queryClient.fetchQuery(snapshotsQueryOptions("AAPL")),
    ).rejects.toMatchObject({ status: 200 });
  });

  it.each([
    ["an HTML shell", HTML],
    ["no cases", { id: 7 }],
  ])("rejects a 200 of a snapshot with %s (G2/G4)", async (_name, body) => {
    getSnapshot.mockResolvedValue(okResult(body) as never);
    await expect(
      setup().queryClient.fetchQuery(snapshotQueryOptions("AAPL", 7)),
    ).rejects.toMatchObject({ status: 200 });
  });

  it.each([
    ["an HTML shell", HTML],
    ["no origins", { summary: [] }],
    ["no summary", { origins: [] }],
  ])("rejects a 200 of the backtest with %s (G2/G4)", async (_name, body) => {
    getBacktest.mockResolvedValue(okResult(body) as never);
    await expect(
      setup().queryClient.fetchQuery(backtestQueryOptions("AAPL")),
    ).rejects.toMatchObject({ status: 200 });
  });

  it("carries a read's 422 detail", async () => {
    listSnapshots.mockResolvedValue(errorResult(422, { detail: "Nope" }) as never);
    await expect(
      setup().queryClient.fetchQuery(snapshotsQueryOptions("AAPL")),
    ).rejects.toMatchObject({ status: 422, detail: "Nope" });
  });
});

describe("the audit pages", () => {
  function renderAudit(entity: Parameters<typeof auditInfiniteOptions>[1]) {
    const { wrapper } = setup();
    return renderHook(() => useInfiniteQuery(auditInfiniteOptions("AAPL", entity)), { wrapper });
  }

  it("asks every change type with no filter and no cursor", async () => {
    listAudit.mockResolvedValue(okResult(auditPage()) as never);
    const { result } = renderAudit("all");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listAudit).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, query: {} });
    expect(result.current.hasNextPage).toBe(false);
  });

  it("sends the filter and follows next_before_id", async () => {
    listAudit
      .mockResolvedValueOnce(okResult(auditPage({ next_before_id: 41 })) as never)
      .mockResolvedValueOnce(okResult(auditPage({ rows: [auditRow({ id: 40 })] })) as never);
    const { result } = renderAudit("engine_choice");
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    expect(listAudit).toHaveBeenLastCalledWith({
      path: { ticker: "AAPL" },
      query: { entity: "engine_choice" },
    });
    await act(() => result.current.fetchNextPage());
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(listAudit).toHaveBeenLastCalledWith({
      path: { ticker: "AAPL" },
      query: { entity: "engine_choice", before_id: 41 },
    });
    expect(result.current.hasNextPage).toBe(false);
  });

  it("rejects a 200 without rows (G2/G4)", async () => {
    listAudit.mockResolvedValue(okResult(HTML) as never);
    const { result } = renderAudit("all");
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 200 });
  });
});

describe("useCreateSnapshot", () => {
  it("posts the note and invalidates the snapshots", async () => {
    createSnapshot.mockResolvedValue(okResult(snapshotOut(), 201) as never);
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useCreateSnapshot("AAPL", 1), { wrapper });
    await act(() => result.current.mutateAsync("Before the print"));
    expect(createSnapshot).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1 },
      body: { note: "Before the print" },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: snapshotsKey("AAPL") });
  });

  it("carries the 422 detail and does not invalidate", async () => {
    createSnapshot.mockResolvedValue(errorResult(422, { detail: "Too long" }) as never);
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useCreateSnapshot("AAPL", 1), { wrapper });
    await expect(result.current.mutateAsync(null)).rejects.toMatchObject({
      status: 422,
      detail: "Too long",
    });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("rejects a 200 without an id (G2/G4)", async () => {
    createSnapshot.mockResolvedValue(okResult(HTML) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useCreateSnapshot("AAPL", 1), { wrapper });
    await expect(result.current.mutateAsync(null)).rejects.toMatchObject({ status: 200 });
  });
});

describe("useRunBacktest", () => {
  it("writes the reply into the backtest query", async () => {
    runBacktest.mockResolvedValue(okResult(backtest()) as never);
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(backtestKey("AAPL"), noBacktest());
    const { result } = renderHook(() => useRunBacktest("AAPL"), { wrapper });
    await act(() => result.current.mutateAsync());
    expect(runBacktest).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(queryClient.getQueryData(backtestKey("AAPL"))).toEqual(backtest());
  });

  it("carries the 422 detail and leaves the stored run alone", async () => {
    runBacktest.mockResolvedValue(
      errorResult(422, { detail: "No 10-K filings to back-test" }) as never,
    );
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(backtestKey("AAPL"), backtest());
    const { result } = renderHook(() => useRunBacktest("AAPL"), { wrapper });
    await expect(result.current.mutateAsync()).rejects.toMatchObject({
      status: 422,
      detail: "No 10-K filings to back-test",
    });
    expect(queryClient.getQueryData(backtestKey("AAPL"))).toEqual(backtest());
  });

  it("rejects a 200 of the wrong shape and writes nothing (G2/G4)", async () => {
    runBacktest.mockResolvedValue(okResult(HTML) as never);
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useRunBacktest("AAPL"), { wrapper });
    await expect(result.current.mutateAsync()).rejects.toMatchObject({ status: 200 });
    expect(queryClient.getQueryData(backtestKey("AAPL"))).toBeUndefined();
  });
});

describe("useSetRationale", () => {
  it("patches the row and invalidates the audit pages", async () => {
    setRationale.mockResolvedValue(okResult(auditRow({ rationale: "Guide raised" })) as never);
    const { queryClient, wrapper } = setup();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useSetRationale("AAPL"), { wrapper });
    await act(() => result.current.mutateAsync({ id: 41, rationale: "Guide raised" }));
    expect(setRationale).toHaveBeenCalledWith({
      path: { ticker: "AAPL", row_id: 41 },
      body: { rationale: "Guide raised" },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: auditKey("AAPL") });
  });

  it("carries the 422 detail", async () => {
    setRationale.mockResolvedValue(errorResult(422, { detail: "At most 500" }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useSetRationale("AAPL"), { wrapper });
    await expect(result.current.mutateAsync({ id: 41, rationale: "x" })).rejects.toMatchObject({
      status: 422,
      detail: "At most 500",
    });
  });

  it("rejects a 200 without an id (G2/G4)", async () => {
    setRationale.mockResolvedValue(okResult(HTML) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useSetRationale("AAPL"), { wrapper });
    await expect(result.current.mutateAsync({ id: 41, rationale: null })).rejects.toMatchObject({
      status: 200,
    });
  });
});
