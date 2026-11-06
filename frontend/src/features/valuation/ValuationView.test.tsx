import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet,
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet,
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet,
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
  listScenariosApiV1CompaniesTickerScenariosGet,
} from "@/api/generated/sdk.gen";
import { errorResult, okResult } from "@/test/responses";
import { scenarios } from "@/test/scenarios";
import {
  sensitivityGrid,
  tornado,
  valuation,
  valuationInputs,
  valuationSummary,
} from "@/test/valuation";
import { renderWithClient, seen } from "@/test/valuationView";

import { ValuationView } from "./ValuationView";

vi.mock("@/api/generated/sdk.gen", () => ({
  listScenariosApiV1CompaniesTickerScenariosGet: vi.fn(),
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet: vi.fn(),
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet: vi.fn(),
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet: vi.fn(),
  listSetsApiV1CompaniesTickerCompsSetsGet: vi.fn(),
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet: vi.fn(),
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet: vi.fn(),
}));
vi.mock("echarts-for-react/esm/core", () => ({ default: vi.fn(() => null) }));

const list = vi.mocked(listScenariosApiV1CompaniesTickerScenariosGet);
const getSummary = vi.mocked(
  getValuationSummaryApiV1CompaniesTickerScenariosScenarioIdValuationGet,
);
const getValuation = vi.mocked(
  getValuationApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationGet,
);
const getInputs = vi.mocked(
  getValuationInputsApiV1CompaniesTickerScenariosScenarioIdCasesCaseValuationInputsGet,
);

const getTornado = vi.mocked(
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet,
);
const getGrid = vi.mocked(
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
);

beforeEach(() => {
  getTornado.mockResolvedValue(okResult(tornado()) as never);
  getGrid.mockResolvedValue(okResult(sensitivityGrid()) as never);
  list.mockResolvedValue(okResult(scenarios()) as never);
  getSummary.mockResolvedValue(okResult(valuationSummary()) as never);
  getValuation.mockResolvedValue(okResult(valuation()) as never);
  getInputs.mockResolvedValue(okResult(valuationInputs()) as never);
});
afterEach(() => vi.clearAllMocks());

const renderView = (path?: string) => renderWithClient(<ValuationView ticker="AAPL" />, path);
const lastPath = (mock: typeof getValuation | typeof getInputs) => mock.mock.calls.at(-1)?.[0].path;

describe("ValuationView", () => {
  it("groups the picked case's results, sensitivity and inputs under its heading", async () => {
    renderView("/c/AAPL/valuation?scenario=2&case=bear");
    const group = await screen.findByRole("region", { name: "Bear case" });
    expect(within(group).getByRole("heading", { level: 2, name: "Bear case" })).toBeInTheDocument();
    expect(group).toHaveTextContent("Cycle scenario");
    for (const name of ["Results", "Sensitivity", "Inputs"]) {
      expect(await within(group).findByRole("region", { name })).toBeInTheDocument();
    }
    // The summary compares the cases, so it sits above the group, not in it.
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(group).not.toContainElement(summary);
  });

  it("shows the picked case's sensitivity between its results and its inputs", async () => {
    renderView("/c/AAPL/valuation?scenario=2&case=bear");
    const results = await screen.findByRole("region", { name: "Results" });
    const sensitivity = await screen.findByRole("region", { name: "Sensitivity" });
    const inputs = await screen.findByRole("region", { name: "Inputs" });
    expect(
      results.compareDocumentPosition(sensitivity) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      sensitivity.compareDocumentPosition(inputs) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(getTornado.mock.calls.at(-1)?.[0].path).toEqual({
      ticker: "AAPL",
      scenario_id: 2,
      case: "bear",
    });
  });

  it("shows the summary, the picked case's results and its inputs, top to bottom", async () => {
    renderView();
    const summary = await screen.findByRole("region", { name: "Summary" });
    const results = await screen.findByRole("region", { name: "Results" });
    const inputs = await screen.findByRole("region", { name: "Inputs" });
    expect(
      summary.compareDocumentPosition(results) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(results.compareDocumentPosition(inputs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(lastPath(getValuation)).toEqual({ ticker: "AAPL", scenario_id: 1, case: "base" });
    expect(lastPath(getInputs)).toEqual({ ticker: "AAPL", scenario_id: 1, case: "base" });
    expect(screen.getByRole("radiogroup", { name: "Scale" })).toBeInTheDocument();
  });

  it("takes the scenario and case from the URL shared with Forecast", async () => {
    renderView("/c/AAPL/valuation?scenario=2&case=bear");
    await screen.findByRole("region", { name: "Results" });
    expect(lastPath(getValuation)).toEqual({ ticker: "AAPL", scenario_id: 2, case: "bear" });
    expect(getSummary).toHaveBeenCalledWith({ path: { ticker: "AAPL", scenario_id: 2 } });
    expect((screen.getByRole("combobox", { name: "Scenario" }) as HTMLSelectElement).value).toBe(
      "2",
    );
    expect(screen.getByRole("radio", { name: "Bear" })).toBeChecked();
  });

  it("writes a case switch to ?case and values that case", async () => {
    renderView();
    await screen.findByRole("region", { name: "Results" });
    await userEvent.click(screen.getByRole("radio", { name: "Bull" }));
    await waitFor(() =>
      expect(lastPath(getValuation)).toEqual({ ticker: "AAPL", scenario_id: 1, case: "bull" }),
    );
    expect(lastPath(getInputs)).toEqual({ ticker: "AAPL", scenario_id: 1, case: "bull" });
    expect(seen.search).toBe("?case=bull");
  });

  it("writes a scenario switch to ?scenario", async () => {
    renderView();
    await screen.findByRole("region", { name: "Results" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Scenario" }), "Cycle");
    await waitFor(() =>
      expect(getSummary).toHaveBeenLastCalledWith({ path: { ticker: "AAPL", scenario_id: 2 } }),
    );
    expect(seen.search).toBe("?scenario=2");
  });

  it("shows Loading… while the scenarios load", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says when there is no scenario", async () => {
    list.mockResolvedValue(okResult([]) as never);
    renderView();
    expect(await screen.findByText("No scenarios.")).toBeInTheDocument();
  });

  it("shows the reason when the scenarios cannot load", async () => {
    list.mockResolvedValue(errorResult(500, {}) as never);
    renderView();
    expect(await screen.findByText("Could not load the scenarios.")).toBeInTheDocument();
  });
});
