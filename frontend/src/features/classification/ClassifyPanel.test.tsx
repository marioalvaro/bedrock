import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { companyKey } from "@/api/companies";
import {
  answerApiV1CompaniesTickerClassificationsPut,
  getCompanyApiV1CompaniesTickerGet,
  decideApiV1CompaniesTickerClassificationsClassificationIdPut,
  getClassificationsOfApiV1CompaniesTickerClassificationsGet,
  getStatusApiV1ClassificationStatusGet,
  setModeApiV1CompaniesTickerClassificationModePut,
  startRunApiV1CompaniesTickerClassificationsRunPost,
} from "@/api/generated/sdk.gen";
import type { UnclassifiedLineOut } from "@/api/generated/types.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import {
  answerOut,
  classificationRun,
  classifications,
  classifiedLine,
  classifierStatus,
  noClassifierStatus,
} from "@/test/classification";
import { companyItem } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import { ClassifyPanel } from "./ClassifyPanel";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompanyApiV1CompaniesTickerGet: vi.fn(),
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

const HAIKU = "claude:claude-haiku-5-5";
const LUNA = "openrouter:openai/gpt-6-luna";

const gapsLine: UnclassifiedLineOut = {
  statement: "CF",
  taxonomy: "msft",
  concept: "DepreciationAmortizationAndOther",
  label: "Depreciation, amortization, and other",
  latest_value: "22287000000",
  latest_period_end: "2024-06-30",
  filings: ["0000950170-24-087843"],
};

function renderPanel(pollMs?: number): QueryClient {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <ClassifyPanel ticker="AAPL" unclassified={[gapsLine]} pollMs={pollMs} />
    </QueryClientProvider>,
  );
  return queryClient;
}

const table = () => screen.findByRole("table", { name: "Lines to classify" });
const rowOf = async (label: string) =>
  within(await table())
    .getByText(label)
    .closest("tr") as HTMLElement;

beforeEach(() => {
  setScale("M");
  vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(okResult(companyItem()) as never);
  getStatus.mockResolvedValue(okResult(classifierStatus()) as never);
  getList.mockResolvedValue(okResult(classifications()) as never);
  startRun.mockResolvedValue(
    okResult(classificationRun({ status: "running", lines_answered: 0 }), 202) as never,
  );
  decide.mockResolvedValue(okResult(answerOut()) as never);
  answer.mockResolvedValue(okResult(answerOut({ classifier: "user" })) as never);
  setMode.mockResolvedValue(okResult(companyItem()) as never);
});

afterEach(() => vi.clearAllMocks());

describe("ClassifyPanel without a classifier", () => {
  beforeEach(() => getStatus.mockResolvedValue(okResult(noClassifierStatus()) as never));

  it("keeps today's table and its sentence, says why, and offers no button", async () => {
    renderPanel();
    expect(
      await screen.findByText("No classifier is configured. See Settings."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Map it in the company's override file, or list it under other_lines."),
    ).toBeInTheDocument();
    const row = await rowOf("Depreciation, amortization, and other");
    expect(within(row).getByText("0000950170-24-087843")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Classify/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Classification mode")).not.toBeInTheDocument();
    expect(getList).not.toHaveBeenCalled();
  });
});

describe("ClassifyPanel with a classifier", () => {
  it("lists only the configured classifiers and asks for the chosen one", async () => {
    renderPanel();
    const select = (await screen.findByLabelText("Classifier")) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual([HAIKU, LUNA]);
    await waitFor(() =>
      expect(getList).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        query: { classifier: HAIKU },
      }),
    );

    await userEvent.selectOptions(select, LUNA);

    await waitFor(() =>
      expect(getList).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { classifier: LUNA },
      }),
    );
  });

  it("starts from the company's source when it is configured, asking only for it", async () => {
    vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
      okResult(companyItem({ classification_mode: "all", classification_source: LUNA })) as never,
    );
    getList.mockResolvedValue(okResult(classifications({ mode: "all", source: LUNA })) as never);
    renderPanel();
    await screen.findByRole("button", { name: "Classify 2 lines" });
    expect((screen.getByLabelText("Classifier") as HTMLSelectElement).value).toBe(LUNA);
    expect(getList.mock.calls.map((call) => call[0]?.query)).toEqual([{ classifier: LUNA }]);
  });

  it("counts the lines a run would ask on its button", async () => {
    renderPanel();
    expect(await screen.findByRole("button", { name: "Classify 2 lines" })).toBeEnabled();
    expect(screen.getByText("Lines to classify (2)")).toBeInTheDocument();
  });

  it("disables the button when nothing is left to ask", async () => {
    getList.mockResolvedValue(okResult(classifications({ to_ask: 0 })) as never);
    renderPanel();
    expect(await screen.findByRole("button", { name: "Classify 0 lines" })).toBeDisabled();
  });

  it("shows the confirmation's numbers and posts the confirmed count", async () => {
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Classify 2 lines" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Classify 2 lines?")).toBeInTheDocument();
    const field = (name: string) =>
      within(dialog).getByText(name).nextElementSibling?.textContent ?? "";
    expect(field("Lines")).toBe("2");
    expect(field("Classifier")).toBe(HAIKU);
    expect(field("Estimated tokens")).toBe("1,200 in + 300 out");
    expect(field("Estimated cost")).toBe("$0.0027");
    expect(field("Tokens left today")).toBe("187,500");
    expect(field("Tokens left this month")).toBe("1,520,000");
    expect(
      within(dialog).getByText("This sends the lines' labels, tags and amounts to Anthropic."),
    ).toBeInTheDocument();
    expect(startRun).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(startRun).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: { classifier: HAIKU, confirm_lines: 2 },
      }),
    );
  });

  it("sends nothing when the confirmation is cancelled", async () => {
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Classify 2 lines" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(startRun).not.toHaveBeenCalled();
  });

  it("shows a refused run's message and refetches the list", async () => {
    startRun.mockResolvedValue(
      errorResult(409, {
        detail: "2 lines were confirmed but 1 would be sent now.",
        code: "stale_estimate",
      }) as never,
    );
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Classify 2 lines" }));
    const calls = getList.mock.calls.length;
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Confirm" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "2 lines were confirmed but 1 would be sent now.",
    );
    await waitFor(() => expect(getList.mock.calls.length).toBeGreaterThan(calls));
  });

  it("shows the progress while a run runs, then stops polling and refreshes the company", async () => {
    getList
      .mockResolvedValueOnce(
        okResult(
          classifications({
            run: classificationRun({ status: "running", lines_asked: 2, lines_answered: 1 }),
          }),
        ) as never,
      )
      .mockResolvedValue(okResult(classifications({ run: classificationRun() })) as never);
    const queryClient = renderPanel(20);
    const statements = [...companyKey("AAPL"), "statements", "IS", "annual", "total", "reported"];
    queryClient.setQueryData(statements, {});

    expect(await screen.findByText("Classifying… 1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Classify 2 lines" })).toBeDisabled();
    await waitFor(() => expect(screen.queryByText(/Classifying…/)).not.toBeInTheDocument());
    await waitFor(() => expect(queryClient.getQueryState(statements)?.isInvalidated).toBe(true));

    const settled = getList.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(getList.mock.calls.length).toBe(settled);
  });

  it("shows the reason of a stopped run above the table", async () => {
    getList.mockResolvedValue(
      okResult(
        classifications({
          run: classificationRun({
            status: "stopped",
            error: "Stopped: 550 tokens are needed and 0 are left of the daily budget",
          }),
        }),
      ) as never,
    );
    renderPanel();
    expect(
      await screen.findByText(
        "The last run stopped. Stopped: 550 tokens are needed and 0 are left of the daily budget",
      ),
    ).toBeInTheDocument();
  });

  it("shows each answer with its classifier, proposal, confidence and status", async () => {
    getList.mockResolvedValue(
      okResult(
        classifications({
          lines: [
            classifiedLine({
              answers: [
                answerOut({ id: 11, classifier: HAIKU, codes: ["sga", "rnd"] }),
                answerOut({
                  id: 12,
                  classifier: LUNA,
                  codes: [],
                  confidence: "0.6200",
                  status: "rejected",
                }),
              ],
            }),
          ],
        }),
      ) as never,
    );
    renderPanel();
    const first = await rowOf("Marketing expense");
    expect(within(first).getByText(HAIKU)).toBeInTheDocument();
    expect(
      within(first).getByText("Combined: SG&A + Research and development"),
    ).toBeInTheDocument();
    expect(within(first).getByText("95%")).toBeInTheDocument();
    expect(within(first).getByText("Proposed")).toBeInTheDocument();
    const second = within(await table())
      .getByText(LUNA)
      .closest("tr") as HTMLElement;
    expect(second).not.toBe(first);
    expect(second).toHaveClass("row-sub");
    expect(within(second).getByText("Other")).toBeInTheDocument();
    expect(within(second).getByText("62%")).toBeInTheDocument();
    expect(within(second).getByText("Rejected")).toBeInTheDocument();
    expect(within(second).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(within(second).getByRole("button", { name: "Accept" })).toBeInTheDocument();
  });

  it("shows a line nobody answered yet with a dash", async () => {
    renderPanel();
    const row = await rowOf("Marketing expense");
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
    expect(within(row).queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
  });

  it("accepts and rejects an answer", async () => {
    getList.mockResolvedValue(
      okResult(
        classifications({ lines: [classifiedLine({ answers: [answerOut({ id: 11 })] })] }),
      ) as never,
    );
    renderPanel();
    const row = await rowOf("Marketing expense");

    await userEvent.click(within(row).getByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith({
        path: { ticker: "AAPL", classification_id: 11 },
        body: { status: "accepted" },
      }),
    );
    await userEvent.click(within(row).getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(decide).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL", classification_id: 11 },
        body: { status: "rejected" },
      }),
    );
  });

  it("saves the user's own answer from Change: a candidate, or Other for none", async () => {
    renderPanel();
    const row = await rowOf("Marketing expense");
    const change = within(row).getByLabelText("Change Marketing expense") as HTMLSelectElement;
    expect(Array.from(change.options).map((o) => o.textContent)).toEqual([
      "Change…",
      "SG&A",
      "Research and development",
      "Other",
    ]);

    await userEvent.selectOptions(change, "rnd");
    await waitFor(() =>
      expect(answer).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: { statement: "IS", taxonomy: "aapl", concept: "MarketingExpense", codes: ["rnd"] },
      }),
    );

    await userEvent.selectOptions(change, "Other");
    await waitFor(() =>
      expect(answer).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        body: { statement: "IS", taxonomy: "aapl", concept: "MarketingExpense", codes: [] },
      }),
    );
  });

  it("shows the company's mode and changes it", async () => {
    getList.mockResolvedValue(
      okResult(classifications({ mode: "accepted", source: null })) as never,
    );
    renderPanel();
    const mode = await screen.findByLabelText("Classification mode");
    expect(within(mode).getByRole("radio", { name: "Accepted only" })).toBeChecked();

    await userEvent.click(within(mode).getByRole("radio", { name: "All above 90%" }));
    await waitFor(() =>
      expect(setMode).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: { mode: "all", source: HAIKU },
      }),
    );

    await userEvent.click(within(mode).getByRole("radio", { name: "Off" }));
    await waitFor(() =>
      expect(setMode).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        body: { mode: "off", source: null },
      }),
    );
  });

  it("shows a decision's error", async () => {
    getList.mockResolvedValue(
      okResult(
        classifications({ lines: [classifiedLine({ answers: [answerOut({ id: 11 })] })] }),
      ) as never,
    );
    decide.mockResolvedValue(errorResult(422, { detail: "Not a candidate." }) as never);
    renderPanel();
    await userEvent.click(
      within(await rowOf("Marketing expense")).getByRole("button", { name: "Accept" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Not a candidate.");
  });

  it("shows loading, then an error, when the lines cannot be read", async () => {
    getList.mockResolvedValue(errorResult(500) as never);
    renderPanel();
    expect(await screen.findByText("Could not load the lines to classify.")).toBeInTheDocument();
  });

  it("says so when no line is left to classify", async () => {
    getList.mockResolvedValue(okResult(classifications({ lines: [], to_ask: 0 })) as never);
    renderPanel();
    expect(await screen.findByText("No lines to classify.")).toBeInTheDocument();
  });
});
