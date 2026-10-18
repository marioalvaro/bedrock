import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createCustomRuleApiV1QoeCustomRulesPost,
  deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete,
  listCustomRulesApiV1QoeCustomRulesGet,
  updateCustomRuleApiV1QoeCustomRulesRuleIdPut,
} from "@/api/generated/sdk.gen";
import type { QoeCustomRuleOut } from "@/api/generated/types.gen";
import { FORMULA_HINT, FORMULA_UNITS_NOTE } from "@/lib/levels";
import { createQueryClient } from "@/lib/query-client";
import { qoeCustomRule } from "@/test/analysis";
import { errorResult, okResult } from "@/test/responses";

import { CustomRules } from "./CustomRules";

vi.mock("@/api/generated/sdk.gen", () => ({
  listCustomRulesApiV1QoeCustomRulesGet: vi.fn(),
  createCustomRuleApiV1QoeCustomRulesPost: vi.fn(),
  updateCustomRuleApiV1QoeCustomRulesRuleIdPut: vi.fn(),
  deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete: vi.fn(),
}));

const list = vi.mocked(listCustomRulesApiV1QoeCustomRulesGet);
const create = vi.mocked(createCustomRuleApiV1QoeCustomRulesPost);
const update = vi.mocked(updateCustomRuleApiV1QoeCustomRulesRuleIdPut);
const remove = vi.mocked(deleteCustomRuleApiV1QoeCustomRulesRuleIdDelete);

const formulaRule = () =>
  qoeCustomRule({
    id: 2,
    code: "custom_2",
    label: "Broken rule",
    formula: "revenu / 2",
    direction: "below",
    unit: "x",
    warn: null,
    alert: null,
    warn_formula: "avg(revenue) * 2",
    error: "Unknown name 'revenu' at 0",
  });

function renderRaw() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <CustomRules />
    </QueryClientProvider>,
  );
}

async function renderRules(rules: QoeCustomRuleOut[] = [qoeCustomRule(), formulaRule()]) {
  list.mockResolvedValue(okResult(rules) as never);
  renderRaw();
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
}

beforeEach(() => {
  create.mockResolvedValue(okResult(qoeCustomRule({ id: 9 }), 201) as never);
  update.mockResolvedValue(okResult(qoeCustomRule()) as never);
  remove.mockResolvedValue(okResult(null, 204) as never);
});

afterEach(() => vi.clearAllMocks());

const openAdd = () => userEvent.click(screen.getByRole("button", { name: "Add rule" }));
const save = () => userEvent.click(screen.getByRole("button", { name: "Save" }));

describe("CustomRules list", () => {
  it("shows the heading, the hint and the rules with levels and error", async () => {
    await renderRules();
    expect(screen.getByRole("heading", { level: 2, name: "Custom rules" })).toBeVisible();
    expect(screen.getByText(FORMULA_HINT)).toBeVisible();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const first = within(rows[0]!);
    expect(first.getByText("Accruals (mine)")).toBeVisible();
    expect(first.getByText("(net_income - cfo) / avg(total_assets)")).toBeVisible();
    expect(first.getByText(/warn > 5%/)).toBeVisible();
    expect(first.getByText(/alert > 10%/)).toBeVisible();
    const second = within(rows[1]!);
    expect(second.getByText(/avg\(revenue\) \* 2/)).toBeVisible();
    expect(second.getByText("Unknown name 'revenu' at 0")).toHaveClass("text-destructive");
  });

  it("shows its own loading state while the list is pending", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderRaw();
    expect(screen.getByText("Loading…")).toBeVisible();
  });

  it("shows the empty state", async () => {
    await renderRules([]);
    expect(screen.getByText("No custom rules.")).toBeVisible();
  });

  it("shows an error when the list cannot load", async () => {
    list.mockResolvedValue(errorResult(500) as never);
    renderRaw();
    expect(await screen.findByText("Could not load the custom rules.")).toBeVisible();
  });
});

describe("CustomRules form", () => {
  it("sends percent levels as fractions for a pct rule", async () => {
    await renderRules([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Label"), "Accruals");
    await userEvent.type(screen.getByLabelText("Formula"), "net_income / revenue");
    await userEvent.type(screen.getByLabelText("Warn"), "5");
    await userEvent.type(screen.getByLabelText("Alert"), "10");
    await save();
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        body: {
          label: "Accruals",
          formula: "net_income / revenue",
          direction: "above",
          unit: "pct",
          warn: "0.05",
          alert: "0.1",
        },
      }),
    );
    await waitFor(() => expect(screen.queryByLabelText("Label")).not.toBeInTheDocument());
  });

  it("sends a formula level as typed and marks it with ƒ", async () => {
    await renderRules([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Label"), "Rule");
    await userEvent.type(screen.getByLabelText("Formula"), "revenue");
    expect(screen.queryByText("ƒ")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Warn"), "avg(revenue)");
    expect(screen.getByText("ƒ")).toBeVisible();
    await save();
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        body: expect.objectContaining({ warn: "avg(revenue)", alert: null }),
      }),
    );
  });

  it("shows the fractions note only while a level is a formula, once", async () => {
    await renderRules([]);
    await openAdd();
    expect(screen.queryByText(FORMULA_UNITS_NOTE)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Warn"), "5");
    expect(screen.queryByText(FORMULA_UNITS_NOTE)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Alert"), "avg(revenue)");
    expect(screen.getByText(FORMULA_UNITS_NOTE)).toBeVisible();
    await userEvent.clear(screen.getByLabelText("Warn"));
    await userEvent.type(screen.getByLabelText("Warn"), "prev(revenue)");
    expect(screen.getAllByText(FORMULA_UNITS_NOTE)).toHaveLength(1);
  });

  it("sends direction below and unit x with an x level as typed", async () => {
    await renderRules([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Label"), "Cover");
    await userEvent.type(screen.getByLabelText("Formula"), "revenue");
    await userEvent.selectOptions(screen.getByLabelText("Direction"), "below");
    await userEvent.selectOptions(screen.getByLabelText("Unit"), "x");
    await userEvent.type(screen.getByLabelText("Warn"), "0.8");
    await save();
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        body: {
          label: "Cover",
          formula: "revenue",
          direction: "below",
          unit: "x",
          warn: "0.8",
          alert: null,
        },
      }),
    );
  });

  it("shows the API detail on a 422 from an update", async () => {
    update.mockResolvedValue(errorResult(422, { detail: "Bad formula at 3" }) as never);
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Edit Accruals (mine)" }));
    await save();
    expect(await screen.findByRole("alert")).toHaveTextContent("Bad formula at 3");
    expect(screen.getByLabelText("Label")).toBeVisible();
  });

  it("does not send a blank label or formula", async () => {
    await renderRules([]);
    await openAdd();
    await save();
    expect(await screen.findByText("Enter a label")).toBeVisible();
    await userEvent.type(screen.getByLabelText("Label"), "x");
    await save();
    expect(await screen.findByText("Enter a formula")).toBeVisible();
    expect(create).not.toHaveBeenCalled();
  });

  it("shows the API detail on a 422 and keeps the form open", async () => {
    create.mockResolvedValue(errorResult(422, { detail: "Unknown name 'revenu' at 0" }) as never);
    await renderRules([]);
    await openAdd();
    await userEvent.type(screen.getByLabelText("Label"), "x");
    await userEvent.type(screen.getByLabelText("Formula"), "revenu");
    await save();
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown name 'revenu' at 0");
    expect(screen.getByLabelText("Formula")).toHaveValue("revenu");
  });

  it("prefills on edit and PUTs to the rule id", async () => {
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Edit Accruals (mine)" }));
    expect(screen.getByLabelText("Label")).toHaveValue("Accruals (mine)");
    expect(screen.getByLabelText("Formula")).toHaveValue("(net_income - cfo) / avg(total_assets)");
    expect(screen.getByLabelText("Warn")).toHaveValue("5");
    expect(screen.getByLabelText("Alert")).toHaveValue("10");
    await userEvent.clear(screen.getByLabelText("Alert"));
    await save();
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        path: { rule_id: 1 },
        body: {
          label: "Accruals (mine)",
          formula: "(net_income - cfo) / avg(total_assets)",
          direction: "above",
          unit: "pct",
          warn: "0.05",
          alert: null,
        },
      }),
    );
  });

  it("prefills a formula level with its text and the ƒ marker", async () => {
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Edit Broken rule" }));
    expect(screen.getByLabelText("Warn")).toHaveValue("avg(revenue) * 2");
    expect(screen.getByText("ƒ")).toBeVisible();
  });

  it("closes the form on Cancel", async () => {
    await renderRules([]);
    await openAdd();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Label")).not.toBeInTheDocument();
  });
});

describe("CustomRules delete", () => {
  it("asks for confirmation, then DELETEs", async () => {
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Delete Accruals (mine)" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith({ path: { rule_id: 1 } }));
  });

  it("shows an error when the delete fails", async () => {
    remove.mockResolvedValue(errorResult(500, {}) as never);
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Delete Accruals (mine)" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete the rule.");
  });

  it("shows the API detail when the delete fails with one", async () => {
    remove.mockResolvedValue(errorResult(409, { detail: "Rule is in use" }) as never);
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Delete Accruals (mine)" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Rule is in use");
  });

  it("never calls DELETE when the dialog is cancelled", async () => {
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Delete Accruals (mine)" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(remove).not.toHaveBeenCalled();
  });

  it("closes the form when the rule being edited is deleted", async () => {
    await renderRules();
    await userEvent.click(screen.getByRole("button", { name: "Edit Accruals (mine)" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete Accruals (mine)" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByLabelText("Label")).not.toBeInTheDocument());
  });
});
