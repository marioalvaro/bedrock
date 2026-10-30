import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  createEntryApiV1CompaniesTickerGuidancePost,
  createSetApiV1CompaniesTickerCompsSetsPost,
  deleteEntryApiV1CompaniesTickerGuidanceGuidanceIdDelete,
  deleteSetApiV1CompaniesTickerCompsSetsSetIdDelete,
  getComparisonApiV1CompaniesTickerCompsSetsSetIdComparisonGet,
  getGuidanceApiV1CompaniesTickerGuidanceGet,
  getPeerSuggestionsApiV1CompaniesTickerPeerSuggestionsGet,
  listMetricsApiV1CompaniesTickerGuidanceMetricsGet,
  listSetsApiV1CompaniesTickerCompsSetsGet,
  updateEntryApiV1CompaniesTickerGuidanceGuidanceIdPut,
  updateSetApiV1CompaniesTickerCompsSetsSetIdPut,
  createNoteApiV1CompaniesTickerNotesPost,
  createSeriesApiV1CompaniesTickerSegmentSeriesPost,
  deleteNoteApiV1CompaniesTickerNotesNoteIdDelete,
  deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  fillAnnualApiV1CompaniesTickerSegmentsFillAnnualPost,
  importSegmentsApiV1CompaniesTickerSegmentsImportPost,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
  setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut,
  updateNoteApiV1CompaniesTickerNotesNoteIdPut,
  updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut,
} from "@/api/generated/sdk.gen";
import type {
  CompsOut,
  CompsSetIn,
  CompsSetOut,
  GuidanceEntryOut,
  GuidanceIn,
  GuidanceOut,
  ImportIssueOut,
  MetricChoiceOut,
  PeerSuggestionOut,
  NoteIn,
  NoteLinkOut,
  NoteOut,
  FillAnnualIn,
  FillAnnualOut,
  SegmentImportIn,
  SegmentImportOut,
  SegmentSeriesIn,
  SegmentSeriesOut,
  SegmentSeriesUpdate,
  SegmentValuesIn,
} from "@/api/generated/types.gen";
import type { Basis } from "@/api/statements";

// Keys of the M3 context views. `invalidateAdjustmentViews` reaches `compsKey` (the comparisons)
// and `guidanceKey` (the log), whose actuals follow the normalized statements.
export const segmentsKey = (ticker: string) => [...companyKey(ticker), "segments"] as const;
export const guidanceKey = (ticker: string) => [...companyKey(ticker), "guidance"] as const;
export const guidanceMetricsKey = (ticker: string) =>
  [...companyKey(ticker), "guidance-metrics"] as const;
export const compsKey = (ticker: string) => [...companyKey(ticker), "comps"] as const;
export const compsSetsKey = (ticker: string) => [...companyKey(ticker), "comps-sets"] as const;
export const peerSuggestionsKey = (ticker: string) =>
  [...companyKey(ticker), "peer-suggestions"] as const;
export const notesKey = (ticker: string) => [...companyKey(ticker), "notes"] as const;
export const noteLinksKey = (ticker: string) => [...companyKey(ticker), "note-links"] as const;

export type SegmentFreq = "annual" | "quarterly";
export type FiscalPeriod = NonNullable<NoteIn["fiscal_period"]>;

// The Notes filters, as the API takes them (an unset field is not sent).
export interface NoteFilter {
  code?: string; // a line
  metricKind?: NonNullable<NoteIn["metric_kind"]>; // a ratio / capital / quality metric, with its code
  metricCode?: string;
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
        ...(filter.metricKind !== undefined && { metric_kind: filter.metricKind }),
        ...(filter.metricCode !== undefined && { metric_code: filter.metricCode }),
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

/** GET …/comps-sets (ordered by name, members by ticker). */
export const compsSetsQueryOptions = (ticker: string) =>
  queryOptions<CompsSetOut[]>({
    queryKey: compsSetsKey(ticker),
    queryFn: async () => {
      const sets = await unwrap(listSetsApiV1CompaniesTickerCompsSetsGet({ path: { ticker } }));
      if (!Array.isArray(sets)) throw new ApiError(200, "Unexpected response");
      return sets;
    },
  });

/** GET …/comps-sets/{id}/comparison. Rejects a 200 without `companies` and `rows` arrays. */
export const comparisonQueryOptions = (ticker: string, setId: number, basis: Basis) =>
  queryOptions<CompsOut>({
    queryKey: [...compsKey(ticker), setId, basis],
    queryFn: async () => {
      const table = await unwrap(
        getComparisonApiV1CompaniesTickerCompsSetsSetIdComparisonGet({
          path: { ticker, set_id: setId },
          query: { basis },
        }),
      );
      if (!Array.isArray(table?.companies) || !Array.isArray(table?.rows)) {
        throw new ApiError(200, "Unexpected response");
      }
      return table;
    },
  });

/** GET …/peer-suggestions, with `in_set` against the set being edited (none: all false). */
export const peerSuggestionsQueryOptions = (ticker: string, setId: number | null) =>
  queryOptions<PeerSuggestionOut[]>({
    queryKey: [...peerSuggestionsKey(ticker), setId],
    queryFn: async () => {
      const list = await unwrap(
        getPeerSuggestionsApiV1CompaniesTickerPeerSuggestionsGet({
          path: { ticker },
          ...(setId !== null && { query: { set_id: setId } }),
        }),
      );
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/** GET …/guidance: the evaluated entries, the summary and the per-metric counts. */
export const guidanceQueryOptions = (ticker: string) =>
  queryOptions<GuidanceOut>({
    queryKey: guidanceKey(ticker),
    queryFn: async () => {
      const log = await unwrap(getGuidanceApiV1CompaniesTickerGuidanceGet({ path: { ticker } }));
      if (!Array.isArray(log?.entries) || !Array.isArray(log?.by_metric) || !log?.summary) {
        throw new ApiError(200, "Unexpected response");
      }
      return log;
    },
  });

/** GET …/guidance/metrics: the metric choices of the guidance form. */
export const guidanceMetricsQueryOptions = (ticker: string) =>
  queryOptions<MetricChoiceOut[]>({
    queryKey: guidanceMetricsKey(ticker),
    queryFn: async () => {
      const list = await unwrap(
        listMetricsApiV1CompaniesTickerGuidanceMetricsGet({ path: { ticker } }),
      );
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/**
 * A segment change moves the segment grids, the KPI actuals of the guidance log and the guidance
 * metric choices (a KPI series is a metric).
 */
export function invalidateSegmentViews(queryClient: QueryClient, ticker: string): Promise<void> {
  return Promise.all(
    [segmentsKey(ticker), guidanceKey(ticker), guidanceMetricsKey(ticker)].map((queryKey) =>
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

/** A comps-set change moves the sets, every comparison and the suggestions (`in_set`). */
export function invalidateCompsViews(queryClient: QueryClient, ticker: string): Promise<void> {
  return Promise.all(
    [compsSetsKey(ticker), compsKey(ticker), peerSuggestionsKey(ticker)].map((queryKey) =>
      queryClient.invalidateQueries({ queryKey }),
    ),
  ).then(() => undefined);
}

/** POST …/comps-sets; on success invalidates the comps views. */
export function useCreateCompsSet(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<CompsSetOut, Error, CompsSetIn>({
    mutationFn: (body) =>
      unwrap(createSetApiV1CompaniesTickerCompsSetsPost({ path: { ticker }, body })),
    onSuccess: () => invalidateCompsViews(queryClient, ticker),
  });
}

/** PUT …/comps-sets/{id} (name and members, replaced); on success invalidates the comps views. */
export function useUpdateCompsSet(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<CompsSetOut, Error, { id: number; body: CompsSetIn }>({
    mutationFn: ({ id, body }) =>
      unwrap(
        updateSetApiV1CompaniesTickerCompsSetsSetIdPut({ path: { ticker, set_id: id }, body }),
      ),
    onSuccess: () => invalidateCompsViews(queryClient, ticker),
  });
}

/** DELETE …/comps-sets/{id}; on success invalidates the comps views. */
export function useDeleteCompsSet(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(deleteSetApiV1CompaniesTickerCompsSetsSetIdDelete({ path: { ticker, set_id: id } })),
    onSuccess: () => invalidateCompsViews(queryClient, ticker),
  });
}

/** POST …/guidance; on success invalidates the guidance log. */
export function useCreateGuidance(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<GuidanceEntryOut, Error, GuidanceIn>({
    mutationFn: (body) =>
      unwrap(createEntryApiV1CompaniesTickerGuidancePost({ path: { ticker }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: guidanceKey(ticker) }),
  });
}

/** PUT …/guidance/{id} (replaces the entry); on success invalidates the guidance log. */
export function useUpdateGuidance(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<GuidanceEntryOut, Error, { id: number; body: GuidanceIn }>({
    mutationFn: ({ id, body }) =>
      unwrap(
        updateEntryApiV1CompaniesTickerGuidanceGuidanceIdPut({
          path: { ticker, guidance_id: id },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: guidanceKey(ticker) }),
  });
}

/** DELETE …/guidance/{id}; on success invalidates the guidance log. */
export function useDeleteGuidance(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(
        deleteEntryApiV1CompaniesTickerGuidanceGuidanceIdDelete({
          path: { ticker, guidance_id: id },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: guidanceKey(ticker) }),
  });
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

/**
 * POST …/segments/fill-annual: FY values from the sum of the quarters. A dry run only counts what
 * would change, so only a real run invalidates the segment views.
 */
export function useFillAnnualSegments(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<FillAnnualOut, Error, FillAnnualIn>({
    mutationFn: (body) =>
      unwrap(fillAnnualApiV1CompaniesTickerSegmentsFillAnnualPost({ path: { ticker }, body })),
    onSuccess: (_counts, body) =>
      body.dry_run ? undefined : invalidateSegmentViews(queryClient, ticker),
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
