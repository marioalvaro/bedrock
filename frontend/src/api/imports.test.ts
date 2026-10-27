import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companiesQueryKey, companyKey } from "@/api/companies";
import { compsKey, guidanceKey } from "@/api/context";
import {
  deleteImportApiV1CompaniesTickerImportsImportIdDelete,
  importStatementsApiV1CompaniesTickerImportsPost,
  listImportsApiV1CompaniesTickerImportsGet,
} from "@/api/generated/sdk.gen";
import {
  ImportFileFailed,
  importTemplateUrl,
  importsKey,
  importsQueryOptions,
  useConfirmImport,
  useDeleteImport,
  usePreviewImport,
} from "@/api/imports";
import { preview, statementImport } from "@/test/imports";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  listImportsApiV1CompaniesTickerImportsGet: vi.fn(),
  importStatementsApiV1CompaniesTickerImportsPost: vi.fn(),
  deleteImportApiV1CompaniesTickerImportsImportIdDelete: vi.fn(),
}));

const list = vi.mocked(listImportsApiV1CompaniesTickerImportsGet);
const post = vi.mocked(importStatementsApiV1CompaniesTickerImportsPost);
const remove = vi.mocked(deleteImportApiV1CompaniesTickerImportsImportIdDelete);

afterEach(() => vi.clearAllMocks());

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

const file = new File(["x"], "AAPL.xlsx");

// Keys a statement import moves, and keys it leaves alone.
const movedKeys = (ticker: string) => [
  [...companyKey(ticker), "statements", "IS", "annual", "total", "reported"],
  [...companyKey(ticker), "cell", "sga", 2024, "FY"],
  [...companyKey(ticker), "ratios", "annual"],
  [...companyKey(ticker), "mapping-gaps"],
  [...companyKey(ticker), "multiples"],
  importsKey(ticker),
  compsKey(ticker),
  guidanceKey(ticker),
  companyKey(ticker),
  companiesQueryKey,
];
const otherCompany = [...companyKey("MSFT"), "statements", "IS", "annual", "total", "reported"];

function seed(queryClient: QueryClient) {
  for (const key of [...movedKeys("AAPL"), otherCompany]) queryClient.setQueryData(key, {});
}

function expectInvalidated(queryClient: QueryClient, invalidated: boolean) {
  for (const key of movedKeys("AAPL")) {
    expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(invalidated);
  }
  expect(queryClient.getQueryState(otherCompany)?.isInvalidated).toBe(false);
}

describe("importTemplateUrl", () => {
  it("names the format, the prefill and the scale", () => {
    expect(importTemplateUrl("AAPL", { format: "xlsx", prefill: true, scale: "millions" })).toBe(
      "/api/v1/companies/AAPL/import-template?format=xlsx&prefill=true&scale=millions",
    );
    expect(importTemplateUrl("AAPL", { format: "csv", prefill: false, scale: "units" })).toBe(
      "/api/v1/companies/AAPL/import-template?format=csv&prefill=false&scale=units",
    );
  });

  it("encodes the ticker", () => {
    expect(importTemplateUrl("BRK/B", { format: "csv", prefill: false, scale: "units" })).toContain(
      "/companies/BRK%2FB/",
    );
  });
});

describe("importsQueryOptions", () => {
  it("returns the history", async () => {
    list.mockResolvedValue(okResult([statementImport()]) as never);
    const { queryClient } = setup();
    expect(await queryClient.fetchQuery(importsQueryOptions("AAPL"))).toEqual([statementImport()]);
    expect(list).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
  });

  it("rejects a 200 whose body is not an array", async () => {
    list.mockResolvedValue(okResult("<html></html>") as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(importsQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 200,
      detail: "Unexpected response",
    });
  });
});

describe("usePreviewImport", () => {
  it("sends a dry run with the file and the scale and invalidates nothing", async () => {
    post.mockResolvedValue(okResult(preview()) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => usePreviewImport("AAPL"), { wrapper });
    result.current.mutate({ file, scale: "millions" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(post).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { file, dry_run: true, scale: "millions" },
    });
    expect(result.current.data).toEqual(preview());
    expectInvalidated(queryClient, false);
  });

  it("omits the scale when none is chosen", async () => {
    post.mockResolvedValue(okResult(preview()) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => usePreviewImport("AAPL"), { wrapper });
    result.current.mutate({ file });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(post).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { file, dry_run: true },
    });
  });

  it("rejects a 422 with every located error", async () => {
    const errors = [
      { sheet: "IS", row: 12, column: "G", message: "not a number" },
      { sheet: null, row: null, column: null, message: "unknown sheet" },
    ];
    post.mockResolvedValue(errorResult(422, { detail: "2 errors", errors }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => usePreviewImport("AAPL"), { wrapper });
    result.current.mutate({ file });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ImportFileFailed);
    expect((result.current.error as ImportFileFailed).issues).toEqual(errors);
    expect((result.current.error as ImportFileFailed).detail).toBe("2 errors");
  });

  it("keeps a plain ApiError for another failure", async () => {
    post.mockResolvedValue(errorResult(413, { detail: "File too large" }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => usePreviewImport("AAPL"), { wrapper });
    result.current.mutate({ file });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).not.toBeInstanceOf(ImportFileFailed);
    expect(result.current.error).toMatchObject({ status: 413, detail: "File too large" });
  });
});

describe("useConfirmImport", () => {
  it("sends the real run and invalidates what an import moves", async () => {
    post.mockResolvedValue(okResult(preview({ dry_run: false, import_id: 4 })) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useConfirmImport("AAPL"), { wrapper });
    result.current.mutate({ file, scale: "thousands" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(post).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { file, dry_run: false, scale: "thousands" },
    });
    expect(result.current.data?.import_id).toBe(4);
    expectInvalidated(queryClient, true);
  });

  it("invalidates nothing when the file is refused", async () => {
    post.mockResolvedValue(errorResult(422, { detail: "1 error", errors: [] }) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useConfirmImport("AAPL"), { wrapper });
    result.current.mutate({ file });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expectInvalidated(queryClient, false);
  });
});

describe("useDeleteImport", () => {
  it("deletes one import and invalidates what an import moves", async () => {
    remove.mockResolvedValue(okResult(undefined, 204) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useDeleteImport("AAPL"), { wrapper });
    result.current.mutate(3);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", import_id: 3 } });
    expectInvalidated(queryClient, true);
  });

  it("rejects a 404 with its reason", async () => {
    remove.mockResolvedValue(errorResult(404, { detail: "Unknown import" }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useDeleteImport("AAPL"), { wrapper });
    result.current.mutate(9);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 404, detail: "Unknown import" });
  });
});
