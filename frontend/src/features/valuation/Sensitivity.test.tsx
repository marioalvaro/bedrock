import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet,
} from "@/api/generated/sdk.gen";
import { errorResult, okResult } from "@/test/responses";
import { sensitivityGrid, tornado } from "@/test/valuation";
import { renderWithClient } from "@/test/valuationView";

import { Sensitivity } from "./Sensitivity";

vi.mock("@/api/generated/sdk.gen", () => ({
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet: vi.fn(),
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet: vi.fn(),
}));
vi.mock("echarts-for-react/esm/core", () => ({ default: vi.fn(() => null) }));

const getTornado = vi.mocked(
  getTornadoApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityTornadoGet,
);
const getGrid = vi.mocked(
  getSensitivityGridApiV1CompaniesTickerScenariosScenarioIdCasesCaseSensitivityGridGet,
);

const renderSensitivity = () =>
  renderWithClient(<Sensitivity ticker="AAPL" scenarioId={1} scenarioCase="base" />);

beforeEach(() => {
  getTornado.mockResolvedValue(okResult(tornado()) as never);
  getGrid.mockResolvedValue(okResult(sensitivityGrid()) as never);
});
afterEach(() => vi.clearAllMocks());

describe("Sensitivity", () => {
  it("sits in its own card", async () => {
    renderSensitivity();
    await screen.findByRole("table", { name: /DCF value per share/ });
    expect(screen.getByRole("region", { name: "Sensitivity" })).toHaveClass("rounded-lg", "border");
  });

  it("shows the tornado, then the grid over the tornado's inputs", async () => {
    renderSensitivity();
    expect(screen.getByText("Loading the sensitivity…")).toBeInTheDocument();
    expect(
      await screen.findByRole("img", { name: "Tornado: change in DCF value per share by input" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: /DCF value per share/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sensitivity" })).toBeInTheDocument();
    expect(getTornado).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 1, case: "base" },
    });
  });

  it("shows the API's 422 detail and no grid", async () => {
    getTornado.mockResolvedValue(
      errorResult(422, { detail: "Set these drivers: gross_margin" }) as never,
    );
    renderSensitivity();
    expect(await screen.findByText("Set these drivers: gross_margin")).toBeInTheDocument();
    expect(getGrid).not.toHaveBeenCalled();
  });

  it("falls back to a plain message for another failure", async () => {
    getTornado.mockResolvedValue(errorResult(500) as never);
    renderSensitivity();
    expect(await screen.findByText("Could not load the sensitivity.")).toBeInTheDocument();
  });
});
