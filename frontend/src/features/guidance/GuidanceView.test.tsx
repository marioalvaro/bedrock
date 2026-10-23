import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEntryApiV1CompaniesTickerGuidancePost,
  deleteEntryApiV1CompaniesTickerGuidanceGuidanceIdDelete,
  getGuidanceApiV1CompaniesTickerGuidanceGet,
  listMetricsApiV1CompaniesTickerGuidanceMetricsGet,
  updateEntryApiV1CompaniesTickerGuidanceGuidanceIdPut,
} from "@/api/generated/sdk.gen";
import { localIsoDate } from "@/lib/now";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { guidance, guidanceEntry, guidanceMetrics } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";

import { GuidanceView } from "./GuidanceView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getGuidanceApiV1CompaniesTickerGuidanceGet: vi.fn(),
  listMetricsApiV1CompaniesTickerGuidanceMetricsGet: vi.fn(),
  createEntryApiV1CompaniesTickerGuidancePost: vi.fn(),
  updateEntryApiV1CompaniesTickerGuidanceGuidanceIdPut: vi.fn(),
  deleteEntryApiV1CompaniesTickerGuidanceGuidanceIdDelete: vi.fn(),
}));

const getGuidance = vi.mocked(getGuidanceApiV1CompaniesTickerGuidanceGet);
const listMetrics = vi.mocked(listMetricsApiV1CompaniesTickerGuidanceMetricsGet);
const createEntry = vi.mocked(createEntryApiV1CompaniesTickerGuidancePost);
const updateEntry = vi.mocked(updateEntryApiV1CompaniesTickerGuidanceGuidanceIdPut);
const deleteEntry = vi.mocked(deleteEntryApiV1CompaniesTickerGuidanceGuidanceIdDelete);

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <GuidanceView ticker="AAPL" />
    </QueryClientProvider>,
  );
}

async function renderLoaded() {
  renderView();
  await waitFor(() => expect(entryRow(3)).not.toBeNull());
}

const entryRow = (id: number) => document.querySelector(`[data-entry-id="${id}"]`) as HTMLElement;
const verdict = (id: number) => within(entryRow(id)).getByTestId("verdict");

async function openForm() {
  await userEvent.click(screen.getByRole("button", { name: "Add guidance" }));
  await waitFor(() => expect(screen.getByLabelText("Metric")).toBeEnabled());
}

async function fill(metric: string, low: string, high: string) {
  await userEvent.selectOptions(screen.getByLabelText("Metric"), metric);
  await userEvent.type(screen.getByLabelText("Low"), low);
  await userEvent.type(screen.getByLabelText("High"), high);
}

const lastBody = () => createEntry.mock.calls.at(-1)![0]!.body as Record<string, unknown>;

beforeEach(() => {
  setScale("M");
  getGuidance.mockResolvedValue(okResult(guidance()) as never);
  listMetrics.mockResolvedValue(okResult(guidanceMetrics()) as never);
  createEntry.mockResolvedValue(okResult(guidanceEntry({ id: 9 }), 201) as never);
  updateEntry.mockResolvedValue(okResult(guidanceEntry({ id: 3 })) as never);
  deleteEntry.mockResolvedValue(okResult(null, 204) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("GuidanceView log", () => {
  it("summarizes the latest entries with the hit rate", async () => {
    await renderLoaded();
    expect(
      screen.getByText("1 beat · 0 in range · 1 miss · 1 pending · hit rate 50%"),
    ).toBeVisible();
  });

  it("shows a dash for a hit rate with nothing decided", async () => {
    getGuidance.mockResolvedValue(
      okResult(
        guidance({ summary: { beat: 0, in_range: 0, miss: 0, pending: 1, hit_rate: null } }),
      ) as never,
    );
    await renderLoaded();
    expect(screen.getByText("0 beat · 0 in range · 0 miss · 1 pending · hit rate —")).toBeVisible();
  });

  it("lists the counts per metric", async () => {
    await renderLoaded();
    const table = screen.getByRole("table", { name: "By metric" });
    const row = within(table).getByRole("row", { name: /Gross margin/ });
    expect(row).toHaveTextContent("Gross margin1000100%");
  });

  it("colors the verdicts", async () => {
    await renderLoaded();
    expect(verdict(3)).toHaveTextContent("Miss");
    expect(verdict(3)).toHaveClass("text-negative");
    expect(verdict(4)).toHaveTextContent("Beat");
    expect(verdict(4)).toHaveClass("text-positive");
    expect(verdict(5)).toHaveTextContent("Pending");
    expect(verdict(5)).not.toHaveClass("text-positive", "text-negative");
  });

  it("mutes and marks the revisions", async () => {
    await renderLoaded();
    expect(entryRow(1)).toHaveClass("text-muted-foreground");
    expect(entryRow(1)).toHaveTextContent("rev.");
    expect(entryRow(3)).not.toHaveClass("text-muted-foreground");
    expect(entryRow(3)).not.toHaveTextContent("rev.");
  });

  it("formats ranges and actuals by unit in the page scale", async () => {
    await renderLoaded();
    expect(entryRow(3)).toHaveTextContent("395,000 – 400,000");
    expect(entryRow(3)).toHaveTextContent("391,035");
    expect(entryRow(3)).toHaveTextContent("-1.2%");
    expect(entryRow(3)).toHaveTextContent("FY2024");
    expect(entryRow(4)).toHaveTextContent("45.0% – 46.0%");
    expect(entryRow(4)).toHaveTextContent("46.2%");
    expect(entryRow(4)).toHaveTextContent("Q4 FY2024");
  });

  it("follows the page scale", async () => {
    setScale("B");
    await renderLoaded();
    expect(entryRow(3)).toHaveTextContent("395.0 – 400.0");
  });

  it("shows a point estimate as one value", async () => {
    getGuidance.mockResolvedValue(
      okResult(
        guidance({ entries: [guidanceEntry({ id: 3, low: "0.46", high: "0.46", unit: "pct" })] }),
      ) as never,
    );
    await renderLoaded();
    expect(entryRow(3)).toHaveTextContent("46.0%");
    expect(entryRow(3)).not.toHaveTextContent("–");
  });

  it("shows an empty state", async () => {
    getGuidance.mockResolvedValue(
      okResult(
        guidance({
          entries: [],
          by_metric: [],
          summary: { beat: 0, in_range: 0, miss: 0, pending: 0, hit_rate: null },
        }),
      ) as never,
    );
    renderView();
    expect(await screen.findByText("No guidance yet.")).toBeVisible();
  });

  it("shows an error when the log cannot load", async () => {
    getGuidance.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("Could not load the guidance.")).toBeVisible();
  });
});

describe("GuidanceView form", () => {
  it("groups the metrics as Lines, Ratios and KPIs", async () => {
    await renderLoaded();
    await openForm();
    const groups = within(screen.getByLabelText("Metric")).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("label"))).toEqual(["Lines", "Ratios", "KPIs"]);
  });

  it("sends a percent metric as a fraction", async () => {
    await renderLoaded();
    await openForm();
    await fill("gross_margin", "46", "47");
    await userEvent.clear(screen.getByLabelText("Fiscal year"));
    await userEvent.type(screen.getByLabelText("Fiscal year"), "2025");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "Q1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(createEntry).toHaveBeenCalled());
    expect(createEntry.mock.calls[0]![0]!.path).toEqual({ ticker: "AAPL" });
    expect(lastBody()).toEqual({
      metric: "gross_margin",
      fiscal_year: 2025,
      fiscal_period: "Q1",
      low: "0.46",
      high: "0.47",
      basis: "reported",
      direction: "higher",
      given_on: localIsoDate(new Date()),
      source_note: null,
    });
  });

  it("reads a USD value in the page scale", async () => {
    setScale("B");
    await renderLoaded();
    await openForm();
    await fill("revenue", "380", "390");
    expect(screen.getByText("USD billions")).toBeVisible();
    await userEvent.type(screen.getByLabelText("Source note"), "  Q4 call ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(createEntry).toHaveBeenCalled());
    expect(lastBody()).toMatchObject({
      low: "380000000000",
      high: "390000000000",
      source_note: "Q4 call",
    });
  });

  it("offers quarters only for a quarterly metric", async () => {
    await renderLoaded();
    await openForm();
    await userEvent.selectOptions(screen.getByLabelText("Metric"), "revenue");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "Q2");
    await userEvent.selectOptions(screen.getByLabelText("Metric"), "roe");
    const period = screen.getByLabelText("Period");
    expect(
      within(period)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["FY"]);
    expect(period).toHaveValue("FY");
  });

  it("takes the direction from the metric", async () => {
    await renderLoaded();
    await openForm();
    await userEvent.selectOptions(screen.getByLabelText("Metric"), "sga");
    expect(screen.getByLabelText("Direction")).toHaveValue("lower");
    await userEvent.selectOptions(screen.getByLabelText("Metric"), "revenue");
    expect(screen.getByLabelText("Direction")).toHaveValue("higher");
  });

  it("says how to sign outflows", async () => {
    await renderLoaded();
    await openForm();
    expect(
      screen.getByText("Use the statements' sign: outflows such as capex are negative"),
    ).toBeVisible();
  });

  it("refuses text that is not a number", async () => {
    await renderLoaded();
    await openForm();
    await fill("revenue", "abc", "390");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number");
    expect(createEntry).not.toHaveBeenCalled();
  });

  it("shows the API's 422 detail", async () => {
    createEntry.mockResolvedValue(
      errorResult(422, { detail: "low must not be above high" }) as never,
    );
    await renderLoaded();
    await openForm();
    await fill("revenue", "400", "390");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("low must not be above high");
  });

  it("prefills an edit and sends a PUT", async () => {
    await renderLoaded();
    await userEvent.click(within(entryRow(3)).getByRole("button", { name: /^Edit/ }));
    expect(screen.getByLabelText("Metric")).toHaveValue("revenue");
    expect(screen.getByLabelText("Low")).toHaveValue("395000");
    expect(screen.getByLabelText("High")).toHaveValue("400000");
    expect(screen.getByLabelText("Given on")).toHaveValue("2024-05-02");
    await userEvent.clear(screen.getByLabelText("High"));
    await userEvent.type(screen.getByLabelText("High"), "401000");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateEntry).toHaveBeenCalled());
    const call = updateEntry.mock.calls[0]![0]!;
    expect(call.path).toEqual({ ticker: "AAPL", guidance_id: 3 });
    expect(call.body).toMatchObject({
      low: "395000000000",
      high: "401000000000",
      given_on: "2024-05-02",
    });
  });

  it("keeps a deleted KPI selectable on edit", async () => {
    listMetrics.mockResolvedValue(
      okResult(guidanceMetrics().filter((m) => m.metric !== "kpi:stores")) as never,
    );
    await renderLoaded();
    await userEvent.click(within(entryRow(5)).getByRole("button", { name: /^Edit/ }));
    expect(screen.getByLabelText("Metric")).toHaveValue("kpi:stores");
  });

  it("deletes an entry behind a confirmation", async () => {
    await renderLoaded();
    await userEvent.click(within(entryRow(3)).getByRole("button", { name: /^Delete/ }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(deleteEntry).toHaveBeenCalledWith({ path: { ticker: "AAPL", guidance_id: 3 } }),
    );
  });
});
