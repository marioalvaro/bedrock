import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  createNoteApiV1CompaniesTickerNotesPost,
  createSeriesApiV1CompaniesTickerSegmentSeriesPost,
  deleteNoteApiV1CompaniesTickerNotesNoteIdDelete,
  deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  importSegmentsApiV1CompaniesTickerSegmentsImportPost,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
  setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut,
  updateNoteApiV1CompaniesTickerNotesNoteIdPut,
  updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut,
} from "@/api/generated/sdk.gen";
import type {
  ImportIssueOut,
  NoteIn,
  NoteLinkOut,
  NoteOut,
  SegmentImportIn,
  SegmentImportOut,
  SegmentSeriesIn,
  SegmentSeriesOut,
  SegmentSeriesUpdate,
  SegmentValuesIn,
} from "@/api/generated/types.gen";

// Keys of the M3 context views. S5 adds comps and guidance queries under `compsKey` and
// `guidanceKey`, so `invalidateAdjustmentViews` (which reaches both) needs no change then.
export const segmentsKey = (ticker: string) => [...companyKey(ticker), "segments"] as const;
export const guidanceKey = (ticker: string) => [...companyKey(ticker), "guidance"] as const;
export const compsKey = (ticker: string) => [...companyKey(ticker), "comps"] as const;
export const notesKey = (ticker: string) => [...companyKey(ticker), "notes"] as const;
export const noteLinksKey = (ticker: string) => [...companyKey(ticker), "note-links"] as const;

export type SegmentFreq = "annual" | "quarterly";
export type FiscalPeriod = NonNullable<NoteIn["fiscal_period"]>;

// The Notes filters, as the API takes them (an unset field is not sent).
export interface NoteFilter {
  code?: string;
  fiscalYear?: number;
  fiscalPeriod?: FiscalPeriod;
}

/** GET …/segments. Rejects a 200 without `periods` and `blocks` arrays (Gotcha G2). */
export const segmentsQueryOptions = (ticker: string, freq: SegmentFreq) =>
  queryOptions({
    queryKey: [...segmentsKey(ticker), freq],
    queryFn: async () => {
      const grid = await unwrap(
        getSegmentsApiV1CompaniesTickerSegmentsGet({ path: { ticker }, query: { freq } }),
      );
      if (!Array.isArray(grid?.periods) || !Array.isArray(grid?.blocks)) {
        throw new ApiError(200, "Unexpected response");
      }
      return grid;
    },
  });

/** GET …/notes with the filter (newest first, as the API orders it). */
export const notesQueryOptions = (ticker: string, filter: NoteFilter) =>
  queryOptions<NoteOut[]>({
    queryKey: [...notesKey(ticker), filter],
    queryFn: async () => {
      const query = {
        ...(filter.code !== undefined && { code: filter.code }),
        ...(filter.fiscalYear !== undefined && { fiscal_year: filter.fiscalYear }),
        ...(filter.fiscalPeriod !== undefined && { fiscal_period: filter.fiscalPeriod }),
      };
      const list = await unwrap(listNotesApiV1CompaniesTickerNotesGet({ path: { ticker }, query }));
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/** GET …/notes/links: one entry per distinct link, which drives the statement markers. */
export const noteLinksQueryOptions = (ticker: string) =>
  queryOptions<NoteLinkOut[]>({
    queryKey: noteLinksKey(ticker),
    queryFn: async () => {
      const links = await unwrap(listLinksApiV1CompaniesTickerNotesLinksGet({ path: { ticker } }));
      if (!Array.isArray(links)) throw new ApiError(200, "Unexpected response");
      return links;
    },
  });

/** A segment change moves the segment grids and the KPI actuals of the guidance log. */
export function invalidateSegmentViews(queryClient: QueryClient, ticker: string): Promise<void> {
  return Promise.all(
    [segmentsKey(ticker), guidanceKey(ticker)].map((queryKey) =>
      queryClient.invalidateQueries({ queryKey }),
    ),
  ).then(() => undefined);
}

/** A note change moves the notes lists (every filter) and the marker index. */
export function invalidateNoteViews(queryClient: QueryClient, ticker: string): Promise<void> {
  return Promise.all(
    [notesKey(ticker), noteLinksKey(ticker)].map((queryKey) =>
      queryClient.invalidateQueries({ queryKey }),
    ),
  ).then(() => undefined);
}

/** POST …/segment-series; on success invalidates the segment views. */
export function useCreateSeries(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<SegmentSeriesOut, Error, SegmentSeriesIn>({
    mutationFn: (body) =>
      unwrap(createSeriesApiV1CompaniesTickerSegmentSeriesPost({ path: { ticker }, body })),
    onSuccess: () => invalidateSegmentViews(queryClient, ticker),
  });
}

/** PUT …/segment-series/{id} (name and display order); on success invalidates the segment views. */
export function useUpdateSeries(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<SegmentSeriesOut, Error, { id: number; body: SegmentSeriesUpdate }>({
    mutationFn: ({ id, body }) =>
      unwrap(
        updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut({
          path: { ticker, series_id: id },
          body,
        }),
      ),
    onSuccess: () => invalidateSegmentViews(queryClient, ticker),
  });
}

/** DELETE …/segment-series/{id} (its values go too); on success invalidates the segment views. */
export function useDeleteSeries(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(
        deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete({
          path: { ticker, series_id: id },
        }),
      ),
    onSuccess: () => invalidateSegmentViews(queryClient, ticker),
  });
}

/** PUT …/segment-series/{id}/values: what a grid cell edit sends (`value` null deletes). */
export function useSetSegmentValues(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<SegmentSeriesOut, Error, { id: number } & SegmentValuesIn>({
    mutationFn: ({ id, values }) =>
      unwrap(
        setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut({
          path: { ticker, series_id: id },
          body: { values },
        }),
      ),
    onSuccess: () => invalidateSegmentViews(queryClient, ticker),
  });
}

/** An import the API refused: the 422's every error, each with its 1-based row and column. */
export class ImportFailed extends ApiError {
  readonly issues: ImportIssueOut[];

  constructor(detail: string | undefined, issues: ImportIssueOut[]) {
    super(422, detail);
    this.name = "ImportFailed";
    this.issues = issues;
  }
}

// The 422 body of a refused import, as an `ImportFailed`; null when it carries no error list.
function importFailure(error: unknown): ImportFailed | null {
  if (typeof error !== "object" || error === null) return null;
  const { detail, errors } = error as { detail?: unknown; errors?: unknown };
  if (!Array.isArray(errors)) return null;
  return new ImportFailed(typeof detail === "string" ? detail : undefined, errors);
}

/** POST …/segments/import; a 422 rejects with `ImportFailed`. Invalidates the segment views. */
export function useImportSegments(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<SegmentImportOut, Error, SegmentImportIn>({
    mutationFn: async (body) => {
      const result = await importSegmentsApiV1CompaniesTickerSegmentsImportPost({
        path: { ticker },
        body,
      }).catch(() => undefined);
      if (result?.response?.status === 422) {
        const failure = importFailure(result.error);
        if (failure) throw failure;
      }
      return unwrap(Promise.resolve(result ?? {}));
    },
    onSuccess: () => invalidateSegmentViews(queryClient, ticker),
  });
}

/** POST …/notes; on success invalidates the note views. */
export function useCreateNote(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<NoteOut, Error, NoteIn>({
    mutationFn: (body) =>
      unwrap(createNoteApiV1CompaniesTickerNotesPost({ path: { ticker }, body })),
    onSuccess: () => invalidateNoteViews(queryClient, ticker),
  });
}

/** PUT …/notes/{id} (replaces the whole note); on success invalidates the note views. */
export function useUpdateNote(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<NoteOut, Error, { id: number; body: NoteIn }>({
    mutationFn: ({ id, body }) =>
      unwrap(updateNoteApiV1CompaniesTickerNotesNoteIdPut({ path: { ticker, note_id: id }, body })),
    onSuccess: () => invalidateNoteViews(queryClient, ticker),
  });
}

/** DELETE …/notes/{id}; on success invalidates the note views. */
export function useDeleteNote(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(deleteNoteApiV1CompaniesTickerNotesNoteIdDelete({ path: { ticker, note_id: id } })),
    onSuccess: () => invalidateNoteViews(queryClient, ticker),
  });
}
