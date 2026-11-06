import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet } from "@/api/generated/sdk.gen";
import { errorResult, okResult } from "@/test/responses";
import { valuationSummary } from "@/test/valuation";
import { renderWithClient } from "@/test/valuationView";

import { ValuationSummary } from "./ValuationSummary";

vi.mock("@/api/generated/sdk.gen", () => ({
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet: vi.fn(),
}));

const getSummary = vi.mocked(
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
);

afterEach(() => vi.clearAllMocks());

const renderSummary = (scenarioCase: "base" | "bull" | "bear" = "base") =>
  renderWithClient(<ValuationSummary ticker="AAPL" scenarioId={1} scenarioCase={scenarioCase} />);

async function loaded() {
  return screen.findByRole("table", { name: "Valuation by case" });
}

const row = (table: HTMLElement, method: string) =>
  within(table).getByRole("rowheader", { name: method }).closest("tr") as HTMLElement;

describe("ValuationSummary", () => {
  it("sits in its own card", async () => {
    getSummary.mockResolvedValue(okResult(valuationSummary()) as never);
    renderSummary();
    expect(await screen.findByRole("region", { name: "Summary" })).toHaveClass(
      "rounded-lg",
      "border",
    );
  });

  it("is titled by what it shows and shades the picked case's column", async () => {
    getSummary.mockResolvedValue(okResult(valuationSummary()) as never);
    renderSummary("bear");
    const table = await loaded();
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(
      within(summary).getByRole("heading", { name: "Target price by case" }),
    ).toBeInTheDocument();
    const header = within(table).getByRole("columnheader", { name: "Bear" });
    expect(header).toHaveClass("bg-muted");
    const row = within(table).getByRole("rowheader", { name: "DCF (FCFF)" }).closest("tr")!;
    const [bull, , bear] = within(row).getAllByRole("cell");
    expect(bear).toHaveClass("bg-muted");
    expect(bull).not.toHaveClass("bg-muted");
  });

  it("asks for the scenario's summary and shows the price line", async () => {
    getSummary.mockResolvedValue(okResult(valuationSummary()) as never);
    renderSummary();
    await loaded();
    expect(getSummary).toHaveBeenCalledWith({ path: { ticker: "AAPL", scenario_id: 1 } });
    expect(screen.getByText("Price $336.67 · close of 2026-10-07")).toBeInTheDocument();
  });

  it("puts Bull, Base and Bear in that order, in their colors, the picked case bold", async () => {
    getSummary.mockResolvedValue(okResult(valuationSummary()) as never);
    renderSummary("bear");
    const table = await loaded();
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(["Method", "Bull", "Base", "Bear"]);
    expect(headers[1]).toHaveClass("text-positive");
    expect(headers[2]).toHaveClass("text-chart-1");
    expect(headers[3]).toHaveClass("text-negative");
    expect(headers[3]).toHaveClass("font-bold");
    expect(headers[2]).not.toHaveClass("font-bold");
  });

  it("shows each method's value per share above its upside, colored by sign", async () => {
    getSummary.mockResolvedValue(okResult(valuationSummary()) as never);
    renderSummary();
    const table = await loaded();
    const cells = within(row(table, "DCF (FCFF)")).getAllByRole("cell");
    // Bull, Base, Bear.
    expect(cells[0]).toHaveTextContent("$353.15+4.9%");
    expect(within(cells[0]!).getByText("+4.9%")).toHaveClass("text-positive");
    expect(cells[1]).toHaveTextContent("$131.83-60.8%");
    expect(within(cells[1]!).getByText("-60.8%")).toHaveClass("text-negative");
    expect(cells[2]).toHaveTextContent("$112.91");
  });

  it("shows a method's error in its cells", async () => {
    getSummary.mockResolvedValue(okResult(valuationSummary()) as never);
    renderSummary();
    const table = await loaded();
    const cells = within(row(table, "EV/EBITDA")).getAllByRole("cell");
    expect(cells).toHaveLength(3);
    for (const cell of cells) {
      expect(cell).toHaveTextContent("EV/EBITDA: fewer than 3 years of history");
    }
  });

  it("shows a case that cannot run by its error in every row", async () => {
    const summary = valuationSummary();
    const bear = {
      ...summary.cases[2]!,
      value_per_share: {},
      upside: {},
      errors: {},
      error: "Set these drivers: gross_margin",
    };
    getSummary.mockResolvedValue(
      okResult({ ...summary, cases: [summary.cases[0]!, summary.cases[1]!, bear] }) as never,
    );
    renderSummary();
    const table = await loaded();
    for (const method of ["DCF (FCFF)", "P/E"]) {
      const cells = within(row(table, method)).getAllByRole("cell");
      expect(cells[2]).toHaveTextContent("Set these drivers: gross_margin");
    }
  });

  it("lists each case's reason when no case can run (no method row)", async () => {
    const summary = valuationSummary();
    const failed = summary.cases.map((entry) => ({
      ...entry,
      value_per_share: {},
      upside: {},
      errors: {},
      error: "Set these drivers: gross_margin",
    }));
    getSummary.mockResolvedValue(okResult({ ...summary, methods: [], cases: failed }) as never);
    renderSummary();
    expect(await screen.findByText("Bull: Set these drivers: gross_margin")).toBeInTheDocument();
    expect(screen.getByText("Base: Set these drivers: gross_margin")).toBeInTheDocument();
    expect(screen.getByText("Bear: Set these drivers: gross_margin")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Valuation by case" })).not.toBeInTheDocument();
  });

  it("says when no price is stored and shows no upside", async () => {
    const summary = valuationSummary({ price: null, price_date: null });
    const cases = summary.cases.map((c) => ({
      ...c,
      upside: { dcf_fcff: null, "multiple:pe": null, "multiple:ev_ebitda": null },
    }));
    getSummary.mockResolvedValue(okResult({ ...summary, cases }) as never);
    renderSummary();
    const table = await loaded();
    expect(
      screen.getByText("No price stored. Refresh the company to load prices."),
    ).toBeInTheDocument();
    const cells = within(row(table, "DCF (FCFF)")).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("$131.83—");
  });

  it("shows the API's reason when the summary fails", async () => {
    getSummary.mockResolvedValue(errorResult(422, { detail: "No opening balance sheet" }) as never);
    renderSummary();
    expect(await screen.findByText("No opening balance sheet")).toBeInTheDocument();
  });

  it("shows a generic message on another failure, and Loading… first", async () => {
    getSummary.mockResolvedValue(errorResult(500) as never);
    renderSummary();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the valuation summary.")).toBeInTheDocument();
  });
});
