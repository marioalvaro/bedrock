import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet,
  listSetsApiV1CompaniesTickerCompsSetsGet,
  putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut,
  resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost,
} from "@/api/generated/sdk.gen";
import type { ValuationInputsOut } from "@/api/generated/types.gen";
import type { ScenarioCase } from "@/api/scenarios";
import { compsSets } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";
import { valuationInputs, withInputs } from "@/test/valuation";
import { renderWithClient } from "@/test/valuationView";

import { ValuationInputs } from "./ValuationInputs";

vi.mock("@/api/generated/sdk.gen", () => ({
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet: vi.fn(),
  putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut: vi.fn(),
  resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost:
    vi.fn(),
  listSetsApiV1CompaniesTickerCompsSetsGet: vi.fn(),
}));

const getInputs = vi.mocked(
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet,
);
const putInputs = vi.mocked(
  putValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsPut,
);
const resetInputs = vi.mocked(
  resetValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsResetPost,
);
const listSets = vi.mocked(listSetsApiV1CompaniesTickerCompsSetsGet);

beforeEach(() => {
  putInputs.mockResolvedValue(okResult(valuationInputs()) as never);
  resetInputs.mockResolvedValue(okResult(valuationInputs()) as never);
  listSets.mockResolvedValue(okResult(compsSets()) as never);
});
afterEach(() => vi.clearAllMocks());

async function renderInputs(
  view: ValuationInputsOut = valuationInputs(),
  scenarioCase: ScenarioCase = "base",
) {
  getInputs.mockResolvedValue(okResult({ ...view, case: scenarioCase }) as never);
  renderWithClient(<ValuationInputs ticker="AAPL" scenarioId={1} scenarioCase={scenarioCase} />);
  await screen.findByRole("region", { name: "Discount rate" });
}

const field = (name: string) => screen.getByRole("textbox", { name }) as HTMLInputElement;
const select = (name: string) => screen.getByRole("combobox", { name }) as HTMLSelectElement;
const sent = () => putInputs.mock.calls.map(([options]) => options.body?.rows);

async function retype(name: string, text: string) {
  await userEvent.clear(field(name));
  if (text) await userEvent.type(field(name), text);
  await userEvent.tab();
}

describe("fields", () => {
  it("asks for the case's inputs and groups them in panels", async () => {
    await renderInputs();
    expect(getInputs).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
    });
    for (const group of ["Discount rate", "Terminal value", "Multiples"]) {
      expect(screen.getByRole("region", { name: group })).toBeInTheDocument();
    }
    expect(field("Risk-free rate")).toHaveValue("4.0%");
    expect(field("Beta")).toHaveValue("1.00");
    expect(field("Cost of debt")).toHaveValue("3.37%");
  });

  it("styles each value by its source and names it in the title", async () => {
    await renderInputs(
      withInputs(valuationInputs(), {
        beta: { source: "own", own: "1.2", value: "1.2" },
        equity_risk_premium: { source: "base", value: "0.055" },
      }),
      "bull",
    );
    expect(field("Beta")).not.toHaveClass("text-muted-foreground");
    expect(field("Beta")).toHaveAttribute("title", "Set in this case");
    expect(field("Equity risk premium")).toHaveClass("text-muted-foreground", "italic");
    expect(field("Equity risk premium")).toHaveAttribute("title", "Inherited from Base");
    expect(field("Risk-free rate")).toHaveClass("text-muted-foreground");
    expect(field("Risk-free rate")).not.toHaveClass("italic");
    expect(field("Risk-free rate")).toHaveAttribute("title", "Default");
    expect(field("Tax rate")).toHaveAttribute("title", "From the forecast's FY2026 tax rate");
    expect(select("Discount method")).toHaveAttribute("title", "Default");
  });

  it("sends a percent typed in a field as a fraction, on blur", async () => {
    await renderInputs();
    await retype("Risk-free rate", "4.5");
    await waitFor(() => expect(putInputs).toHaveBeenCalledTimes(1));
    expect(putInputs).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
      body: { rows: [{ code: "risk_free_rate", value: "0.045" }] },
    });
  });

  it("sends a multiple as typed", async () => {
    await renderInputs();
    await retype("Beta", "1.2");
    await waitFor(() => expect(sent()).toEqual([[{ code: "beta", value: "1.2" }]]));
  });

  it("sends null for an emptied own value", async () => {
    await renderInputs(
      withInputs(valuationInputs(), { beta: { source: "own", own: "1.2", value: "1.2" } }),
    );
    await retype("Beta", "");
    await waitFor(() => expect(sent()).toEqual([[{ code: "beta", value: null }]]));
  });

  it("says Enter a number for text that is not one, and sends nothing", async () => {
    await renderInputs();
    await retype("Beta", "one");
    expect(await screen.findByText("Enter a number")).toBeInTheDocument();
    expect(putInputs).not.toHaveBeenCalled();
  });

  it("sends nothing when a field is left unchanged", async () => {
    await renderInputs();
    await userEvent.click(field("Cost of debt"));
    await userEvent.tab();
    await retype("Beta", "1");
    expect(putInputs).not.toHaveBeenCalled();
  });

  it("shows the API's 422 detail under the field", async () => {
    putInputs.mockResolvedValue(errorResult(422, { detail: "beta must be in [0, 5]" }) as never);
    await renderInputs();
    await retype("Beta", "7");
    expect(await screen.findByText("beta must be in [0, 5]")).toBeInTheDocument();
    expect(field("Beta")).toHaveAttribute("aria-invalid", "true");
  });

  it("sends a choice and the mid-year checkbox on change", async () => {
    await renderInputs();
    await userEvent.selectOptions(select("Terminal method"), "Exit multiple");
    await userEvent.click(screen.getByRole("checkbox", { name: "Mid-year discounting" }));
    await waitFor(() =>
      expect(sent()).toEqual([
        [{ code: "terminal_method", value: "exit_multiple" }],
        [{ code: "mid_year", value: "false" }],
      ]),
    );
    expect(
      within(select("Discount method"))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["WACC", "Direct rate"]);
  });

  it("shows the warnings above the panels", async () => {
    await renderInputs(valuationInputs({ warnings: ["Set these drivers: gross_margin"] }));
    expect(screen.getByText("Set these drivers: gross_margin")).toBeInTheDocument();
  });
});

describe("clearing and reset", () => {
  it("offers Back to the default on Base's own value, sending null", async () => {
    await renderInputs(
      withInputs(valuationInputs(), { beta: { source: "own", own: "1.2", value: "1.2" } }),
    );
    expect(
      screen.queryByRole("button", { name: "Risk-free rate: Back to the default" }),
    ).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Beta: Back to the default" }));
    await waitFor(() => expect(sent()).toEqual([[{ code: "beta", value: null }]]));
  });

  it("offers Use Base's value on Bull's own value", async () => {
    await renderInputs(
      withInputs(valuationInputs(), { terminal_method: { source: "own", own: "gordon" } }),
      "bull",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Terminal method: Use Base's value" }),
    );
    await waitFor(() => expect(sent()).toEqual([[{ code: "terminal_method", value: null }]]));
  });

  it.each([
    ["base", "Base", "Every valuation input of Base goes back to its default."],
    ["bull", "Bull", "Its own inputs are removed; it follows Base again."],
  ] as const)("resets %s's inputs after the dialog", async (scenarioCase, label, text) => {
    await renderInputs(valuationInputs(), scenarioCase);
    await userEvent.click(screen.getByRole("button", { name: `Reset ${label} inputs` }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(text);
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset" }));
    await waitFor(() =>
      expect(resetInputs).toHaveBeenCalledWith({
        path: { ticker: "AAPL", scenario_id: 1, case: scenarioCase },
      }),
    );
  });
});

describe("display rules", () => {
  it("WACC hides the direct rate and Gordon the exit multiple", async () => {
    await renderInputs();
    expect(screen.queryByRole("textbox", { name: "Discount rate" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Exit multiple (EV/EBITDA)" })).toBeNull();
    expect(field("Terminal growth")).toHaveValue("2.5%");
  });

  it("a direct rate hides the WACC inputs; an exit multiple hides the growth", async () => {
    await renderInputs(
      withInputs(valuationInputs(), {
        discount_method: { value: "direct", source: "own", own: "direct" },
        terminal_method: { value: "exit_multiple", source: "own", own: "exit_multiple" },
      }),
    );
    expect(field("Discount rate")).toHaveValue("9.0%");
    for (const name of [
      "Risk-free rate",
      "Equity risk premium",
      "Beta",
      "Cost of debt",
      "Tax rate",
      "Debt weight",
    ]) {
      expect(screen.queryByRole("textbox", { name })).toBeNull();
    }
    expect(field("Exit multiple (EV/EBITDA)")).toHaveValue("12.0×");
    expect(screen.queryByRole("textbox", { name: "Terminal growth" })).toBeNull();
  });

  it("lays out the targets with the columns their source uses", async () => {
    await renderInputs(withInputs(valuationInputs(), { ev_ebitda_source: { value: "manual" } }));
    const table = screen.getByRole("table", { name: "Multiple targets" });
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((h) => h.textContent),
    ).toEqual(["P/E", "EV/EBITDA", "P/FCF", "EV/Sales"]);
    expect(select("P/E source")).toHaveValue("own_history");
    expect(field("P/E percentile")).toHaveValue("50.0%");
    expect(screen.queryByRole("textbox", { name: "P/E multiple" })).toBeNull();
    expect(field("EV/EBITDA multiple")).toHaveValue("");
    expect(screen.queryByRole("textbox", { name: "EV/EBITDA percentile" })).toBeNull();
    expect(select("P/E year")).toHaveValue("1");
    expect(
      within(select("P/E year"))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["FY26E", "FY27E", "FY28E", "FY29E", "FY30E"]);
    expect(screen.queryByRole("combobox", { name: "P/FCF year" })).toBeNull();
  });

  it("sends a target's year and source", async () => {
    await renderInputs();
    await userEvent.selectOptions(select("P/E year"), "FY28E");
    await userEvent.selectOptions(select("P/FCF source"), "Manual");
    await waitFor(() =>
      expect(sent()).toEqual([
        [{ code: "pe_year", value: "3" }],
        [{ code: "p_fcf_source", value: "manual" }],
      ]),
    );
  });

  it("shows the comps-set select only when a target uses a peer median", async () => {
    await renderInputs();
    expect(screen.queryByRole("combobox", { name: "Comps set" })).toBeNull();
    expect(listSets).not.toHaveBeenCalled();
  });

  it("lists the company's comps sets and None, and sends the pick", async () => {
    await renderInputs(withInputs(valuationInputs(), { pe_source: { value: "peer_median" } }));
    const sets = await waitFor(() => {
      const found = select("Comps set");
      expect(within(found).getAllByRole("option")).toHaveLength(3);
      return found;
    });
    expect(
      within(sets)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["None", "Hardware & industrials", "Software"]);
    await userEvent.selectOptions(sets, "Software");
    await waitFor(() => expect(sent()).toEqual([[{ code: "comps_set_id", value: "2" }]]));
  });
});

describe("states", () => {
  it("shows the API's 422 detail when the inputs cannot load", async () => {
    getInputs.mockResolvedValue(errorResult(422, { detail: "Scenario has no cases" }) as never);
    renderWithClient(<ValuationInputs ticker="AAPL" scenarioId={1} scenarioCase="base" />);
    expect(await screen.findByText("Scenario has no cases")).toBeInTheDocument();
  });

  it("shows Loading… then a failure's message", async () => {
    getInputs.mockResolvedValue(errorResult(500) as never);
    renderWithClient(<ValuationInputs ticker="AAPL" scenarioId={1} scenarioCase="base" />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the valuation inputs.")).toBeInTheDocument();
  });
});
