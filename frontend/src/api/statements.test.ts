import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import {
  getAsReportedApiV1CompaniesTickerAsReportedGet,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getStatementApiV1CompaniesTickerStatementsGet,
} from "@/api/generated/sdk.gen";
import {
  asReportedQueryOptions,
  mappingGapsQueryOptions,
  statementQueryOptions,
} from "@/api/statements";
import { asReportedBalanceSheet } from "@/test/classification";
import { mappingGaps } from "@/test/companies";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  getCellApiV1CompaniesTickerStatementsCellGet: vi.fn(),
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
  getAsReportedApiV1CompaniesTickerAsReportedGet: vi.fn(),
}));

const getStatement = vi.mocked(getStatementApiV1CompaniesTickerStatementsGet);
const statement = {
  periods: [{ fiscal_year: 2024, fiscal_period: "FY" }],
  rows: [{ code: "revenue" }],
};

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

afterEach(() => vi.clearAllMocks());

describe("statementQueryOptions basis", () => {
  it("sends basis normalized as a query param", async () => {
    getStatement.mockResolvedValue(okResult(statement) as never);
    await client().fetchQuery(statementQueryOptions("AAPL", "IS", "annual", "total", "normalized"));
    expect(getStatement).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { type: "IS", freq: "annual", common_size_base: "total", basis: "normalized" },
    });
  });

  it("defaults to reported", async () => {
    getStatement.mockResolvedValue(okResult(statement) as never);
    await client().fetchQuery(statementQueryOptions("AAPL", "IS", "annual"));
    expect(getStatement.mock.calls[0]?.[0]?.query).toMatchObject({ basis: "reported" });
  });

  it("keys differ between reported and normalized, basis after commonSizeBase", () => {
    const reported = statementQueryOptions("AAPL", "IS", "annual", "total", "reported").queryKey;
    const normalized = statementQueryOptions(
      "AAPL",
      "IS",
      "annual",
      "total",
      "normalized",
    ).queryKey;
    expect(reported).not.toEqual(normalized);
    expect(reported.slice(-2)).toEqual(["total", "reported"]);
    expect(normalized.slice(-2)).toEqual(["total", "normalized"]);
    expect(statementQueryOptions("AAPL", "IS", "annual").queryKey).toEqual(reported);
  });

  it("rejects a 200 with a wrong body", async () => {
    getStatement.mockResolvedValue(okResult("<html></html>") as never);
    await expect(
      client().fetchQuery(statementQueryOptions("AAPL", "IS", "annual", "total", "normalized")),
    ).rejects.toMatchObject({ status: 200, detail: "Unexpected response" });
  });

  it("rejects a 404 and a network error", async () => {
    getStatement.mockResolvedValue(errorResult(404) as never);
    await expect(
      client().fetchQuery(statementQueryOptions("AAPL", "IS", "annual", "total", "normalized")),
    ).rejects.toMatchObject({ status: 404 });
    getStatement.mockResolvedValue(networkErrorResult() as never);
    await expect(
      client().fetchQuery(statementQueryOptions("AAPL", "IS", "annual", "total", "normalized")),
    ).rejects.toMatchObject({ status: undefined });
  });
});

describe("mappingGapsQueryOptions", () => {
  it("rejects a gaps report without its unclassified lines (an API before M7b S7)", async () => {
    const { unclassified_lines: _dropped, ...old } = mappingGaps();
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(old) as never,
    );
    await expect(client().fetchQuery(mappingGapsQueryOptions("AAPL"))).rejects.toMatchObject({
      status: 200,
      detail: "Unexpected response",
    });
  });

  it("accepts a full gaps report", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    await expect(client().fetchQuery(mappingGapsQueryOptions("AAPL"))).resolves.toMatchObject({
      unclassified_lines: [],
    });
  });
});

describe("asReportedQueryOptions (M7d S5)", () => {
  const getAsReported = vi.mocked(getAsReportedApiV1CompaniesTickerAsReportedGet);

  it("asks for the default filing without an accession", async () => {
    getAsReported.mockResolvedValue(okResult(asReportedBalanceSheet()) as never);
    await client().fetchQuery(asReportedQueryOptions("AAPL", "BS", null));
    expect(getAsReported).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { statement: "BS" },
    });
  });

  it("sends a named accession and keys by statement and accession", async () => {
    getAsReported.mockResolvedValue(okResult(asReportedBalanceSheet()) as never);
    await client().fetchQuery(asReportedQueryOptions("AAPL", "IS", "0000320193-25-000079"));
    expect(getAsReported).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { statement: "IS", accession: "0000320193-25-000079" },
    });
    expect(asReportedQueryOptions("AAPL", "IS", "x").queryKey).toEqual([
      ...companyKey("AAPL"),
      "as-reported",
      "IS",
      "x",
    ]);
  });

  it("rejects a 200 with a wrong body and passes a 404 on", async () => {
    getAsReported.mockResolvedValue(okResult({ filing: null }) as never);
    await expect(
      client().fetchQuery(asReportedQueryOptions("AAPL", "BS", null)),
    ).rejects.toMatchObject({ status: 200, detail: "Unexpected response" });
    getAsReported.mockResolvedValue(errorResult(404) as never);
    await expect(
      client().fetchQuery(asReportedQueryOptions("AAPL", "BS", "nope")),
    ).rejects.toMatchObject({ status: 404 });
  });
});
