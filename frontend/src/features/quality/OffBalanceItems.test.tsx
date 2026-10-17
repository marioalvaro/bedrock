import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost,
  deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete,
  listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet,
  updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut,
} from "@/api/generated/sdk.gen";
import type { OffBalanceItemOut } from "@/api/generated/types.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { offBalanceItem, offBalanceItems } from "@/test/analysis";
import { errorResult, okResult } from "@/test/responses";

import { OffBalanceItems } from "./OffBalanceItems";

vi.mock("@/api/generated/sdk.gen", () => ({
  listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet: vi.fn(),
  createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost: vi.fn(),
  updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut: vi.fn(),
  deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete: vi.fn(),
}));

const list = vi.mocked(listOffBalanceItemsApiV1CompaniesTickerOffBalanceItemsGet);
const create = vi.mocked(createOffBalanceItemApiV1CompaniesTickerOffBalanceItemsPost);
const update = vi.mocked(updateOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdPut);
const remove = vi.mocked(deleteOffBalanceItemApiV1CompaniesTickerOffBalanceItemsItemIdDelete);

async function renderItems(items: OffBalanceItemOut[] = offBalanceItems()) {
  list.mockResolvedValue(okResult(items) as never);
  renderRaw();
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
}

function renderRaw() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <OffBalanceItems ticker="AAPL" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setScale("M");
  list.mockResolvedValue(okResult(offBalanceItems()) as never);
  create.mockResolvedValue(okResult(offBalanceItem({ id: 9 }), 201) as never);
  update.mockResolvedValue(okResult(offBalanceItem()) as never);
  remove.mockResolvedValue(okResult(null, 204) as never);
});

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

const save = () => userEvent.click(screen.getByRole("button", { name: "Save" }));
const openAdd = () => userEvent.click(screen.getByRole("button", { name: "Add item" }));

describe("OffBalanceItems list", () => {
  it("shows the heading, Add item and None logged for an empty list", async () => {
    await renderItems([]);
    expect(
      screen.getByRole("heading", { level: 2, name: "Off-balance-sheet items" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Add item" })).toBeVisible();
    expect(screen.getByText("None logged.")).toBeVisible();
  });

  it("lists items in order with kind, description, scaled amount, as-of and source note", async () => {
    await renderItems();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const first = within(rows[0]!);
    expect(first.getByText("Purchase commitment")).toBeVisible();
    expect(first.getByText("Unconditional purchase obligations")).toBeVisible();
    expect(first.getByText("12,500")).toBeVisible();
    expect(first.getByText("as of 2024-09-28")).toBeVisible();
    expect(first.getByText("10-K Note 12")).toBeVisible();
    expect(
      first.getByRole("button", { name: "Edit Unconditional purchase obligations" }),
    ).toBeVisible();
    expect(
      first.getByRole("button", { name: "Delete Unconditional purchase obligations" }),
    ).toBeVisible();
  });

  it("shows a dash and no source note for an item without them", async () => {
    await renderItems();
    const second = within(screen.getAllByRole("listitem")[1]!);
    expect(second.getByText("Guarantee")).toBeVisible();
    expect(second.getByText("—")).toBeVisible();
    expect(second.getByText("as of 2023-09-30")).toBeVisible();
    expect(second.queryByText("10-K Note 12")).not.toBeInTheDocument();
  });

  it("formats the amount at scale B", async () => {
    setScale("B");
    await renderItems();
    expect(screen.getByText("12.5")).toBeVisible();
  });

  it("labels every kind", async () => {
    const kinds = ["lease", "guarantee", "vie", "purchase_commitment", "other"] as const;
    await renderItems(
      kinds.map((kind, i) => offBalanceItem({ id: i + 1, kind, description: `d${i}` })),
    );
    for (const label of ["Lease", "Guarantee", "VIE", "Purchase commitment", "Other"]) {
      expect(screen.getByText(label)).toBeVisible();
    }
  });
});

describe("OffBalanceItems loading", () => {
  it("fetches the list for the ticker and renders the response", async () => {
    await renderItems([offBalanceItem({ id: 7, description: "From the GET" })]);
    expect(list).toHaveBeenCalledWith({ path: { ticker: "AAPL" } });
    expect(screen.getByText("From the GET")).toBeVisible();
  });

  it("shows Loading… while pending", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderRaw();
    expect(screen.getByText("Loading…")).toBeVisible();
    expect(screen.queryByText("None logged.")).not.toBeInTheDocument();
  });

  it("shows an error line when the list fails", async () => {
    list.mockResolvedValue(errorResult(500, {}) as never);
    renderRaw();
    const line = await screen.findByText("Could not load the off-balance-sheet items.");
    expect(line).toHaveClass("text-destructive");
    expect(screen.queryByText("None logged.")).not.toBeInTheDocument();
  });
});

describe("OffBalanceItems add form", () => {
  it("posts the exact body in USD units with trimmed text", async () => {
    await renderItems([]);
    await openAdd();
    expect(screen.getByLabelText("Kind")).toHaveValue("lease");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "vie");
    await userEvent.type(screen.getByLabelText("Description"), "  Lease for HQ ");
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "12.5");
    await userEvent.type(screen.getByLabelText("As of"), "2024-09-28");
    await userEvent.type(screen.getByLabelText("Source note"), " Note 7 ");
    await save();

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: {
          kind: "vie",
          description: "Lease for HQ",
          amount: "12500000",
          as_of: "2024-09-28",
          source_note: "Note 7",
        },
      }),
    );
    await waitFor(() => expect(screen.queryByLabelText("Description")).not.toBeInTheDocument());
  });

  it("parses the amount at scale B", async () => {
    setScale("B");
    await renderItems([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Description"), "x");
    await userEvent.type(screen.getByLabelText("Amount (USD billions)"), "1.5");
    await userEvent.type(screen.getByLabelText("As of"), "2024-09-28");
    await save();
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0]![0]!.body).toMatchObject({ amount: "1500000000" });
  });

  it("sends null for a blank amount and a blank source note", async () => {
    await renderItems([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Description"), "x");
    await userEvent.type(screen.getByLabelText("As of"), "2024-09-28");
    await userEvent.type(screen.getByLabelText("Source note"), "   ");
    await save();
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0]![0]!.body).toEqual({
      kind: "lease",
      description: "x",
      amount: null,
      as_of: "2024-09-28",
      source_note: null,
    });
  });

  it("validates in order and sends nothing", async () => {
    await renderItems([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Description"), "   ");
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "abc");
    await save();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a description");

    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.type(screen.getByLabelText("Description"), "x");
    await save();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number");

    await userEvent.clear(screen.getByLabelText("Amount (USD millions)"));
    await save();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a date");
    expect(create).not.toHaveBeenCalled();
  });

  it("shows the API's 422 detail and keeps the form open", async () => {
    create.mockResolvedValue(errorResult(422, { detail: "Unknown kind" }) as never);
    await renderItems([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Description"), "x");
    await userEvent.type(screen.getByLabelText("As of"), "2024-09-28");
    await save();
    expect(await screen.findByText("Unknown kind")).toBeVisible();
    expect(screen.getByLabelText("Description")).toHaveValue("x");
  });

  it("falls back to a generic message without a detail", async () => {
    create.mockResolvedValue(errorResult(500, {}) as never);
    await renderItems([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Description"), "x");
    await userEvent.type(screen.getByLabelText("As of"), "2024-09-28");
    await save();
    expect(await screen.findByText("Could not save the item.")).toBeVisible();
  });

  it("disables Save while the request is pending", async () => {
    create.mockReturnValue(new Promise(() => {}) as never);
    await renderItems([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Description"), "x");
    await userEvent.type(screen.getByLabelText("As of"), "2024-09-28");
    await save();
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
  });

  it("closes the form on Cancel without sending", async () => {
    await renderItems([]);
    await openAdd();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Description")).not.toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });
});

describe("OffBalanceItems edit", () => {
  it("prefills every field and PUTs to the item's id", async () => {
    await renderItems();
    await userEvent.click(
      screen.getByRole("button", { name: "Edit Unconditional purchase obligations" }),
    );
    expect(screen.getByLabelText("Kind")).toHaveValue("purchase_commitment");
    expect(screen.getByLabelText("Description")).toHaveValue("Unconditional purchase obligations");
    expect(screen.getByLabelText("Amount (USD millions)")).toHaveValue("12500");
    expect(screen.getByLabelText("As of")).toHaveValue("2024-09-28");
    expect(screen.getByLabelText("Source note")).toHaveValue("10-K Note 12");

    await userEvent.clear(screen.getByLabelText("Amount (USD millions)"));
    await userEvent.type(screen.getByLabelText("Amount (USD millions)"), "13");
    await save();
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        path: { ticker: "AAPL", item_id: 3 },
        body: {
          kind: "purchase_commitment",
          description: "Unconditional purchase obligations",
          amount: "13000000",
          as_of: "2024-09-28",
          source_note: "10-K Note 12",
        },
      }),
    );
    expect(create).not.toHaveBeenCalled();
  });

  it("prefills blank amount and source note for an item without them", async () => {
    await renderItems();
    await userEvent.click(screen.getByRole("button", { name: "Edit Guarantees of supplier debt" }));
    expect(screen.getByLabelText("Amount (USD millions)")).toHaveValue("");
    expect(screen.getByLabelText("Source note")).toHaveValue("");
  });
});

describe("OffBalanceItems edit regressions", () => {
  it("re-fills the amount in the new scale when the scale changes mid-edit", async () => {
    await renderItems([offBalanceItem({ amount: "25000000" })]);
    await userEvent.click(
      screen.getByRole("button", { name: "Edit Unconditional purchase obligations" }),
    );
    expect(screen.getByLabelText("Amount (USD millions)")).toHaveValue("25");
    act(() => setScale("B"));
    expect(screen.getByLabelText("Amount (USD billions)")).toHaveValue("0.025");
    await save();
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0]![0]!.body).toMatchObject({ amount: "25000000" });
  });

  it("sends amount null when an existing amount is cleared", async () => {
    await renderItems();
    await userEvent.click(
      screen.getByRole("button", { name: "Edit Unconditional purchase obligations" }),
    );
    await userEvent.clear(screen.getByLabelText("Amount (USD millions)"));
    await save();
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0]![0]!.body).toMatchObject({ amount: null });
  });

  it("keeps the form open and shows the detail on an edit 422", async () => {
    update.mockResolvedValue(errorResult(422, { detail: "Amount too large" }) as never);
    await renderItems();
    await userEvent.click(
      screen.getByRole("button", { name: "Edit Unconditional purchase obligations" }),
    );
    await save();
    expect(await screen.findByText("Amount too large")).toBeVisible();
    expect(screen.getByLabelText("Description")).toHaveValue("Unconditional purchase obligations");
  });

  it("closes the form when the item being edited is deleted", async () => {
    await renderItems();
    await userEvent.click(
      screen.getByRole("button", { name: "Edit Unconditional purchase obligations" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Delete Unconditional purchase obligations" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(remove).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByLabelText("Description")).not.toBeInTheDocument());
  });
});

describe("OffBalanceItems delete", () => {
  it("deletes only after confirmation", async () => {
    await renderItems();
    await userEvent.click(
      screen.getByRole("button", { name: "Delete Unconditional purchase obligations" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete this item?")).toBeVisible();
    expect(within(dialog).getByText("Unconditional purchase obligations")).toBeVisible();
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", item_id: 3 } }),
    );
  });

  it("sends nothing when the dialog is cancelled", async () => {
    await renderItems();
    await userEvent.click(
      screen.getByRole("button", { name: "Delete Guarantees of supplier debt" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(remove).not.toHaveBeenCalled();
  });

  it("shows the API detail when the delete fails", async () => {
    remove.mockResolvedValue(errorResult(422, { detail: "Item is locked" }) as never);
    await renderItems();
    await userEvent.click(
      screen.getByRole("button", { name: "Delete Guarantees of supplier debt" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Item is locked")).toBeVisible();
  });
});
