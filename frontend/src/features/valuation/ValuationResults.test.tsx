import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet } from "@/api/generated/sdk.gen";
import { setScale } from "@/lib/scale";
import { errorResult, okResult } from "@/test/responses";
import { dcf, evEbitdaError, peResult, result, valuation } from "@/test/valuation";
import { renderWithClient } from "@/test/valuationView";

import { ValuationResults } from "./ValuationResults";

vi.mock("@/api/generated/sdk.gen", () => ({
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet: vi.fn(),
}));

const getValuation = vi.mocked(
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet,
);

beforeEach(() => setScale("M"));
afterEach(() => vi.clearAllMocks());

const renderResults = () =>
  renderWithClient(<ValuationResults ticker="AAPL" scenarioId={1} scenarioCase="bull" />);

const serve = (body = valuation()) => getValuation.mockResolvedValue(okResult(body) as never);

// The cells of a table row named by its header cell.
const cells = (table: HTMLElement, name: string) =>
  within(within(table).getByRole("rowheader", { name }).closest("tr") as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);

describe("DCF", () => {
  it("asks for the picked case and shows the WACC line and mid-year discounting", async () => {
    serve();
    renderResults();
    expect(
      await screen.findByText(
        "WACC 8.9% · cost of equity 9.0% (4.0% + 1.00 × 5.0%) · after-tax cost of debt 2.8% · debt 1.7% / equity 98.3%",
      ),
    ).toBeInTheDocument();
    expect(getValuation).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "bull" },
    });
    expect(screen.getByText("Mid-year discounting")).toBeInTheDocument();
  });

  it("shows a direct rate", async () => {
    const direct = dcf({
      mid_year: false,
      discount: { ...dcf().discount, method: "direct", rate: "0.09" },
    });
    serve(valuation({ results: [result({ dcf: direct })] }));
    renderResults();
    expect(await screen.findByText("Discount rate 9.0% (set directly)")).toBeInTheDocument();
    expect(screen.getByText("End-of-year discounting")).toBeInTheDocument();
  });

  it("lays the cash flows out by period, the stub as the rest of its year", async () => {
    serve();
    renderResults();
    const table = await screen.findByRole("table", { name: "Cash flows" });
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual([
      "USD millions",
      "FY26E (rest of year)",
      "FY27E",
    ]);
    expect(headers[1]).toHaveClass("cell-forecast");
    expect(cells(table, "NOPAT")).toEqual(["26,578", "121,586"]);
    expect(cells(table, "D&A")).toEqual(["3,042", "13,918"]);
    expect(cells(table, "Change in working capital")).toEqual(["5,831", "525"]);
    expect(cells(table, "Capex")).toEqual(["(2,899)", "(13,261)"]);
    expect(cells(table, "FCFF")).toEqual(["32,552", "122,768"]);
    expect(within(table).getByRole("rowheader", { name: "FCFF" }).closest("tr")).toHaveClass(
      "font-semibold",
    );
    expect(cells(table, "Discount years")).toEqual(["0.00", "0.49"]);
    expect(cells(table, "Discount factor")).toEqual(["1.0000", "0.9594"]);
    expect(cells(table, "Present value")).toEqual(["32,552", "117,788"]);
  });

  it("follows the page scale", async () => {
    setScale("B");
    serve();
    renderResults();
    const table = await screen.findByRole("table", { name: "Cash flows" });
    expect(cells(table, "FCFF")).toEqual(["32.6", "122.8"]);
  });

  it("shows the terminal value with its implied exit multiple and its share of EV", async () => {
    serve();
    renderResults();
    const terminal = await screen.findByRole("region", { name: "Terminal value" });
    expect(terminal).toHaveTextContent("Gordon growth 2.5%");
    expect(terminal).toHaveTextContent("Terminal value 2,082,191");
    expect(terminal).toHaveTextContent("Present value 1,484,242");
    expect(terminal).toHaveTextContent("Implied exit multiple 12.1× EV/EBITDA");
    expect(terminal).toHaveTextContent("Terminal value is 76% of EV");
  });

  it("bridges EV to the value per share, the signs as labels", async () => {
    serve();
    renderResults();
    const table = await screen.findByRole("table", { name: "Bridge" });
    const rows = within(table)
      .getAllByRole("row")
      .map((row) => row.textContent);
    expect(rows).toEqual([
      "Enterprise value1,947,893",
      "− Debt84,344",
      "+ Cash39,544",
      "+ Short-term investments22,855",
      "− Minority interest0",
      "− Temporary equity0",
      "= Equity value1,925,948",
      "÷ Shares14,609",
      "= Value per share$131.83",
      "Upside vs price-60.8%",
    ]);
  });

  it("shows a DCF error in place of the DCF", async () => {
    serve(
      valuation({
        results: [
          result({
            dcf: null,
            enterprise_value: null,
            equity_value: null,
            value_per_share: null,
            upside: null,
            error: "The discount rate must exceed the terminal growth",
          }),
        ],
      }),
    );
    renderResults();
    expect(
      await screen.findByText("The discount rate must exceed the terminal growth"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Bridge" })).not.toBeInTheDocument();
  });
});

describe("multiples", () => {
  it("lists a row per target with its year, metric, multiple, source, value and upside", async () => {
    serve();
    renderResults();
    const table = await screen.findByRole("table", { name: "Multiple targets" });
    expect(cells(table, "P/E")).toEqual(["FY26E", "127,703", "25.0×Manual", "$218.53", "-35.1%"]);
    expect(within(table).getByText("127,703")).toHaveAttribute("title", "Net income to common");
  });

  it("names the own-history and peer-median sources", async () => {
    const own = peResult({
      multiple: { ...peResult().multiple!, source: "own_history", percentile: "0.5", n: 9 },
    });
    const peer = peResult({
      key: "multiple:ev_ebitda",
      label: "EV/EBITDA",
      multiple: {
        ...peResult().multiple!,
        ratio_code: "ev_ebitda",
        source: "peer_median",
        n: 4,
        comps_set: { id: 3, name: "Megacaps" },
      },
    });
    serve(valuation({ results: [result(), own, peer] }));
    renderResults();
    const table = await screen.findByRole("table", { name: "Multiple targets" });
    expect(within(table).getByText("Own history, 50th percentile of 9 years")).toBeInTheDocument();
    expect(within(table).getByText("Peer median of Megacaps (4 peers)")).toBeInTheDocument();
  });

  it("shows an error row across the columns, and the trailing-multiple footnote", async () => {
    serve();
    renderResults();
    const table = await screen.findByRole("table", { name: "Multiple targets" });
    const [error] = within(
      within(table).getByRole("rowheader", { name: "EV/EBITDA" }).closest("tr") as HTMLElement,
    ).getAllByRole("cell");
    expect(error).toHaveTextContent("EV/EBITDA: fewer than 3 years of history");
    expect(error).toHaveAttribute("colspan", "5");
    expect(
      screen.getByText(
        "Own-history and peer multiples are trailing multiples applied to a forecast year.",
      ),
    ).toBeInTheDocument();
  });

  it("says when no target is on", async () => {
    serve(valuation({ results: [result()] }));
    renderResults();
    expect(await screen.findByText("No multiple target is on.")).toBeInTheDocument();
  });
});

describe("notes and states", () => {
  it("marks a result's caveat with † and lists its text", async () => {
    const caveat = "Consolidated debt includes John Deere Financial's.";
    serve(valuation({ results: [result({ caveat }), peResult(), evEbitdaError()] }));
    renderResults();
    expect(await screen.findByText(`† ${caveat}`)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "DCF (FCFF) †" })).toBeInTheDocument();
  });

  it("lists the forecast's warnings", async () => {
    serve(valuation({ warnings: ["Tax rate held at the FY2025 rate"] }));
    renderResults();
    expect(await screen.findByText("Tax rate held at the FY2025 rate")).toBeInTheDocument();
  });

  it("offers Open Scenarios when drivers must be set", async () => {
    getValuation.mockResolvedValue(
      errorResult(422, { detail: "Set these drivers: gross_margin" }) as never,
    );
    renderResults();
    expect(await screen.findByText("Set these drivers: gross_margin")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Scenarios" })).toHaveAttribute(
      "href",
      "/c/AAPL/scenarios?scenario=1&case=bull",
    );
  });

  it("shows another 422 without the link", async () => {
    getValuation.mockResolvedValue(
      errorResult(422, { detail: "No opening balance sheet" }) as never,
    );
    renderResults();
    expect(await screen.findByText("No opening balance sheet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open Scenarios" })).not.toBeInTheDocument();
  });

  it("shows the generic message for a 422 without a detail", async () => {
    getValuation.mockResolvedValue(errorResult(422, {}) as never);
    renderResults();
    expect(await screen.findByText("Could not load the valuation.")).toBeInTheDocument();
  });

  it("says so when the DCF has neither details nor an error", async () => {
    serve(valuation({ results: [result({ dcf: null })] }));
    renderResults();
    expect(await screen.findByText("No DCF result.")).toBeInTheDocument();
  });

  it("shows Loading… then a generic message on another failure", async () => {
    getValuation.mockResolvedValue(errorResult(500) as never);
    renderResults();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the valuation.")).toBeInTheDocument();
  });
});
