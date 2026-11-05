import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet,
  importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { errorResult, okResult } from "@/test/responses";
import { driverGrid, driverImport } from "@/test/scenarios";

import { DriverImportSheet } from "./DriverImportSheet";

vi.mock("@/api/generated/sdk.gen", () => ({
  getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet: vi.fn(),
  importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost: vi.fn(),
}));

const getDrivers = vi.mocked(getDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversGet);
const importDrivers = vi.mocked(
  importDriversApiV1CompaniesTickerScenariosScenarioIdCasesCaseDriversImportPost,
);

const file = new File(["driver_code,label,unit,kind,FY2026\n"], "AAPL-Bull-drivers.xlsx");

function renderSheet() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <DriverImportSheet
        ticker="AAPL"
        scenarioId={2}
        scenarioCase="bull"
        open
        scale="M"
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onClose };
}

async function preview() {
  await userEvent.upload(screen.getByLabelText("Driver file"), file);
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
}

beforeEach(() => {
  getDrivers.mockResolvedValue(okResult(driverGrid()) as never);
});

afterEach(() => vi.clearAllMocks());

describe("DriverImportSheet", () => {
  it("accepts CSV and Excel files", () => {
    renderSheet();
    expect(screen.getByLabelText("Driver file")).toHaveAttribute("accept", ".csv,.xlsx");
  });

  it("labels the changes from the case's own driver grid", () => {
    renderSheet();
    expect(getDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      query: { freq: "annual" },
    });
  });

  it("asks for a file before a preview", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a file first");
    expect(importDrivers).not.toHaveBeenCalled();
  });

  it("previews the changes with labels, years and values by unit", async () => {
    importDrivers.mockResolvedValue(okResult(driverImport()) as never);
    renderSheet();
    await preview();
    expect(importDrivers).toHaveBeenCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      body: { file, dry_run: true },
    });
    const list = await screen.findByRole("list", { name: "Changes" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["Revenue growth · FY27: 5.0% → 8.0%", "Gross margin · FY26: 47.0% → cleared"]);
    expect(screen.getByRole("button", { name: "Apply 2 changes" })).toBeEnabled();
  });

  it("names a quarter's change by the quarter and keeps it apart from its year's", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    importDrivers.mockResolvedValue(
      okResult(
        driverImport({
          changes: [
            {
              driver_code: "gross_margin",
              fiscal_year: 2026,
              fiscal_period: "FY",
              old: "0.47",
              new: "0.48",
              old_kind: "value",
              new_kind: "value",
            },
            {
              driver_code: "gross_margin",
              fiscal_year: 2026,
              fiscal_period: "Q1",
              old: "0.44",
              new: "0.46",
              old_kind: "value",
              new_kind: "value",
            },
          ],
        }),
      ) as never,
    );
    renderSheet();
    await preview();
    const list = await screen.findByRole("list", { name: "Changes" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["Gross margin · FY26: 47.0% → 48.0%", "Gross margin · Q1 FY26: 44.0% → 46.0%"]);
    expect(errors).not.toHaveBeenCalled(); // no duplicate React key
    errors.mockRestore();
  });

  it("shows offsets as offsets and a new value from nothing", async () => {
    importDrivers.mockResolvedValue(
      okResult(
        driverImport({
          changes: [
            {
              driver_code: "revenue_growth",
              fiscal_year: 2026,
              fiscal_period: "FY",
              old: "0.03",
              new: "0.04",
              old_kind: "offset",
              new_kind: "offset",
            },
            {
              driver_code: "buybacks",
              fiscal_year: 2027,
              fiscal_period: "FY",
              old: null,
              new: "90000000000",
              old_kind: null,
              new_kind: "value",
            },
          ],
        }),
      ) as never,
    );
    renderSheet();
    await preview();
    const items = within(await screen.findByRole("list", { name: "Changes" })).getAllByRole(
      "listitem",
    );
    expect(items.map((item) => item.textContent)).toEqual([
      "Revenue growth · FY26: +3.0 pts → +4.0 pts",
      "Buybacks · FY27: — → 90,000",
    ]);
    expect(screen.getByRole("button", { name: "Apply 2 changes" })).toBeInTheDocument();
  });

  it("says 'Nothing to change' for a file equal to the case", async () => {
    importDrivers.mockResolvedValue(okResult(driverImport({ changes: [] })) as never);
    renderSheet();
    await preview();
    expect(await screen.findByText("Nothing to change")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Apply/ })).not.toBeInTheDocument();
  });

  it("lists every error of a refused file, located by row and column", async () => {
    importDrivers.mockResolvedValue(
      errorResult(422, {
        detail: "The file has errors",
        errors: [
          { row: 3, column: "F", message: "'abc' is not a number" },
          { row: 4, column: null, message: "Unknown driver code 'foo'" },
          { row: null, column: null, message: "The file is empty" },
        ],
      }) as never,
    );
    renderSheet();
    await preview();
    const errors = await screen.findByRole("list", { name: "Errors" });
    expect(
      within(errors)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "row 3, column F: 'abc' is not a number",
      "row 4: Unknown driver code 'foo'",
      "The file is empty",
    ]);
    expect(screen.queryByRole("button", { name: /^Apply/ })).not.toBeInTheDocument();
  });

  it("lists the year-mode errors as the API words them", async () => {
    importDrivers.mockResolvedValue(
      errorResult(422, {
        detail: "The file has errors",
        errors: [
          { row: 2, column: "E", message: "FY2027 is set by quarter" },
          { row: 3, column: "G", message: "FY2026 is set annually; switch it to by quarter first" },
          {
            row: 4,
            column: null,
            message: "Q4 FY2027 is missing for gross_margin (FY2027 is set by quarter)",
          },
        ],
      }) as never,
    );
    renderSheet();
    await preview();
    const errors = await screen.findByRole("list", { name: "Errors" });
    expect(
      within(errors)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "row 2, column E: FY2027 is set by quarter",
      "row 3, column G: FY2026 is set annually; switch it to by quarter first",
      "row 4: Q4 FY2027 is missing for gross_margin (FY2027 is set by quarter)",
    ]);
  });

  it("shows a plain 422 reason", async () => {
    importDrivers.mockResolvedValue(
      errorResult(422, { detail: "The file is larger than 1 MB" }) as never,
    );
    renderSheet();
    await preview();
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is larger than 1 MB");
  });

  it("applies the changes with the same file", async () => {
    importDrivers.mockResolvedValueOnce(okResult(driverImport()) as never);
    importDrivers.mockResolvedValueOnce(
      okResult(driverImport({ dry_run: false, grid: driverGrid() })) as never,
    );
    renderSheet();
    await preview();
    await userEvent.click(await screen.findByRole("button", { name: "Apply 2 changes" }));
    expect(importDrivers).toHaveBeenLastCalledWith({
      path: { ticker: "AAPL", scenario_id: 2, case: "bull" },
      body: { file, dry_run: false },
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Applied 2 changes.");
    expect(screen.queryByRole("list", { name: "Changes" })).not.toBeInTheDocument();
  });

  it("drops the preview when another file is chosen", async () => {
    importDrivers.mockResolvedValue(okResult(driverImport()) as never);
    renderSheet();
    await preview();
    await screen.findByRole("list", { name: "Changes" });
    await userEvent.upload(screen.getByLabelText("Driver file"), new File(["x"], "other.csv"));
    await waitFor(() =>
      expect(screen.queryByRole("list", { name: "Changes" })).not.toBeInTheDocument(),
    );
  });
});
