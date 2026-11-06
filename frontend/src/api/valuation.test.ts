import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import { ApiError } from "@/api/errors";
import {
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet,
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet,
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet,
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
  putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut,
  resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost,
} from "@/api/generated/sdk.gen";
import {
  ValuationUnavailable,
  sensitivityGridQueryOptions,
  tornadoQueryOptions,
  usePutValuationInputs,
  useResetValuationInputs,
  valuationInputsQueryOptions,
  valuationQueryOptions,
  valuationSummaryQueryOptions,
} from "@/api/valuation";
import { errorResult, okResult } from "@/test/responses";
import {
  sensitivityGrid,
  tornado,
  valuation,
  valuationInputs,
  valuationSummary,
} from "@/test/valuation";

vi.mock("@/api/generated/sdk.gen", () => ({
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet: vi.fn(),
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet: vi.fn(),
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet: vi.fn(),
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet: vi.fn(),
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet: vi.fn(),
  putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut: vi.fn(),
  resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost:
    vi.fn(),
}));

const getInputs = vi.mocked(
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet,
);
const getValuation = vi.mocked(
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet,
);
const getSummary = vi.mocked(
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
);
const putInputs = vi.mocked(
  putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut,
);
const resetInputs = vi.mocked(
  resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost,
);

const getTornado = vi.mocked(
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet,
);
const getGrid = vi.mocked(
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
);

afterEach(() => vi.clearAllMocks());

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

const aapl = companyKey("AAPL");
// A 200 with the Vite fallback's HTML shell (Gotcha G2).
const html = () => okResult("<!doctype html><html></html>") as never;

describe("keys", () => {
  it("nest every valuation query under [company, 'scenarios', id]", () => {
    expect(valuationInputsQueryOptions("AAPL", 2, "bull").queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "bull",
      "valuation-inputs",
    ]);
    expect(valuationQueryOptions("AAPL", 2, "bear").queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "bear",
      "valuation",
    ]);
    expect(valuationSummaryQueryOptions("AAPL", 2).queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "valuation-summary",
    ]);
    expect(tornadoQueryOptions("AAPL", 2, "bull").queryKey).toEqual([
      ...aapl,
      "scenarios",
      2,
      "bull",
      "tornado",
    ]);
    expect(
      sensitivityGridQueryOptions("AAPL", 2, "bear", "discount_rate", "revenue_growth").queryKey,
    ).toEqual([
      ...aapl,
      "scenarios",
      2,
      "bear",
      "sensitivity-grid",
      "discount_rate",
      "revenue_growth",
    ]);
  });
});

const queries = [
  {
    name: "valuationInputsQueryOptions",
    options: () => valuationInputsQueryOptions("AAPL", 2, "bull"),
    sdk: getInputs,
    args: { path: { ticker: "AAPL", scenario_id: 2, case: "bull" } },
    body: valuationInputs({ scenario_id: 2, case: "bull" }),
    bad: { ...valuationInputs(), rows: null },
  },
  {
    name: "valuationQueryOptions",
    options: () => valuationQueryOptions("AAPL", 2, "bull"),
    sdk: getValuation,
    args: { path: { ticker: "AAPL", scenario_id: 2, case: "bull" } },
    body: valuation({ scenario_id: 2, case: "bull" }),
    bad: { ...valuation(), results: null },
  },
  {
    name: "valuationSummaryQueryOptions",
    options: () => valuationSummaryQueryOptions("AAPL", 2),
    sdk: getSummary,
    args: { path: { ticker: "AAPL", scenario_id: 2 } },
    body: valuationSummary({ scenario_id: 2 }),
    bad: { ...valuationSummary(), cases: null },
  },
  {
    name: "tornadoQueryOptions",
    options: () => tornadoQueryOptions("AAPL", 2, "bull"),
    sdk: getTornado,
    args: { path: { ticker: "AAPL", scenario_id: 2, case: "bull" } },
    body: tornado({ scenario_id: 2, case: "bull" }),
    bad: { ...tornado(), bars: null },
  },
  {
    name: "sensitivityGridQueryOptions",
    options: () =>
      sensitivityGridQueryOptions("AAPL", 2, "bull", "discount_rate", "terminal_growth"),
    sdk: getGrid,
    args: {
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      query: { x: "discount_rate", y: "terminal_growth" },
    },
    body: sensitivityGrid({ scenario_id: 2, case: "bull" }),
    bad: { ...sensitivityGrid(), x: null },
  },
];

describe.each(queries)("$name", ({ options, sdk, args, body, bad }) => {
  const run = () => {
    const { queryClient } = setup();
    return queryClient.fetchQuery(options() as never);
  };

  it("calls the SDK and returns the body", async () => {
    sdk.mockResolvedValue(okResult(body) as never);
    await expect(run()).resolves.toEqual(body);
    expect(sdk).toHaveBeenCalledWith(args);
  });

  it("rejects a 200 with the HTML shell or a body of the wrong shape", async () => {
    sdk.mockResolvedValue(html());
    await expect(run()).rejects.toMatchObject({ status: 200 });
    sdk.mockResolvedValue(okResult(bad) as never);
    await expect(run()).rejects.toMatchObject({ status: 200 });
  });

  it("rejects a 422 with ValuationUnavailable and its detail", async () => {
    sdk.mockResolvedValue(errorResult(422, { detail: "Set these drivers: gross_margin" }) as never);
    const error = await run().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ValuationUnavailable);
    expect((error as ValuationUnavailable).detail).toBe("Set these drivers: gross_margin");
  });

  it("rejects another failure as a plain ApiError", async () => {
    sdk.mockResolvedValue(errorResult(404, { detail: "Scenario not found" }) as never);
    const error = await run().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(ValuationUnavailable);
    expect((error as ApiError).status).toBe(404);
  });
});

// The keys an input write of AAPL scenario 2 Bull moves, and the ones it leaves alone.
const edited = [...aapl, "scenarios", 2, "bull", "valuation-inputs"];
const moved = [
  [...aapl, "scenarios", 2, "base", "valuation-inputs"],
  [...aapl, "scenarios", 2, "bull", "valuation"],
  [...aapl, "scenarios", 2, "valuation-summary"],
];
const untouched = [
  [...aapl, "scenarios", 3, "bull", "valuation"],
  [...aapl, "scenarios"],
  [...companyKey("MSFT"), "scenarios", 2, "valuation-summary"],
];

function seed(queryClient: QueryClient) {
  for (const key of [edited, ...moved, ...untouched]) queryClient.setQueryData(key, {});
}

function expectSettled(queryClient: QueryClient, reply: unknown) {
  expect(queryClient.getQueryData(edited)).toEqual(reply);
  expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(false);
  for (const key of moved) {
    expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
  }
  for (const key of untouched) {
    expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
  }
}

describe("usePutValuationInputs", () => {
  const rows = [{ code: "beta", value: "1.2" }];

  it("puts the rows, takes the reply as the case's inputs and marks the scenario stale", async () => {
    const reply = valuationInputs({ scenario_id: 2, case: "bull", warnings: ["saved"] });
    putInputs.mockResolvedValue(okResult(reply) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => usePutValuationInputs("AAPL"), { wrapper });

    result.current.mutate({ id: 2, case: "bull", rows });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(putInputs).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      body: { rows },
    });
    expectSettled(queryClient, reply);
  });

  it("does not apply a reply while another input write of the company runs", async () => {
    let finishFirst: (value: unknown) => void = () => {};
    putInputs
      .mockReturnValueOnce(new Promise((resolve) => (finishFirst = resolve)) as never)
      .mockResolvedValueOnce(okResult(valuationInputs({ warnings: ["second"] })) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const first = renderHook(() => usePutValuationInputs("AAPL"), { wrapper });
    const second = renderHook(() => usePutValuationInputs("AAPL"), { wrapper });

    first.result.current.mutate({ id: 2, case: "bull", rows });
    second.result.current.mutate({ id: 2, case: "bull", rows });
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));
    // The second reply landed while the first still ran: not applied, the inputs are stale.
    expect(queryClient.getQueryData(edited)).toEqual({});
    expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(true);

    finishFirst(okResult(valuationInputs({ warnings: ["first"] })));
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryState(edited)?.isInvalidated).toBe(true);
  });

  it("keeps the API's 422 detail and changes no cache", async () => {
    putInputs.mockResolvedValue(errorResult(422, { detail: "beta must be in [0, 5]" }) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => usePutValuationInputs("AAPL"), { wrapper });

    result.current.mutate({ id: 2, case: "bull", rows });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiError).detail).toBe("beta must be in [0, 5]");
    for (const key of [edited, ...moved]) {
      expect(queryClient.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(false);
    }
  });
});

describe("useResetValuationInputs", () => {
  it("posts the reset and settles like a PUT", async () => {
    const reply = valuationInputs({ scenario_id: 2, case: "bull" });
    resetInputs.mockResolvedValue(okResult(reply) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useResetValuationInputs("AAPL"), { wrapper });

    result.current.mutate({ id: 2, case: "bull" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(resetInputs).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
    });
    expectSettled(queryClient, reply);
  });

  it("rejects a 200 of the wrong shape and applies nothing", async () => {
    resetInputs.mockResolvedValue(html());
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useResetValuationInputs("AAPL"), { wrapper });

    result.current.mutate({ id: 2, case: "bull" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(queryClient.getQueryData(edited)).toEqual({});
  });
});
