import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createAdjustmentApiV1CompaniesTickerAdjustmentsPost,
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete,
  getCellApiV1CompaniesTickerStatementsCellGet,
  updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale, type Scale } from "@/lib/scale";
import { adjustment, cellAdjustment } from "@/test/adjustments";
import { errorResult, okResult } from "@/test/responses";

import { CellDetailSheet, type CellTarget } from "./CellDetailSheet";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCellApiV1CompaniesTickerStatementsCellGet: vi.fn(),
  createAdjustmentApiV1CompaniesTickerAdjustmentsPost: vi.fn(),
  updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut: vi.fn(),
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete: vi.fn(),
}));

const cell = {
  code: "sga",
  label: "SG&A",
  fiscal_year: 2024,
  fiscal_period: "FY",
  value: "-60000000",
  provenance: "reported",
  source: null,
  filing: null,
  derivation: null,
  vintages: [],
  adjustments: [],
  normalized_value: null,
};

const target: CellTarget = {
  code: "sga",
  label: "SG&A",
  unit: "USD",
  adjustable: true,
  fiscalYear: 2024,
  fiscalPeriod: "FY",
};

function mockCell(overrides: Record<string, unknown> = {}) {
  vi.mocked(getCellApiV1CompaniesTickerStatementsCellGet).mockResolvedValue(
    okResult({ ...cell, ...overrides }) as never,
  );
}

function renderSheet(t: Partial<CellTarget> = {}, scale: Scale = "M") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <CellDetailSheet
        ticker="AAPL"
        cik="0000320193"
        target={{ ...target, ...t }}
        scale={scale}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

const create = vi.mocked(createAdjustmentApiV1CompaniesTickerAdjustmentsPost);
const update = vi.mocked(updateAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdPut);
const remove = vi.mocked(deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete);

beforeEach(() => {
  setScale("M");
  mockCell();
  create.mockResolvedValue(okResult(adjustment({ id: 9 }), 201) as never);
  update.mockResolvedValue(okResult(adjustment()) as never);
  remove.mockResolvedValue(okResult(null, 204) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

async function openAdd() {
  await userEvent.click(await screen.findByRole("button", { name: "Add adjustment" }));
}

describe("CellDetailSheet adjustments", () => {
  it("hides the form on a non-adjustable row", async () => {
    renderSheet({ adjustable: false });
    await screen.findByText(/Adjustments: none/);
    expect(screen.queryByRole("button", { name: "Add adjustment" })).not.toBeInTheDocument();
  });

  it("hides the form on a TTM column even on an adjustable row", async () => {
    renderSheet({ fiscalPeriod: "TTM" });
    await screen.findByText(/Adjustments: none/);
    expect(screen.queryByRole("button", { name: "Add adjustment" })).not.toBeInTheDocument();
  });

  it("shows the form on a quarter row", async () => {
    renderSheet({ fiscalPeriod: "Q2" });
    await openAdd();
    expect(screen.getByLabelText("Reason")).toBeInTheDocument();
  });

  it("shows Adjustments: none for an empty list", async () => {
    renderSheet();
    expect(await screen.findByText("Adjustments: none")).toBeInTheDocument();
  });

  it("posts the amount in USD units with the cell's code, year and period", async () => {
    renderSheet();
    await openAdd();
    expect(screen.getByLabelText("Amount (USD millions)")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "-25");
    await userEvent.type(screen.getByLabelText("Reason"), "  Legal settlement ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: {
          canonical_code: "sga",
          fiscal_year: 2024,
          fiscal_period: "FY",
          amount: "-25000000",
          category: "one-off",
          reason: "Legal settlement",
        },
      }),
    );
    await waitFor(() => expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument());
  });

  it("parses the amount at scale B", async () => {
    setScale("B");
    renderSheet({}, "B");
    await openAdd();
    await userEvent.type(screen.getByLabelText("Amount (USD billions)"), "1.5");
    await userEvent.selectOptions(screen.getByLabelText("Category"), "reclass");
    await userEvent.type(screen.getByLabelText("Reason"), "Move");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0]![0]!.body).toMatchObject({
      amount: "1500000000",
      category: "reclass",
    });
  });

  it("sends nothing for an invalid amount or a blank reason", async () => {
    renderSheet();
    await openAdd();
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "abc");
    await userEvent.type(screen.getByLabelText("Reason"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Enter a number")).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("Amount (USD millions)"));
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "5");
    await userEvent.clear(screen.getByLabelText("Reason"));
    await userEvent.type(screen.getByLabelText("Reason"), "   ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Enter a reason")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("shows the API's 422 detail and keeps the form open", async () => {
    create.mockResolvedValue(
      errorResult(422, { detail: "Amount exceeds the reported value" }) as never,
    );
    renderSheet();
    await openAdd();
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "5");
    await userEvent.type(screen.getByLabelText("Reason"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Amount exceeds the reported value")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toHaveValue("x");
    expect(screen.getByLabelText("Amount (USD millions)")).toHaveValue("5");
  });

  it("falls back to a generic message when the error has no detail", async () => {
    create.mockResolvedValue(errorResult(500, {}) as never);
    renderSheet();
    await openAdd();
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "5");
    await userEvent.type(screen.getByLabelText("Reason"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Could not save the adjustment.")).toBeInTheDocument();
  });

  it("shows the normalized value next to the reported one", async () => {
    mockCell({ normalized_value: "-35000000" });
    renderSheet();
    const normalized = await screen.findByText(/Normalized/);
    expect(normalized).toHaveTextContent("Normalized (35)");
    expect(normalized).toHaveClass("prov-normalized");
  });

  it("does not show a normalized value when there is none", async () => {
    renderSheet();
    await screen.findByText(/Adjustments: none/);
    expect(screen.queryByText(/Normalized/)).not.toBeInTheDocument();
  });

  it("lists a propagated adjustment with its via label and no Edit/Delete", async () => {
    mockCell({
      adjustments: [
        cellAdjustment({ id: 1, reason: "Legal settlement", via: "sga", label: "SG&A" }),
      ],
    });
    renderSheet({ code: "ebit", label: "EBIT" });
    const item = (await screen.findByText(/Legal settlement/)).closest("li")!;
    expect(item).toHaveTextContent("FY2024");
    expect(item).toHaveTextContent("one-off");
    expect(item).toHaveTextContent("(25)");
    expect(item).toHaveTextContent("via SG&A");
    expect(within(item).queryByRole("button")).not.toBeInTheDocument();
  });

  it("prefills the edit form and PUTs to the id", async () => {
    mockCell({
      adjustments: [cellAdjustment({ id: 7, amount: "-25500000", category: "reclass" })],
    });
    renderSheet();
    await userEvent.click(
      await screen.findByRole("button", { name: "Edit adjustment Legal settlement" }),
    );
    expect(screen.getByLabelText("Amount (USD millions)")).toHaveValue("-25.5");
    expect(screen.getByLabelText("Category")).toHaveValue("reclass");
    expect(screen.getByLabelText("Reason")).toHaveValue("Legal settlement");

    await userEvent.clear(screen.getByLabelText("Reason"));
    await userEvent.type(screen.getByLabelText("Reason"), "Settlement");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        path: { ticker: "AAPL", adjustment_id: 7 },
        body: {
          canonical_code: "sga",
          fiscal_year: 2024,
          fiscal_period: "FY",
          amount: "-25500000",
          category: "reclass",
          reason: "Settlement",
        },
      }),
    );
    expect(create).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument());
  });

  async function editAndSave() {
    await userEvent.click(
      await screen.findByRole("button", { name: "Edit adjustment Legal settlement" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
  }

  it("keeps a Q2 adjustment's own period when it is edited from the FY cell", async () => {
    // A Q2 flow adjustment also lands in FY2024's cell, listed there with via null.
    mockCell({ adjustments: [cellAdjustment({ id: 7, fiscal_period: "Q2" })] });
    renderSheet({ fiscalPeriod: "FY" });
    await editAndSave();

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0]![0]!.body).toMatchObject({
      canonical_code: "sga",
      fiscal_year: 2024,
      fiscal_period: "Q2",
    });
  });

  it("keeps an FY adjustment's own period when it is edited from a Q4 cell", async () => {
    // An FY instant adjustment also lands in the same year's Q4 cell.
    mockCell({
      adjustments: [cellAdjustment({ id: 7, canonical_code: "cash", fiscal_period: "FY" })],
    });
    renderSheet({ code: "cash", label: "Cash", fiscalPeriod: "Q4" });
    await editAndSave();

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0]![0]!.body).toMatchObject({
      canonical_code: "cash",
      fiscal_year: 2024,
      fiscal_period: "FY",
    });
  });

  it("shows a 422 on edit and keeps the form open", async () => {
    update.mockResolvedValue(
      errorResult(422, { detail: "Amount exceeds the reported value" }) as never,
    );
    mockCell({ adjustments: [cellAdjustment({ id: 7 })] });
    renderSheet();
    await editAndSave();

    expect(await screen.findByText("Amount exceeds the reported value")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toHaveValue("Legal settlement");
  });

  it("disables Save while the edit is pending", async () => {
    update.mockReturnValue(new Promise(() => {}) as never);
    mockCell({ adjustments: [cellAdjustment({ id: 7 })] });
    renderSheet();
    await editAndSave();

    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("deletes only after the confirmation", async () => {
    mockCell({ adjustments: [cellAdjustment({ id: 7 })] });
    renderSheet();
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete adjustment Legal settlement" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete this adjustment?")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(remove).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", { name: "Delete adjustment Legal settlement" }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", adjustment_id: 7 } }),
    );
  });

  it("shows the API detail when the delete fails", async () => {
    remove.mockResolvedValue(errorResult(404, { detail: "Adjustment not found" }) as never);
    mockCell({ adjustments: [cellAdjustment({ id: 7 })] });
    renderSheet();
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete adjustment Legal settlement" }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByText("Adjustment not found")).toBeInTheDocument();
  });
});
