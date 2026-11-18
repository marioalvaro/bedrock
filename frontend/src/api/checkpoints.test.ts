import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  checkpointsKey,
  checkpointsQueryOptions,
  useCreateCheckpoint,
  useDeleteCheckpoint,
  useUpdateCheckpoint,
} from "@/api/checkpoints";
import { companyKey } from "@/api/companies";
import {
  createCheckpointApiV1CompaniesTickerCheckpointsPost,
  deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete,
  listCheckpointsApiV1CompaniesTickerCheckpointsGet,
  updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut,
} from "@/api/generated/sdk.gen";
import { checkpointList, checkpointOut } from "@/test/checkpoints";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  createCheckpointApiV1CompaniesTickerCheckpointsPost: vi.fn(),
  deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete: vi.fn(),
  listCheckpointsApiV1CompaniesTickerCheckpointsGet: vi.fn(),
  updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut: vi.fn(),
}));

const list = vi.mocked(listCheckpointsApiV1CompaniesTickerCheckpointsGet);
const create = vi.mocked(createCheckpointApiV1CompaniesTickerCheckpointsPost);
const update = vi.mocked(updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut);
const remove = vi.mocked(deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete);

afterEach(() => vi.clearAllMocks());

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  return { queryClient, wrapper, invalidate };
}

const BODY = { statement: "gross_margin > 44%", label: null, freq: "ttm", margin: "1%" } as const;

describe("checkpointsQueryOptions", () => {
  it("sits under the company and is always stale", () => {
    expect(checkpointsKey("AAPL")).toEqual([...companyKey("AAPL"), "checkpoints"]);
    expect(checkpointsQueryOptions("AAPL").queryKey).toEqual(checkpointsKey("AAPL"));
    expect(checkpointsQueryOptions("AAPL").staleTime).toBe(0);
  });

  it("loads the checkpoints with their states", async () => {
    list.mockResolvedValue(okResult(checkpointList()) as never);
    const data = await setup().queryClient.fetchQuery(checkpointsQueryOptions("AAPL"));
    expect(list).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(data.checkpoints[0]!.state).toBe("holding");
  });

  it.each([
    ["an HTML shell", "<!doctype html><html></html>"],
    ["no checkpoints", { report: null }],
  ])("rejects a 200 with %s (G2/G4)", async (_name, body) => {
    list.mockResolvedValue(okResult(body) as never);
    await expect(
      setup().queryClient.fetchQuery(checkpointsQueryOptions("AAPL")),
    ).rejects.toMatchObject({ status: 200 });
  });
});

describe("the writes", () => {
  it("creates a checkpoint and invalidates the list", async () => {
    create.mockResolvedValue(okResult(checkpointOut(), 201) as never);
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useCreateCheckpoint("AAPL"), { wrapper });
    await act(() => result.current.mutateAsync(BODY));
    expect(create).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, body: BODY });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: checkpointsKey("AAPL") });
  });

  it("updates a checkpoint by id and invalidates the list", async () => {
    update.mockResolvedValue(okResult(checkpointOut()) as never);
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useUpdateCheckpoint("AAPL"), { wrapper });
    await act(() => result.current.mutateAsync({ id: 3, body: BODY }));
    expect(update).toHaveBeenCalledWith({
      path: { ticker: "AAPL", checkpoint_id: 3 },
      body: BODY,
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: checkpointsKey("AAPL") });
  });

  it("deletes a checkpoint and invalidates the list", async () => {
    remove.mockResolvedValue(okResult(null, 204) as never);
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useDeleteCheckpoint("AAPL"), { wrapper });
    await act(() => result.current.mutateAsync(3));
    expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", checkpoint_id: 3 } });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: checkpointsKey("AAPL") });
  });

  it("carries the 422 detail of a statement that does not parse", async () => {
    create.mockResolvedValue(errorResult(422, { detail: "Unknown name 'gross' at 0" }) as never);
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useCreateCheckpoint("AAPL"), { wrapper });
    await expect(result.current.mutateAsync(BODY)).rejects.toMatchObject({
      status: 422,
      detail: "Unknown name 'gross' at 0",
    });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("rejects a 201 of the wrong shape (G2/G4)", async () => {
    create.mockResolvedValue(okResult("<!doctype html>", 201) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useCreateCheckpoint("AAPL"), { wrapper });
    await expect(result.current.mutateAsync(BODY)).rejects.toMatchObject({ status: 200 });
  });
});
