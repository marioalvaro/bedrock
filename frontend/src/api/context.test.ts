import {
  QueryClient,
  QueryClientProvider,
  type FetchQueryOptions,
  type UseMutationResult,
} from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import {
  ImportFailed,
  noteLinksKey,
  noteLinksQueryOptions,
  notesKey,
  notesQueryOptions,
  segmentsKey,
  segmentsQueryOptions,
  useCreateNote,
  useCreateSeries,
  useDeleteNote,
  useDeleteSeries,
  useFillAnnualSegments,
  useImportSegments,
  useSetSegmentValues,
  useUpdateNote,
  useUpdateSeries,
} from "@/api/context";
import { ApiError } from "@/api/errors";
import {
  createNoteApiV1CompaniesTickerNotesPost,
  createSeriesApiV1CompaniesTickerSegmentSeriesPost,
  deleteNoteApiV1CompaniesTickerNotesNoteIdDelete,
  deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete,
  fillAnnualApiV1CompaniesTickerSegmentsFillAnnualPost,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  importSegmentsApiV1CompaniesTickerSegmentsImportPost,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
  setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut,
  updateNoteApiV1CompaniesTickerNotesNoteIdPut,
  updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut,
} from "@/api/generated/sdk.gen";
import { note, noteLinks, segments } from "@/test/context";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getSegmentsApiV1CompaniesTickerSegmentsGet: vi.fn(),
  createSeriesApiV1CompaniesTickerSegmentSeriesPost: vi.fn(),
  updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut: vi.fn(),
  deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete: vi.fn(),
  setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut: vi.fn(),
  importSegmentsApiV1CompaniesTickerSegmentsImportPost: vi.fn(),
  fillAnnualApiV1CompaniesTickerSegmentsFillAnnualPost: vi.fn(),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  createNoteApiV1CompaniesTickerNotesPost: vi.fn(),
  updateNoteApiV1CompaniesTickerNotesNoteIdPut: vi.fn(),
  deleteNoteApiV1CompaniesTickerNotesNoteIdDelete: vi.fn(),
}));

const getSegments = vi.mocked(getSegmentsApiV1CompaniesTickerSegmentsGet);
const createSeries = vi.mocked(createSeriesApiV1CompaniesTickerSegmentSeriesPost);
const updateSeries = vi.mocked(updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut);
const deleteSeries = vi.mocked(deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete);
const setValues = vi.mocked(setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut);
const importSegments = vi.mocked(importSegmentsApiV1CompaniesTickerSegmentsImportPost);
const fillAnnual = vi.mocked(fillAnnualApiV1CompaniesTickerSegmentsFillAnnualPost);
const listNotes = vi.mocked(listNotesApiV1CompaniesTickerNotesGet);
const listLinks = vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet);
const createNote = vi.mocked(createNoteApiV1CompaniesTickerNotesPost);
const updateNote = vi.mocked(updateNoteApiV1CompaniesTickerNotesNoteIdPut);
const deleteNote = vi.mocked(deleteNoteApiV1CompaniesTickerNotesNoteIdDelete);

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

afterEach(() => vi.clearAllMocks());

const aapl = companyKey("AAPL");

describe("keys", () => {
  it("follow the contract", () => {
    expect(segmentsKey("AAPL")).toEqual([...aapl, "segments"]);
    expect(segmentsQueryOptions("AAPL", "quarterly").queryKey).toEqual([
      ...aapl,
      "segments",
      "quarterly",
    ]);
    expect(notesKey("AAPL")).toEqual([...aapl, "notes"]);
    expect(notesQueryOptions("AAPL", { code: "revenue" }).queryKey).toEqual([
      ...aapl,
      "notes",
      { code: "revenue" },
    ]);
    expect(noteLinksKey("AAPL")).toEqual([...aapl, "note-links"]);
    expect(noteLinksQueryOptions("AAPL").queryKey).toEqual([...aapl, "note-links"]);
  });
});

// Every query: SDK call, body, G2 garbage body, 404.
const queries = [
  {
    name: "segmentsQueryOptions",
    options: () => segmentsQueryOptions("AAPL", "quarterly"),
    sdk: getSegments,
    args: { path: { ticker: "AAPL" }, query: { freq: "quarterly" } },
    body: segments(),
    bad: [{ periods: [] }, "<html></html>"],
  },
  {
    name: "notesQueryOptions",
    options: () =>
      notesQueryOptions("AAPL", { code: "revenue", fiscalYear: 2024, fiscalPeriod: "FY" }),
    sdk: listNotes,
    args: {
      path: { ticker: "AAPL" },
      query: { code: "revenue", fiscal_year: 2024, fiscal_period: "FY" },
    },
    body: [note()],
    bad: [{}, "<html></html>"],
  },
  {
    name: "notesQueryOptions (a metric subject)",
    options: () =>
      notesQueryOptions("AAPL", {
        metricKind: "ratio",
        metricCode: "roe",
        fiscalYear: 2024,
        fiscalPeriod: "FY",
      }),
    sdk: listNotes,
    args: {
      path: { ticker: "AAPL" },
      query: { metric_kind: "ratio", metric_code: "roe", fiscal_year: 2024, fiscal_period: "FY" },
    },
    body: [note()],
    bad: [{}, "<html></html>"],
  },
  {
    name: "noteLinksQueryOptions",
    options: () => noteLinksQueryOptions("AAPL"),
    sdk: listLinks,
    args: { path: { ticker: "AAPL" } },
    body: noteLinks(),
    bad: [{}, "<html></html>"],
  },
];

describe.each(queries)("$name", ({ options: makeOptions, sdk, args, body, bad }) => {
  const options = makeOptions as () => FetchQueryOptions;
  it("calls the SDK and returns the body", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(okResult(body) as never);
    const { queryClient } = setup();
    expect(await queryClient.fetchQuery(options())).toEqual(body);
    expect(sdk).toHaveBeenCalledWith(args);
  });

  it.each(bad)("rejects a 200 with a malformed body %j", async (garbage) => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(okResult(garbage) as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(options())).rejects.toMatchObject({
      status: 200,
      detail: "Unexpected response",
    });
  });

  it("rejects a 404 with status and detail", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(
      errorResult(404, { detail: "nope" }) as never,
    );
    const { queryClient } = setup();
    const err = await queryClient.fetchQuery(options()).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 404, detail: "nope" });
  });
});

describe("notesQueryOptions", () => {
  it("sends no query for an empty filter", async () => {
    listNotes.mockResolvedValue(okResult([]) as never);
    const { queryClient } = setup();
    await queryClient.fetchQuery(notesQueryOptions("AAPL", {}));
    const call = listNotes.mock.calls[0]![0] as { query?: Record<string, unknown> };
    expect(Object.values(call.query ?? {}).filter((v) => v !== undefined)).toEqual([]);
  });
});

type AnyMutation = UseMutationResult<unknown, Error, never>;
const seriesBody = { dimension: "geo", name: "Japan", metric: "revenue", unit: "USD" } as never;
const noteBody = { body_md: "x", canonical_code: "revenue" } as never;

const segmentStale = () => [
  [...segmentsKey("AAPL"), "annual"],
  [...segmentsKey("AAPL"), "quarterly"],
  [...aapl, "guidance"],
];
const segmentFresh = () => [
  [...aapl, "notes", {}],
  noteLinksKey("AAPL"),
  [...aapl, "statements", "IS", "annual", "total", "reported"],
  [...companyKey("MSFT"), "segments", "annual"],
  [...companyKey("MSFT"), "guidance"],
];
const noteStale = () => [
  [...notesKey("AAPL"), {}],
  [...notesKey("AAPL"), { code: "sga" }],
  noteLinksKey("AAPL"),
];
const noteFresh = () => [
  [...segmentsKey("AAPL"), "annual"],
  [...aapl, "guidance"],
  [...companyKey("MSFT"), "notes", {}],
  [...companyKey("MSFT"), "note-links"],
];

function useSeriesCreate() {
  return useCreateSeries("AAPL");
}
function useSeriesUpdate() {
  return useUpdateSeries("AAPL");
}
function useSeriesDelete() {
  return useDeleteSeries("AAPL");
}
function useSegmentValuesSet() {
  return useSetSegmentValues("AAPL");
}
function useSegmentsImport() {
  return useImportSegments("AAPL");
}
function useAnnualFill() {
  return useFillAnnualSegments("AAPL");
}
function useNoteCreate() {
  return useCreateNote("AAPL");
}
function useNoteUpdate() {
  return useUpdateNote("AAPL");
}
function useNoteDelete() {
  return useDeleteNote("AAPL");
}

const mutations = [
  {
    name: "useCreateSeries",
    hook: useSeriesCreate,
    vars: seriesBody,
    sdk: createSeries,
    args: { path: { ticker: "AAPL" }, body: seriesBody },
    stale: segmentStale,
    fresh: segmentFresh,
  },
  {
    name: "useUpdateSeries",
    hook: useSeriesUpdate,
    vars: { id: 4, body: { name: "Japan", display_order: 2 } },
    sdk: updateSeries,
    args: {
      path: { ticker: "AAPL", series_id: 4 },
      body: { name: "Japan", display_order: 2 },
    },
    stale: segmentStale,
    fresh: segmentFresh,
  },
  {
    name: "useDeleteSeries",
    hook: useSeriesDelete,
    vars: 4,
    sdk: deleteSeries,
    args: { path: { ticker: "AAPL", series_id: 4 } },
    stale: segmentStale,
    fresh: segmentFresh,
  },
  {
    name: "useSetSegmentValues",
    hook: useSegmentValuesSet,
    vars: { id: 4, values: [{ fiscal_year: 2024, fiscal_period: "FY", value: null }] },
    sdk: setValues,
    args: {
      path: { ticker: "AAPL", series_id: 4 },
      body: { values: [{ fiscal_year: 2024, fiscal_period: "FY", value: null }] },
    },
    stale: segmentStale,
    fresh: segmentFresh,
  },
  {
    name: "useImportSegments",
    hook: useSegmentsImport,
    vars: { dimension: "geo", scale: "M", text: "name,metric,unit,FY2024" },
    sdk: importSegments,
    args: {
      path: { ticker: "AAPL" },
      body: { dimension: "geo", scale: "M", text: "name,metric,unit,FY2024" },
    },
    stale: segmentStale,
    fresh: segmentFresh,
  },
  {
    name: "useFillAnnualSegments",
    hook: useAnnualFill,
    vars: { dry_run: false },
    sdk: fillAnnual,
    args: { path: { ticker: "AAPL" }, body: { dry_run: false } },
    stale: segmentStale,
    fresh: segmentFresh,
  },
  {
    name: "useCreateNote",
    hook: useNoteCreate,
    vars: noteBody,
    sdk: createNote,
    args: { path: { ticker: "AAPL" }, body: noteBody },
    stale: noteStale,
    fresh: noteFresh,
  },
  {
    name: "useUpdateNote",
    hook: useNoteUpdate,
    vars: { id: 7, body: noteBody },
    sdk: updateNote,
    args: { path: { ticker: "AAPL", note_id: 7 }, body: noteBody },
    stale: noteStale,
    fresh: noteFresh,
  },
  {
    name: "useDeleteNote",
    hook: useNoteDelete,
    vars: 7,
    sdk: deleteNote,
    args: { path: { ticker: "AAPL", note_id: 7 } },
    stale: noteStale,
    fresh: noteFresh,
  },
];

describe.each(mutations)("$name", ({ hook, vars, sdk, args, stale, fresh }) => {
  it("calls the SDK and, on success, marks stale only its views", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(okResult({}, 200) as never);
    const { wrapper, queryClient } = setup();
    for (const key of [...stale(), ...fresh()]) queryClient.setQueryData(key, {});
    const { result } = renderHook(hook as () => AnyMutation, { wrapper });
    result.current.mutate(vars as never);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(sdk).toHaveBeenCalledWith(args);
    for (const key of stale()) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    for (const key of fresh()) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });

  it("surfaces a 422 detail and does not invalidate", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(
      errorResult(422, { detail: "bad input" }) as never,
    );
    const { wrapper, queryClient } = setup();
    for (const key of stale()) queryClient.setQueryData(key, {});
    const { result } = renderHook(hook as () => AnyMutation, { wrapper });
    result.current.mutate(vars as never);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).detail).toBe("bad input");
    for (const key of stale()) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });

  it("fails on a network error with no status", async () => {
    (sdk as ReturnType<typeof vi.fn>).mockResolvedValue(networkErrorResult() as never);
    const { wrapper } = setup();
    const { result } = renderHook(hook as () => AnyMutation, { wrapper });
    result.current.mutate(vars as never);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).status).toBeUndefined();
  });
});

describe("useFillAnnualSegments", () => {
  const counts = { values_created: 2, values_overwritten: 1, values_unchanged: 0 };

  it("returns the counts and leaves the views alone on a dry run", async () => {
    fillAnnual.mockResolvedValue(okResult(counts, 200) as never);
    const { wrapper, queryClient } = setup();
    for (const key of segmentStale()) queryClient.setQueryData(key, {});
    const { result } = renderHook(() => useFillAnnualSegments("AAPL"), { wrapper });

    result.current.mutate({ dry_run: true });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(counts);
    expect(fillAnnual).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, body: { dry_run: true } });
    for (const key of segmentStale()) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });
});

describe("useImportSegments", () => {
  it("returns the counts", async () => {
    const counts = { series_created: 5, values_created: 5, values_updated: 0 };
    importSegments.mockResolvedValue(okResult(counts) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useImportSegments("AAPL"), { wrapper });
    result.current.mutate({ dimension: "geo", scale: "M", text: "t" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(counts);
  });

  it("rejects a 422 with the issue list", async () => {
    const errors = [
      { row: 3, column: 4, message: "bad number" },
      { row: 5, column: null, message: "duplicate series" },
    ];
    importSegments.mockResolvedValue(
      errorResult(422, { detail: "Import failed", errors }) as never,
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useImportSegments("AAPL"), { wrapper });
    result.current.mutate({ dimension: "geo", scale: "M", text: "t" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const error = result.current.error;
    expect(error).toBeInstanceOf(ImportFailed);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ImportFailed).issues).toEqual(errors);
    expect((error as ImportFailed).detail).toBe("Import failed");
  });

  it("rejects another failure as a plain ApiError", async () => {
    importSegments.mockResolvedValue(errorResult(404, { detail: "Unknown ticker" }) as never);
    const { wrapper } = setup();
    const { result } = renderHook(() => useImportSegments("AAPL"), { wrapper });
    result.current.mutate({ dimension: "geo", scale: "M", text: "t" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).not.toBeInstanceOf(ImportFailed);
    expect((result.current.error as ApiError).status).toBe(404);
  });
});
