import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  archiveCompanyApiV1CompaniesTickerArchivePost,
  deletionImpactApiV1CompaniesTickerDeletionImpactGet,
  getCompaniesApiV1CompaniesGet,
  removeCompanyApiV1CompaniesTickerDelete,
  restoreCompanyApiV1CompaniesTickerRestorePost,
} from "@/api/generated/sdk.gen";
import { companyItem, deletionImpact } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import {
  archivedCompaniesQueryOptions,
  companiesQueryKey,
  companiesQueryOptions,
  companyKey,
  companyQueryOptions,
  deletionImpactQueryOptions,
  useArchiveCompany,
  useRemoveCompany,
  useRestoreCompany,
} from "./companies";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
  archiveCompanyApiV1CompaniesTickerArchivePost: vi.fn(),
  restoreCompanyApiV1CompaniesTickerRestorePost: vi.fn(),
  deletionImpactApiV1CompaniesTickerDeletionImpactGet: vi.fn(),
  removeCompanyApiV1CompaniesTickerDelete: vi.fn(),
}));

const listCompanies = vi.mocked(getCompaniesApiV1CompaniesGet);
const archive = vi.mocked(archiveCompanyApiV1CompaniesTickerArchivePost);
const restore = vi.mocked(restoreCompanyApiV1CompaniesTickerRestorePost);
const impact = vi.mocked(deletionImpactApiV1CompaniesTickerDeletionImpactGet);
const remove = vi.mocked(removeCompanyApiV1CompaniesTickerDelete);

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  // Both lists are loaded, as the home list loads them.
  queryClient.setQueryData(companiesQueryKey, [companyItem()]);
  queryClient.setQueryData(archivedCompaniesQueryOptions.queryKey, []);
  return { queryClient, wrapper };
}

const invalidated = (queryClient: QueryClient, key: readonly unknown[]) =>
  queryClient.getQueryState(key)?.isInvalidated;

afterEach(() => vi.clearAllMocks());

// The backend refreshes prices hourly in US market hours, so an open page polls for the header
// price and the list's prices (the poll pauses while the tab is in the background).
describe("company queries", () => {
  it("poll for the scheduled price refresh every 15 minutes", () => {
    expect(companyQueryOptions("AAPL").refetchInterval).toBe(15 * 60_000);
    expect(companiesQueryOptions.refetchInterval).toBe(15 * 60_000);
  });
});

describe("archivedCompaniesQueryOptions (FR-WS-07)", () => {
  it("lists the archived companies under the companies prefix", async () => {
    listCompanies.mockResolvedValue(
      okResult([companyItem({ archived_at: "2026-11-18T09:00:00Z" })]) as never,
    );
    const { queryClient } = setup();

    const data = await queryClient.fetchQuery({ ...archivedCompaniesQueryOptions, staleTime: 0 });

    expect(archivedCompaniesQueryOptions.queryKey).toEqual(["companies", "archived"]);
    expect(listCompanies).toHaveBeenCalledWith({ query: { archived: true } });
    expect(data.map((c) => c.ticker)).toEqual(["AAPL"]);
  });

  it("rejects a 200 that is not a list (G2/G4)", async () => {
    listCompanies.mockResolvedValue(okResult("<!doctype html>") as never);
    const { queryClient } = setup();

    await expect(
      queryClient.fetchQuery({ ...archivedCompaniesQueryOptions, staleTime: 0 }),
    ).rejects.toMatchObject({ status: 200 });
  });
});

describe("deletionImpactQueryOptions (FR-WS-07)", () => {
  it("loads what a permanent delete removes, always fresh", async () => {
    impact.mockResolvedValue(okResult(deletionImpact()) as never);
    const { queryClient } = setup();

    const data = await queryClient.fetchQuery(deletionImpactQueryOptions("COST"));

    expect(deletionImpactQueryOptions("COST").queryKey).toEqual([
      ...companyKey("COST"),
      "deletion-impact",
    ]);
    expect(deletionImpactQueryOptions("COST").staleTime).toBe(0);
    expect(impact).toHaveBeenCalledWith({ path: { ticker: "COST" } });
    expect(data.facts).toBe(48210);
  });

  it.each([
    ["an HTML shell", "<!doctype html>"],
    ["no counts", { ticker: "COST" }],
  ])("rejects a 200 with %s (G2/G4)", async (_name, body) => {
    impact.mockResolvedValue(okResult(body) as never);
    const { queryClient } = setup();

    await expect(queryClient.fetchQuery(deletionImpactQueryOptions("COST"))).rejects.toMatchObject({
      status: 200,
    });
  });
});

describe.each([
  ["useArchiveCompany", useArchiveCompany, archive],
  ["useRestoreCompany", useRestoreCompany, restore],
] as const)("%s (FR-WS-07)", (_name, useHook, sdk) => {
  it("posts for the ticker and invalidates both lists", async () => {
    sdk.mockResolvedValue(okResult(undefined, 204) as never);
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useHook(), { wrapper });

    result.current.mutate("COST");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(sdk).toHaveBeenCalledWith({ path: { ticker: "COST" } });
    expect(invalidated(queryClient, companiesQueryKey)).toBe(true);
    expect(invalidated(queryClient, archivedCompaniesQueryOptions.queryKey)).toBe(true);
  });

  it("carries the API's detail on a failure", async () => {
    sdk.mockResolvedValue(errorResult(404, { detail: "Company not found" }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useHook(), { wrapper });

    result.current.mutate("ZZZZ");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 404, detail: "Company not found" });
  });
});

describe("useRemoveCompany", () => {
  it("deletes, drops the company's queries and invalidates both lists", async () => {
    remove.mockResolvedValue(okResult(undefined, 204) as never);
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(companyKey("COST"), companyItem({ ticker: "COST" }));
    const { result } = renderHook(() => useRemoveCompany(), { wrapper });

    result.current.mutate("COST");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryData(companyKey("COST"))).toBeUndefined();
    expect(invalidated(queryClient, companiesQueryKey)).toBe(true);
    expect(invalidated(queryClient, archivedCompaniesQueryOptions.queryKey)).toBe(true);
  });

  it("carries the 409 of a company that is not archived", async () => {
    remove.mockResolvedValue(
      errorResult(409, { detail: "Archive COST before deleting it permanently." }) as never,
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useRemoveCompany(), { wrapper });

    result.current.mutate("COST");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 409 });
  });
});
