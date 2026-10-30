import { queryOptions, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { companiesQueryKey, companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  deleteImportApiV1CompaniesTickerImportsImportIdDelete,
  importStatementsApiV1CompaniesTickerImportsPost,
  listImportsApiV1CompaniesTickerImportsGet,
} from "@/api/generated/sdk.gen";
import type {
  ImportFileIssueOut,
  ImportPreviewOut,
  StatementImportOut,
} from "@/api/generated/types.gen";

export type ImportFormat = "xlsx" | "csv";
export type ImportScale = ImportPreviewOut["scale"];

export const importsKey = (ticker: string) => [...companyKey(ticker), "imports"] as const;

export interface TemplateOptions {
  format: ImportFormat;
  prefill: boolean;
  scale: ImportScale;
}

/** The download link of GET …/import-template: a plain link, so the browser saves the file. */
export function importTemplateUrl(ticker: string, options: TemplateOptions): string {
  const query = new URLSearchParams({
    format: options.format,
    prefill: String(options.prefill),
    scale: options.scale,
  });
  return `/api/v1/companies/${encodeURIComponent(ticker)}/import-template?${query}`;
}

/** GET …/imports (newest first). Rejects a 200 whose body is not an array (Gotcha G2). */
export const importsQueryOptions = (ticker: string) =>
  queryOptions<StatementImportOut[]>({
    queryKey: importsKey(ticker),
    queryFn: async () => {
      const list = await unwrap(listImportsApiV1CompaniesTickerImportsGet({ path: { ticker } }));
      if (!Array.isArray(list)) throw new ApiError(200, "Unexpected response");
      return list;
    },
  });

/** An import file the API refused: the 422's every error, each located by sheet, row and column. */
export class ImportFileFailed extends ApiError {
  readonly issues: ImportFileIssueOut[];

  constructor(detail: string | undefined, issues: ImportFileIssueOut[]) {
    super(422, detail);
    this.name = "ImportFileFailed";
    this.issues = issues;
  }
}

function fileFailure(error: unknown): ImportFileFailed | null {
  if (typeof error !== "object" || error === null) return null;
  const { detail, errors } = error as { detail?: unknown; errors?: unknown };
  if (!Array.isArray(errors)) return null;
  return new ImportFileFailed(typeof detail === "string" ? detail : undefined, errors);
}

export interface ImportInput {
  file: File;
  scale?: ImportScale; // the file's own `scale` row wins; this is the fallback for a file without one
}

async function sendImport(
  ticker: string,
  { file, scale }: ImportInput,
  dryRun: boolean,
): Promise<ImportPreviewOut> {
  const result = await importStatementsApiV1CompaniesTickerImportsPost({
    path: { ticker },
    body: { file, dry_run: dryRun, ...(scale ? { scale } : {}) },
  }).catch(() => undefined);
  if (result?.response?.status === 422) {
    const failure = fileFailure(result.error);
    if (failure) throw failure;
  }
  return unwrap(Promise.resolve(result ?? {}));
}

/**
 * Marks stale everything an import can move for `ticker`: its statements, cell details, ratios,
 * key stats and gaps (all under the company's key), the import history, the comps and guidance
 * views, and the company list (key stats). Other companies are untouched.
 */
export function invalidateImportViews(queryClient: QueryClient, ticker: string): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: companyKey(ticker) }),
    queryClient.invalidateQueries({ queryKey: companiesQueryKey, exact: true }),
  ]).then(() => undefined);
}

/** POST …/imports with `dry_run`: what the file would change; nothing is stored or invalidated. */
export function usePreviewImport(ticker: string) {
  return useMutation<ImportPreviewOut, Error, ImportInput>({
    mutationFn: (input) => sendImport(ticker, input, true),
  });
}

/** POST …/imports for real; on success invalidates as `invalidateImportViews`. */
export function useConfirmImport(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<ImportPreviewOut, Error, ImportInput>({
    mutationFn: (input) => sendImport(ticker, input, false),
    onSuccess: () => invalidateImportViews(queryClient, ticker),
  });
}

/** DELETE …/imports/{id}; on success invalidates as `invalidateImportViews`. */
export function useDeleteImport(ticker: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      unwrap(
        deleteImportApiV1CompaniesTickerImportsImportIdDelete({
          path: { ticker, import_id: id },
        }),
      ),
    onSuccess: () => invalidateImportViews(queryClient, ticker),
  });
}
