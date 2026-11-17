import { queryOptions } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  getAsReportedApiV1CompaniesTickerAsReportedGet,
  getCellApiV1CompaniesTickerStatementsCellGet,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getStatementApiV1CompaniesTickerStatementsGet,
} from "@/api/generated/sdk.gen";

export type StatementType = "IS" | "BS" | "CF";
export type Freq = "annual" | "quarterly" | "ttm";
// What common-size divides by: revenue / total assets, or each row's parent row.
export type CommonSizeBase = "total" | "parent";
// Reported, or reported plus the company's adjustments (and their propagation).
export type Basis = "reported" | "normalized";

export const statementQueryOptions = (
  ticker: string,
  type: StatementType,
  freq: Freq,
  commonSizeBase: CommonSizeBase = "total",
  // Sent as `basis` and part of the query key.
  basis: Basis = "reported",
) => {
  // Everything before the frequency: same company, same statement.
  const scope = [...companyKey(ticker), "statements", type];
  return queryOptions({
    queryKey: [...scope, freq, commonSizeBase, basis],
    // While another frequency, base or basis loads, keep showing the previous one of the same
    // statement, so the grid is not unmounted and rebuilt (its width, height and scroll jump).
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey.length === scope.length + 3 &&
      scope.every((part, index) => previousQuery.queryKey[index] === part)
        ? previous
        : undefined,
    queryFn: async () => {
      const statement = await unwrap(
        getStatementApiV1CompaniesTickerStatementsGet({
          path: { ticker },
          query: { type, freq, common_size_base: commonSizeBase, basis },
        }),
      );
      // A 200 proves only that something answered (the dev server's SPA fallback sends
      // index.html): decide from the body (Gotcha G2).
      if (!Array.isArray(statement?.periods) || !Array.isArray(statement?.rows)) {
        throw new ApiError(200, "Unexpected response");
      }
      return statement;
    },
  });
};

export const cellDetailQueryOptions = (
  ticker: string,
  code: string,
  fiscalYear: number,
  fiscalPeriod: string,
) =>
  queryOptions({
    queryKey: [...companyKey(ticker), "cell", code, fiscalYear, fiscalPeriod],
    queryFn: () =>
      unwrap(
        getCellApiV1CompaniesTickerStatementsCellGet({
          path: { ticker },
          query: { code, fiscal_year: fiscalYear, fiscal_period: fiscalPeriod },
        }),
      ),
  });

export const mappingGapsQueryOptions = (ticker: string) =>
  queryOptions({
    queryKey: [...companyKey(ticker), "mapping-gaps"],
    queryFn: async () => {
      const gaps = await unwrap(
        getMappingGapsApiV1CompaniesTickerMappingGapsGet({ path: { ticker } }),
      );
      if (
        !Array.isArray(gaps?.missing_items) ||
        !Array.isArray(gaps?.unmapped_concepts) ||
        !Array.isArray(gaps?.coverage) ||
        !Array.isArray(gaps?.rule_warnings) ||
        !Array.isArray(gaps?.unclassified_lines)
      ) {
        throw new ApiError(200, "Unexpected response");
      }
      return gaps;
    },
  });

/** GET …/as-reported (M7d S5): one filing's statement as filed; `accession` null asks for the
 * default filing (the newest 10-K with lines for the statement). Read only. */
export const asReportedQueryOptions = (
  ticker: string,
  statement: StatementType,
  accession: string | null,
) =>
  queryOptions({
    queryKey: [...companyKey(ticker), "as-reported", statement, accession],
    // While another filing of the same statement loads, keep the shown one, so the selector and
    // the grid stay mounted (as `statementQueryOptions` does).
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[3] === statement ? previous : undefined,
    queryFn: async () => {
      const view = await unwrap(
        getAsReportedApiV1CompaniesTickerAsReportedGet({
          path: { ticker },
          query: accession === null ? { statement } : { statement, accession },
        }),
      );
      if (!Array.isArray(view?.lines) || !Array.isArray(view?.filings)) {
        throw new ApiError(200, "Unexpected response");
      }
      return view;
    },
  });
