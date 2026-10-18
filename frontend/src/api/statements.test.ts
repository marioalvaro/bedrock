import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getStatementApiV1CompaniesTickerStatementsGet } from "@/api/generated/sdk.gen";
import { statementQueryOptions } from "@/api/statements";
import { errorResult, networkErrorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getStatementApiV1CompaniesTickerStatementsGet: vi.fn(),
  getCellApiV1CompaniesTickerStatementsCellGet: vi.fn(),
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
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
