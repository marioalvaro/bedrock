import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getStatusApiV1ClassificationStatusGet } from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { classifierStatus, noClassifierStatus } from "@/test/classification";
import { errorResult, okResult } from "@/test/responses";

import { ClassifierStatus } from "./ClassifierStatus";

vi.mock("@/api/generated/sdk.gen", () => ({
  getStatusApiV1ClassificationStatusGet: vi.fn(),
}));

const getStatus = vi.mocked(getStatusApiV1ClassificationStatusGet);

function renderStatus() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <ClassifierStatus />
    </QueryClientProvider>,
  );
}

beforeEach(() => getStatus.mockResolvedValue(okResult(classifierStatus()) as never));
afterEach(() => vi.clearAllMocks());

describe("ClassifierStatus", () => {
  it("lists each classifier with whether its key is set", async () => {
    renderStatus();
    const list = await screen.findByRole("table", { name: "Classifiers" });
    const row = (name: string) => within(list).getByText(name).closest("tr") as HTMLElement;
    expect(within(row("claude:claude-haiku-5-5")).getByText("key set")).toBeInTheDocument();
    expect(within(row("claude:claude-sonnet-5-5")).getByText("no key")).toBeInTheDocument();
    expect(within(row("openrouter:openai/gpt-6-luna")).getByText("key set")).toBeInTheDocument();
    expect(within(row("jev:jev-latest")).getByText("no key")).toBeInTheDocument();
  });

  it("shows the tokens used against the budgets and the estimated cost this month", async () => {
    renderStatus();
    expect(await screen.findByText("12,500 of 200,000 tokens")).toBeInTheDocument();
    expect(screen.getByText("480,000 of 2,000,000 tokens")).toBeInTheDocument();
    expect(screen.getByText("$0.41")).toBeInTheDocument();
  });

  it("reminds that the budgets only limit this app", async () => {
    renderStatus();
    expect(
      await screen.findByText(
        "Set a spending limit in the provider's console as well: these budgets only limit this app.",
      ),
    ).toBeInTheDocument();
  });

  it("shows every classifier as without a key when none is set", async () => {
    getStatus.mockResolvedValue(okResult(noClassifierStatus()) as never);
    renderStatus();
    await screen.findByRole("table", { name: "Classifiers" });
    expect(screen.getAllByText("no key")).toHaveLength(4);
    expect(screen.queryByText("key set")).not.toBeInTheDocument();
    expect(screen.getByText("0 of 200,000 tokens")).toBeInTheDocument();
  });

  it("shows loading, then an error", async () => {
    getStatus.mockResolvedValue(errorResult(500) as never);
    renderStatus();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the classifier status.")).toBeInTheDocument();
  });
});
