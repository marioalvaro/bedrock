// Thesis checkpoints on the Notes tab (M7c, FR-NOTE-03).
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createCheckpointApiV1CompaniesTickerCheckpointsPost,
  deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete,
  listCheckpointsApiV1CompaniesTickerCheckpointsGet,
  updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut,
} from "@/api/generated/sdk.gen";
import type { CheckpointOut } from "@/api/generated/types.gen";
import { createQueryClient } from "@/lib/query-client";
import { checkpointList, checkpointOut } from "@/test/checkpoints";
import { errorResult, okResult } from "@/test/responses";

import { CheckpointsPanel } from "./CheckpointsPanel";

vi.mock("@/api/generated/sdk.gen", () => ({
  createCheckpointApiV1CompaniesTickerCheckpointsPost: vi.fn(),
  deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete: vi.fn(),
  listCheckpointsApiV1CompaniesTickerCheckpointsGet: vi.fn(),
  updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut: vi.fn(),
}));

const list = vi.mocked(listCheckpointsApiV1CompaniesTickerCheckpointsGet);
const create = vi.mocked(createCheckpointApiV1CompaniesTickerCheckpointsPost);
const update = vi.mocked(updateCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdPut);
const remove = vi.mocked(deleteCheckpointApiV1CompaniesTickerCheckpointsCheckpointIdDelete);

afterEach(() => vi.clearAllMocks());

function renderPanel(checkpoints: CheckpointOut[] = [checkpointOut()]) {
  list.mockResolvedValue(okResult(checkpointList({ checkpoints })) as never);
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <CheckpointsPanel ticker="AAPL" />
    </QueryClientProvider>,
  );
}

const bodyRows = async () => {
  const table = await screen.findByRole("table", { name: "Thesis checkpoints" });
  return within(table).getAllByRole("row").slice(1);
};

describe("the list", () => {
  it("shows each checkpoint's state, statement, value and period", async () => {
    renderPanel();
    const [row] = await bodyRows();
    expect(within(row!).getByText("Holding")).toBeInTheDocument();
    expect(within(row!).getByText("Gross margin holds")).toBeInTheDocument();
    expect(within(row!).getByText("gross_margin > 44%")).toHaveClass("font-mono");
    expect(within(row!).getByText("45.2% vs 44.0%")).toBeInTheDocument();
    expect(within(row!).getByText("Q3 FY26 TTM")).toBeInTheDocument();
  });

  it.each([
    ["holding", "Holding", ""],
    ["at_risk", "At risk", "flag-warn"],
    ["broken", "Broken", "flag-alert"],
    ["unknown", "Unknown", "text-muted-foreground"],
  ] as const)("colors the %s state", async (state, word, className) => {
    renderPanel([checkpointOut({ state })]);
    const [row] = await bodyRows();
    const cell = within(row!).getByText(word);
    if (className) expect(cell).toHaveClass(className);
    else expect(cell).not.toHaveClass("flag-warn", "flag-alert", "text-muted-foreground");
  });

  it("says what the last filing changed", async () => {
    renderPanel([
      checkpointOut({ id: 1, state: "broken", previous_state: "holding", changed: true }),
      checkpointOut({ id: 2, label: "Steady", changed: false }),
      checkpointOut({ id: 3, label: "First", previous_state: "unknown", changed: true }),
    ]);
    const [changed, steady, first] = await bodyRows();
    expect(within(changed!).getByText("was Holding")).toBeInTheDocument();
    expect(within(steady!).queryByText(/^was /)).not.toBeInTheDocument();
    expect(within(first!).getByText("New")).toBeInTheDocument();
  });

  it("shows a stored statement's error in place of the value", async () => {
    renderPanel([
      checkpointOut({
        state: "unknown",
        error: "Unknown name 'gross_mgn' at 0",
        left: null,
        right: null,
        period: null,
      }),
    ]);
    const [row] = await bodyRows();
    expect(within(row!).getByText("Unknown name 'gross_mgn' at 0")).toBeInTheDocument();
    expect(within(row!).queryByText(/ vs /)).not.toBeInTheDocument();
  });

  it("invites the first checkpoint when there is none", async () => {
    renderPanel([]);
    expect(
      await screen.findByText(
        "No checkpoints yet. Write what must stay true for the thesis to hold.",
      ),
    ).toBeInTheDocument();
  });

  it("says when the checkpoints cannot be loaded", async () => {
    list.mockResolvedValue(errorResult(500) as never);
    const queryClient = createQueryClient();
    queryClient.setDefaultOptions({ queries: { retry: false } });
    render(
      <QueryClientProvider client={queryClient}>
        <CheckpointsPanel ticker="AAPL" />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Could not load the checkpoints.")).toBeInTheDocument();
  });
});

describe("adding", () => {
  it("posts the statement, label, frequency and margin", async () => {
    create.mockResolvedValue(okResult(checkpointOut({ id: 9 }), 201) as never);
    renderPanel([]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add checkpoint" }));

    const statement = screen.getByLabelText("Statement");
    expect(statement).toHaveAttribute("placeholder", "gross_margin > 44%");
    expect(screen.getByLabelText("At-risk margin")).toHaveAttribute("placeholder", "e.g. 1%");
    expect(screen.getByRole("radio", { name: "TTM" })).toBeChecked();
    await user.type(statement, "roic > prev(roic) - 2%");
    await user.type(screen.getByLabelText("Label"), "Returns hold");
    await user.click(screen.getByRole("radio", { name: "Annual" }));
    await user.type(screen.getByLabelText("At-risk margin"), "1%");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: {
          statement: "roic > prev(roic) - 2%",
          label: "Returns hold",
          freq: "annual",
          margin: "1%",
        },
      }),
    );
    await waitFor(() => expect(screen.queryByLabelText("Statement")).not.toBeInTheDocument());
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("sends no label and no margin when they are left blank", async () => {
    create.mockResolvedValue(okResult(checkpointOut(), 201) as never);
    renderPanel([]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add checkpoint" }));
    await user.type(screen.getByLabelText("Statement"), "gross_margin > 44%");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: { statement: "gross_margin > 44%", label: null, freq: "ttm", margin: null },
      }),
    );
  });

  it("keeps the text and shows the API's reason under the statement on a 422", async () => {
    create.mockResolvedValue(
      errorResult(422, {
        detail: "A checkpoint compares two values: use >, >=, < or <= (at 0)",
      }) as never,
    );
    renderPanel([]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add checkpoint" }));
    await user.type(screen.getByLabelText("Statement"), "gross_margin");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A checkpoint compares two values: use >, >=, < or <= (at 0)");
    expect(screen.getByLabelText("Statement")).toHaveValue("gross_margin");
    expect(screen.getByLabelText("Statement")).toHaveAttribute("aria-invalid", "true");
  });

  it("closes the form on Cancel", async () => {
    renderPanel([]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add checkpoint" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Statement")).not.toBeInTheDocument();
  });
});

describe("editing and deleting", () => {
  it("opens the form filled with the checkpoint and puts the change", async () => {
    update.mockResolvedValue(okResult(checkpointOut()) as never);
    renderPanel([checkpointOut({ id: 4, margin: "0.01", freq: "annual" })]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit Gross margin holds" }));

    expect(screen.getByLabelText("Statement")).toHaveValue("gross_margin > 44%");
    expect(screen.getByLabelText("Label")).toHaveValue("Gross margin holds");
    expect(screen.getByLabelText("At-risk margin")).toHaveValue("0.01");
    expect(screen.getByRole("radio", { name: "Annual" })).toBeChecked();
    await user.clear(screen.getByLabelText("Statement"));
    await user.type(screen.getByLabelText("Statement"), "gross_margin > 45%");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        path: { ticker: "AAPL", checkpoint_id: 4 },
        body: {
          statement: "gross_margin > 45%",
          label: "Gross margin holds",
          freq: "annual",
          margin: "0.01",
        },
      }),
    );
  });

  it("deletes a checkpoint after confirming", async () => {
    remove.mockResolvedValue(okResult(null, 204) as never);
    renderPanel([checkpointOut({ id: 4 })]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete Gross margin holds" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", checkpoint_id: 4 } }),
    );
  });

  it("says when a delete fails", async () => {
    remove.mockResolvedValue(errorResult(500, {}) as never);
    renderPanel([checkpointOut({ id: 4 })]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete Gross margin holds" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete the checkpoint.");
  });
});
