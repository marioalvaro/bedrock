import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSeriesApiV1CompaniesTickerSegmentSeriesPost,
  deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete,
  getSegmentsApiV1CompaniesTickerSegmentsGet,
  importSegmentsApiV1CompaniesTickerSegmentsImportPost,
  setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut,
  updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { segments } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";

import { SegmentsView } from "./SegmentsView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getSegmentsApiV1CompaniesTickerSegmentsGet: vi.fn(),
  createSeriesApiV1CompaniesTickerSegmentSeriesPost: vi.fn(),
  updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut: vi.fn(),
  deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete: vi.fn(),
  setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut: vi.fn(),
  importSegmentsApiV1CompaniesTickerSegmentsImportPost: vi.fn(),
}));

const getSegments = vi.mocked(getSegmentsApiV1CompaniesTickerSegmentsGet);
const createSeries = vi.mocked(createSeriesApiV1CompaniesTickerSegmentSeriesPost);
const updateSeries = vi.mocked(updateSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdPut);
const deleteSeries = vi.mocked(deleteSeriesApiV1CompaniesTickerSegmentSeriesSeriesIdDelete);
const setValues = vi.mocked(setValuesApiV1CompaniesTickerSegmentSeriesSeriesIdValuesPut);
const importSegments = vi.mocked(importSegmentsApiV1CompaniesTickerSegmentsImportPost);

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <SegmentsView ticker="AAPL" />
    </QueryClientProvider>,
  );
}

async function renderLoaded() {
  renderView();
  await screen.findByText("Americas");
}

const cell = (row: string, period: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${period}"]`) as HTMLElement;

// Opens the cell editor, replaces its text and commits with Enter.
async function edit(row: string, period: string, text: string) {
  await userEvent.dblClick(cell(row, period));
  const input = (await waitFor(() => {
    const found = cell(row, period).querySelector("input");
    expect(found).not.toBeNull();
    return found;
  })) as HTMLInputElement;
  await userEvent.clear(input);
  if (text) await userEvent.type(input, text);
  await userEvent.keyboard("{Enter}");
}

beforeEach(() => {
  setScale("M");
  getSegments.mockResolvedValue(okResult(segments()) as never);
  createSeries.mockResolvedValue(okResult({ id: 9 }, 201) as never);
  updateSeries.mockResolvedValue(okResult({ id: 1 }) as never);
  deleteSeries.mockResolvedValue(okResult(null, 204) as never);
  setValues.mockResolvedValue(okResult({ id: 1 }) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("SegmentsView grid", () => {
  it("renders a section per block with its series and formatted values", async () => {
    await renderLoaded();
    expect(screen.getByRole("heading", { name: "Geographic segments · Revenue" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "KPIs" })).toBeVisible();
    expect(screen.getByText("Europe")).toBeVisible();
    expect(cell("series:1", "FY2024")).toHaveTextContent("167,045");
    expect(cell("series:2", "FY2023")).toHaveTextContent("94,294");
    expect(cell("series:1", "FY2023")).toHaveTextContent("—");
    expect(cell("series:3", "FY2024")).toHaveTextContent("46.0%");
  });

  it("ends a business or geo block with an Unallocated row", async () => {
    await renderLoaded();
    expect(cell("unallocated:geo:revenue", "FY2024")).toHaveTextContent("122,662");
    expect(cell("unallocated:geo:revenue", "FY2023")).toHaveTextContent("—");
    expect(screen.getAllByText("Unallocated")).toHaveLength(1);
  });

  it("shows a KPI's name with its unit", async () => {
    await renderLoaded();
    expect(screen.getByText("Gross margin target")).toBeVisible();
    expect(screen.getByText("· %")).toBeVisible();
  });

  it("follows the page scale", async () => {
    setScale("B");
    await renderLoaded();
    expect(cell("series:1", "FY2024")).toHaveTextContent("167.0");
  });

  it("asks for the quarterly grid", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("radio", { name: "Quarterly" }));
    await waitFor(() =>
      expect(getSegments).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { freq: "quarterly" },
      }),
    );
  });

  it("shows loading, error and empty states", async () => {
    getSegments.mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(screen.getByText("Loading…")).toBeVisible();
  });

  it("shows an error when the grid cannot load", async () => {
    getSegments.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("Could not load the segments.")).toBeVisible();
  });

  it("shows an empty state with Add series and Import", async () => {
    getSegments.mockResolvedValue(okResult(segments({ blocks: [] })) as never);
    renderView();
    expect(await screen.findByText(/No segments or KPIs yet/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Add series" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Import" })).toBeVisible();
  });
});

describe("SegmentsView cell edits", () => {
  it("sends one PUT with the scaled value", async () => {
    await renderLoaded();
    await edit("series:1", "FY2023", "150,000");
    await waitFor(() => expect(setValues).toHaveBeenCalledTimes(1));
    expect(setValues).toHaveBeenCalledWith({
      path: { ticker: "AAPL", series_id: 1 },
      body: { values: [{ fiscal_year: 2023, fiscal_period: "FY", value: "150000000000" }] },
    });
  });

  it("starts the editor from the value in the page scale", async () => {
    await renderLoaded();
    await userEvent.dblClick(cell("series:1", "FY2024"));
    await waitFor(() =>
      expect(cell("series:1", "FY2024").querySelector("input")).toHaveValue("167045"),
    );
  });

  it("sends null for an emptied cell", async () => {
    await renderLoaded();
    await edit("series:1", "FY2024", "");
    await waitFor(() => expect(setValues).toHaveBeenCalledTimes(1));
    expect(setValues).toHaveBeenCalledWith({
      path: { ticker: "AAPL", series_id: 1 },
      body: { values: [{ fiscal_year: 2024, fiscal_period: "FY", value: null }] },
    });
  });

  it("sends a typed percent as a fraction", async () => {
    await renderLoaded();
    await edit("series:3", "FY2023", "45.5%");
    await waitFor(() => expect(setValues).toHaveBeenCalledTimes(1));
    expect(setValues).toHaveBeenCalledWith({
      path: { ticker: "AAPL", series_id: 3 },
      body: { values: [{ fiscal_year: 2023, fiscal_period: "FY", value: "0.455" }] },
    });
  });

  it("refuses bad text with 'Enter a number' and sends nothing", async () => {
    await renderLoaded();
    await edit("series:1", "FY2023", "abc");
    expect(await screen.findByText("Enter a number")).toBeVisible();
    expect(setValues).not.toHaveBeenCalled();
    expect(cell("series:1", "FY2023")).toHaveTextContent("—");
  });

  it("sends nothing when the text is unchanged", async () => {
    await renderLoaded();
    await edit("series:1", "FY2024", "167045");
    expect(setValues).not.toHaveBeenCalled();
  });

  it("shows the API's reason when the save fails", async () => {
    setValues.mockResolvedValue(errorResult(422, { detail: "value out of range" }) as never);
    await renderLoaded();
    await edit("series:1", "FY2023", "5");
    expect(await screen.findByText("value out of range")).toBeVisible();
  });

  it("does not edit the Unallocated row", async () => {
    await renderLoaded();
    await userEvent.dblClick(cell("unallocated:geo:revenue", "FY2024"));
    expect(cell("unallocated:geo:revenue", "FY2024").querySelector("input")).toBeNull();
  });
});

describe("SegmentsView series", () => {
  it("adds a series to a block with the block's dimension and metric", async () => {
    await renderLoaded();
    await userEvent.click(
      screen.getByRole("button", { name: "Add series to Geographic segments · Revenue" }),
    );
    await userEvent.type(screen.getByLabelText("Name"), "Japan");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(createSeries).toHaveBeenCalledTimes(1));
    expect(createSeries).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { dimension: "geo", name: "Japan", metric: "revenue", unit: "USD" },
    });
  });

  it("adds a KPI with a code and a unit", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Add series" }));
    await userEvent.selectOptions(screen.getByLabelText("Dimension"), "kpi");
    await userEvent.type(screen.getByLabelText("Name"), "Same-store sales");
    await userEvent.type(screen.getByLabelText("Code"), "sss");
    await userEvent.selectOptions(screen.getByLabelText("Unit"), "pct");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(createSeries).toHaveBeenCalledTimes(1));
    expect(createSeries).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { dimension: "kpi", name: "Same-store sales", metric: "sss", unit: "pct" },
    });
  });

  it("refuses a blank name without a request", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Add series" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Enter a name")).toBeVisible();
    expect(createSeries).not.toHaveBeenCalled();
  });

  it("shows the API's reason when adding fails", async () => {
    createSeries.mockResolvedValue(errorResult(422, { detail: "KPI code already used" }) as never);
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Add series" }));
    await userEvent.type(screen.getByLabelText("Name"), "Japan");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("KPI code already used")).toBeVisible();
  });

  it("renames a series, keeping its display order", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Rename Americas" }));
    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Americas");
    await userEvent.clear(name);
    await userEvent.type(name, "North America");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateSeries).toHaveBeenCalledTimes(1));
    expect(updateSeries).toHaveBeenCalledWith({
      path: { ticker: "AAPL", series_id: 1 },
      body: { name: "North America", display_order: 1 },
    });
  });

  it("deletes a series only after confirmation", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Delete Europe" }));
    expect(deleteSeries).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteSeries).toHaveBeenCalledTimes(1));
    expect(deleteSeries).toHaveBeenCalledWith({ path: { ticker: "AAPL", series_id: 2 } });
  });

  it("keeps the series when the delete is cancelled", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Delete Europe" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(deleteSeries).not.toHaveBeenCalled();
  });
});

const CSV = "name,metric,unit,FY2024\nAmericas,revenue,USD,167045\n";

describe("SegmentsView import", () => {
  async function openImport() {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    return screen.findByRole("dialog");
  }

  it("explains the header and defaults the scale to the page scale", async () => {
    const dialog = await openImport();
    expect(within(dialog).getByText(/FY2024/)).toBeVisible();
    expect(within(dialog).getByLabelText("Scale")).toHaveValue("M");
  });

  it("sends the dimension, scale and text, and reports the counts", async () => {
    importSegments.mockResolvedValue(
      okResult({ series_created: 5, values_created: 5, values_updated: 0 }) as never,
    );
    const dialog = await openImport();
    await userEvent.selectOptions(within(dialog).getByLabelText("Dimension"), "geo");
    await userEvent.click(within(dialog).getByLabelText("CSV or TSV"));
    await userEvent.paste(CSV);
    await userEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    await waitFor(() => expect(importSegments).toHaveBeenCalledTimes(1));
    expect(importSegments).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: { dimension: "geo", scale: "M", text: CSV },
    });
    expect(
      await within(dialog).findByText("5 series created, 5 values created, 0 values updated."),
    ).toBeVisible();
  });

  it("reads a chosen file into the text box", async () => {
    const dialog = await openImport();
    const file = new File([CSV], "geo.csv", { type: "text/csv" });
    await userEvent.upload(within(dialog).getByLabelText("File"), file);
    await waitFor(() => expect(within(dialog).getByLabelText("CSV or TSV")).toHaveValue(CSV));
  });

  it("lists every error with its row and column header", async () => {
    importSegments.mockResolvedValue(
      errorResult(422, {
        detail: "Import failed",
        errors: [
          { row: 3, column: 4, message: "'abc' is not a number" },
          { row: 5, column: null, message: "duplicate series" },
          { row: 2, column: 9, message: "a value with no period column" },
        ],
      }) as never,
    );
    const dialog = await openImport();
    await userEvent.click(within(dialog).getByLabelText("CSV or TSV"));
    await userEvent.paste(CSV);
    await userEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    const items = await within(dialog).findAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "row 3, FY2024: 'abc' is not a number",
      "row 5: duplicate series",
      "row 2, column 9: a value with no period column",
    ]);
  });

  it("refuses an empty paste without a request", async () => {
    const dialog = await openImport();
    await userEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    expect(await within(dialog).findByText("Paste or choose a CSV or TSV first")).toBeVisible();
    expect(importSegments).not.toHaveBeenCalled();
  });

  it("shows the API's reason for a failure without an issue list", async () => {
    importSegments.mockResolvedValue(errorResult(404, { detail: "Unknown ticker" }) as never);
    const dialog = await openImport();
    await userEvent.click(within(dialog).getByLabelText("CSV or TSV"));
    await userEvent.paste(CSV);
    await userEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    expect(await within(dialog).findByText("Unknown ticker")).toBeVisible();
  });
});
