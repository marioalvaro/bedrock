import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  classificationStatusKey,
  classificationStatusQueryOptions,
  classificationsQueryOptions,
  RUN_POLL_MS,
  useAnswerLine,
  useDecideClassification,
  useSetClassificationMode,
  useStartRun,
} from "@/api/classification";
import { companyKey } from "@/api/companies";
import {
  answerApiV1CompaniesTickerClassificationsPut,
  decideApiV1CompaniesTickerClassificationsClassificationIdPut,
  getClassificationsOfApiV1CompaniesTickerClassificationsGet,
  getStatusApiV1ClassificationStatusGet,
  setModeApiV1CompaniesTickerClassificationModePut,
  startRunApiV1CompaniesTickerClassificationsRunPost,
} from "@/api/generated/sdk.gen";
import { classificationRun, classifications, classifierStatus } from "@/test/classification";
import { errorResult, okResult } from "@/test/responses";

vi.mock("@/api/generated/sdk.gen", () => ({
  getStatusApiV1ClassificationStatusGet: vi.fn(),
  getClassificationsOfApiV1CompaniesTickerClassificationsGet: vi.fn(),
  startRunApiV1CompaniesTickerClassificationsRunPost: vi.fn(),
  decideApiV1CompaniesTickerClassificationsClassificationIdPut: vi.fn(),
  answerApiV1CompaniesTickerClassificationsPut: vi.fn(),
  setModeApiV1CompaniesTickerClassificationModePut: vi.fn(),
}));

const getStatus = vi.mocked(getStatusApiV1ClassificationStatusGet);
const getList = vi.mocked(getClassificationsOfApiV1CompaniesTickerClassificationsGet);
const startRun = vi.mocked(startRunApiV1CompaniesTickerClassificationsRunPost);
const decide = vi.mocked(decideApiV1CompaniesTickerClassificationsClassificationIdPut);
const answer = vi.mocked(answerApiV1CompaniesTickerClassificationsPut);
const setMode = vi.mocked(setModeApiV1CompaniesTickerClassificationModePut);

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

afterEach(() => vi.clearAllMocks());

// What a decision or a mode change can move: every view of the company.
const companyViews = [
  [...companyKey("AAPL"), "classifications", "claude:claude-haiku-5-5"],
  [...companyKey("AAPL"), "statements", "IS", "annual", "total", "reported"],
  [...companyKey("AAPL"), "mapping-gaps"],
  [...companyKey("AAPL"), "as-reported", "BS", null],
  companyKey("AAPL"),
];
const otherCompany = [...companyKey("MSFT"), "statements", "IS", "annual", "total", "reported"];

function seed(queryClient: QueryClient) {
  for (const key of [...companyViews, otherCompany, classificationStatusKey]) {
    queryClient.setQueryData(key, {});
  }
}

// The three decision hooks, as one shape for `it.each`.
type AnyMutation = () => {
  mutate: (variables: never) => void;
  isSuccess: boolean;
};

const invalidated = (queryClient: QueryClient, key: readonly unknown[]) =>
  queryClient.getQueryState(key)?.isInvalidated;

describe("classificationStatusQueryOptions", () => {
  it("returns the status", async () => {
    getStatus.mockResolvedValue(okResult(classifierStatus()) as never);
    const { queryClient } = setup();
    const status = await queryClient.fetchQuery(classificationStatusQueryOptions());
    expect(status.classifiers.map((c) => c.name)).toContain("claude:claude-haiku-5-5");
  });

  it("rejects a 200 with a wrong body (Gotcha G2)", async () => {
    getStatus.mockResolvedValue(okResult("<html></html>") as never);
    const { queryClient } = setup();
    await expect(queryClient.fetchQuery(classificationStatusQueryOptions())).rejects.toMatchObject({
      status: 200,
      detail: "Unexpected response",
    });
  });
});

describe("classificationsQueryOptions", () => {
  it("sends the classifier and keys by it", async () => {
    getList.mockResolvedValue(okResult(classifications()) as never);
    const { queryClient } = setup();
    await queryClient.fetchQuery(classificationsQueryOptions("AAPL", "claude:claude-haiku-5-5"));
    expect(getList).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { classifier: "claude:claude-haiku-5-5" },
    });
    expect(classificationsQueryOptions("AAPL", null).queryKey).toEqual([
      ...companyKey("AAPL"),
      "classifications",
      null,
    ]);
  });

  it("sends no classifier when none is chosen", async () => {
    getList.mockResolvedValue(okResult(classifications()) as never);
    const { queryClient } = setup();
    await queryClient.fetchQuery(classificationsQueryOptions("AAPL", null));
    expect(getList).toHaveBeenCalledWith({ path: { ticker: "AAPL" }, query: {} });
  });

  it("rejects a 200 without its lines", async () => {
    getList.mockResolvedValue(okResult({ mode: "off" }) as never);
    const { queryClient } = setup();
    await expect(
      queryClient.fetchQuery(classificationsQueryOptions("AAPL", null)),
    ).rejects.toMatchObject({ status: 200, detail: "Unexpected response" });
  });

  it("polls every 2 seconds while the newest run is running, and not otherwise", () => {
    const interval = classificationsQueryOptions("AAPL", null).refetchInterval as (query: {
      state: { data: unknown };
    }) => number | false;
    const running = classifications({ run: classificationRun({ status: "running" }) });
    expect(RUN_POLL_MS).toBe(2000);
    expect(interval({ state: { data: running } })).toBe(2000);
    for (const status of ["done", "failed", "stopped"] as const) {
      const ended = classifications({ run: classificationRun({ status }) });
      expect(interval({ state: { data: ended } })).toBe(false);
    }
    expect(interval({ state: { data: classifications({ run: null }) } })).toBe(false);
    expect(interval({ state: { data: undefined } })).toBe(false);
  });

  it("polls at a given interval", () => {
    const interval = classificationsQueryOptions("AAPL", null, 25).refetchInterval as (query: {
      state: { data: unknown };
    }) => number | false;
    const running = classifications({ run: classificationRun({ status: "running" }) });
    expect(interval({ state: { data: running } })).toBe(25);
  });
});

describe("mutations", () => {
  it("starts a run with the confirmed count and refreshes the list and the usage", async () => {
    startRun.mockResolvedValue(okResult(classificationRun(), 202) as never);
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useStartRun("AAPL"), { wrapper });

    result.current.mutate({ classifier: "claude:claude-haiku-5-5", confirm_lines: 7 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(startRun).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { classifier: "claude:claude-haiku-5-5", confirm_lines: 7 },
    });
    expect(invalidated(queryClient, companyViews[0] as unknown[])).toBe(true);
    expect(invalidated(queryClient, classificationStatusKey)).toBe(true);
  });

  it("refetches the list after a refused run, so the button shows what is left", async () => {
    startRun.mockResolvedValue(
      errorResult(409, {
        detail: "Nothing is left to classify.",
        code: "nothing_to_classify",
      }) as never,
    );
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(() => useStartRun("AAPL"), { wrapper });

    result.current.mutate({ classifier: "claude:claude-haiku-5-5", confirm_lines: 7 });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({
      status: 409,
      detail: "Nothing is left to classify.",
    });
    expect(invalidated(queryClient, companyViews[0] as unknown[])).toBe(true);
  });

  it.each<[string, AnyMutation, unknown, () => void]>([
    [
      "a decision",
      () => {
        decide.mockResolvedValue(okResult({}) as never);
        return useDecideClassification("AAPL");
      },
      { id: 4, status: "accepted" },
      () =>
        expect(decide).toHaveBeenCalledWith({
          path: { ticker: "AAPL", classification_id: 4 },
          body: { status: "accepted" },
        }),
    ],
    [
      "an answer",
      () => {
        answer.mockResolvedValue(okResult({}) as never);
        return useAnswerLine("AAPL");
      },
      { statement: "IS", taxonomy: "aapl", concept: "Foo", codes: ["sga"] },
      () =>
        expect(answer).toHaveBeenCalledWith({
          path: { ticker: "AAPL" },
          body: { statement: "IS", taxonomy: "aapl", concept: "Foo", codes: ["sga"] },
        }),
    ],
    [
      "a mode change",
      () => {
        setMode.mockResolvedValue(okResult({}) as never);
        return useSetClassificationMode("AAPL");
      },
      { mode: "all", source: "claude:claude-haiku-5-5" },
      () =>
        expect(setMode).toHaveBeenCalledWith({
          path: { ticker: "AAPL" },
          body: { mode: "all", source: "claude:claude-haiku-5-5" },
        }),
    ],
  ])("%s refreshes every view of the company and no other", async (_name, hook, vars, sent) => {
    const { queryClient, wrapper } = setup();
    seed(queryClient);
    const { result } = renderHook(hook, { wrapper });

    (result.current.mutate as (variables: unknown) => void)(vars);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    sent();
    for (const key of companyViews) {
      expect(invalidated(queryClient, key), JSON.stringify(key)).toBe(true);
    }
    expect(invalidated(queryClient, otherCompany)).toBe(false);
  });
});
