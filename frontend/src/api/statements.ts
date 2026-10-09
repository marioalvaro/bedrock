import { queryOptions } from "@tanstack/react-query";

import { companyKey } from "@/api/companies";
import { ApiError, unwrap } from "@/api/errors";
import {
  getCellApiV1CompaniesTickerStatementsCellGet,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getStatementApiV1CompaniesTickerStatementsGet,
} from "@/api/generated/sdk.gen";

export type StatementType = "IS" | "BS" | "CF";
export type Freq = "annual" | "quarterly" | "ttm";

export const statementQueryOptions = (ticker: string, type: StatementType, freq: Freq) =>
  queryOptions({
    queryKey: [...companyKey(ticker), "statements", type, freq],
    queryFn: async () => {
      const statement = await unwrap(
        getStatementApiV1CompaniesTickerStatementsGet({
          path: { ticker },
          query: { type, freq },
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
      if (!Array.isArray(gaps?.missing_items) || !Array.isArray(gaps?.unmapped_concepts)) {
        throw new ApiError(200, "Unexpected response");
      }
      return gaps;
    },
  });
