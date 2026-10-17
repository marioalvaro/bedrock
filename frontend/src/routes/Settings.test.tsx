import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listQoeRulesApiV1QoeRulesGet,
  resetQoeThresholdsApiV1QoeRulesCodeDelete,
  setQoeThresholdsApiV1QoeRulesCodePut,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { qoeRule, qoeRules } from "@/test/analysis";
import { errorResult, okResult } from "@/test/responses";

import { Settings } from "./Settings";

vi.mock("@/api/generated/sdk.gen", () => ({
  listQoeRulesApiV1QoeRulesGet: vi.fn(),
  setQoeThresholdsApiV1QoeRulesCodePut: vi.fn(),
  resetQoeThresholdsApiV1QoeRulesCodeDelete: vi.fn(),
}));

function renderSettings() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <Settings />
    </QueryClientProvider>,
  );
}

async function setup(rules = qoeRules()) {
  vi.mocked(listQoeRulesApiV1QoeRulesGet).mockResolvedValue(okResult(rules) as never);
  renderSettings();
  await screen.findByRole("heading", { name: "Quality-of-earnings thresholds" });
  await screen.findByLabelText("Accruals ratio warn");
}

const input = (name: string) => screen.getByLabelText(name) as HTMLInputElement;

describe("Settings", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("still renders the theme toggle", async () => {
    await setup();
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeInTheDocument();
  });

  it("prefills pct as percent, x as typed, and a null level as empty", async () => {
    await setup([
      ...qoeRules(),
      qoeRule({
        code: "goodwill_impairment",
        label: "Goodwill impairment",
        warn: "0",
        alert: null,
      }),
    ]);
    expect(input("Accruals ratio warn").value).toBe("5");
    expect(input("Accruals ratio alert").value).toBe("10");
    expect(input("CFO / net income warn").value).toBe("0.8");
    expect(input("CFO / net income alert").value).toBe("0");
    expect(input("Goodwill impairment warn").value).toBe("0");
    expect(input("Goodwill impairment alert").value).toBe("");
  });

  it("sends a percent input as an exact fraction and keeps the other key", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockResolvedValue(okResult(qoeRule()) as never);
    await setup();
    await userEvent.clear(input("Accruals ratio warn"));
    await userEvent.type(input("Accruals ratio warn"), "12.5");
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    await waitFor(() =>
      expect(setQoeThresholdsApiV1QoeRulesCodePut).toHaveBeenCalledWith({
        path: { code: "accruals_ratio" },
        body: { warn: "0.125", alert: "0.1" },
      }),
    );
  });

  it("sends an x input as typed", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockResolvedValue(okResult(qoeRule()) as never);
    await setup();
    await userEvent.clear(input("CFO / net income warn"));
    await userEvent.type(input("CFO / net income warn"), "0.9");
    await userEvent.click(screen.getByRole("button", { name: "Save CFO / net income" }));
    await waitFor(() =>
      expect(setQoeThresholdsApiV1QoeRulesCodePut).toHaveBeenCalledWith({
        path: { code: "cfo_to_net_income" },
        body: { warn: "0.9", alert: "0" },
      }),
    );
  });

  it("sends null for a blanked input", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockResolvedValue(okResult(qoeRule()) as never);
    await setup();
    await userEvent.clear(input("Accruals ratio alert"));
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    await waitFor(() =>
      expect(setQoeThresholdsApiV1QoeRulesCodePut).toHaveBeenCalledWith({
        path: { code: "accruals_ratio" },
        body: { warn: "0.05", alert: null },
      }),
    );
  });

  it("rejects malformed input without sending", async () => {
    await setup();
    await userEvent.clear(input("Accruals ratio warn"));
    await userEvent.type(input("Accruals ratio warn"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a number");
    expect(setQoeThresholdsApiV1QoeRulesCodePut).not.toHaveBeenCalled();
  });

  it("shows the 422 detail in the row", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockResolvedValue(
      errorResult(422, { detail: "warn must be below alert" }) as never,
    );
    await setup();
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("warn must be below alert");
  });

  it("disables Save while the request is pending", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockReturnValue(new Promise(() => {}) as never);
    await setup();
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Accruals ratio" })).toBeDisabled(),
    );
  });

  it("offers Reset only on the overridden row and deletes that code", async () => {
    vi.mocked(resetQoeThresholdsApiV1QoeRulesCodeDelete).mockResolvedValue(
      okResult(qoeRule()) as never,
    );
    await setup();
    expect(screen.getAllByRole("button", { name: /^Reset / })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Reset SBC / revenue" }));
    await waitFor(() =>
      expect(resetQoeThresholdsApiV1QoeRulesCodeDelete).toHaveBeenCalledWith({
        path: { code: "sbc_to_revenue" },
      }),
    );
  });

  it("shows the API detail when Reset fails", async () => {
    vi.mocked(resetQoeThresholdsApiV1QoeRulesCodeDelete).mockResolvedValue(
      errorResult(404, { detail: "Unknown rule" }) as never,
    );
    await setup();
    await userEvent.click(screen.getByRole("button", { name: "Reset SBC / revenue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown rule");
  });

  it("Reset refetches the rules and shows the defaults", async () => {
    const [accruals, sbc, cfo] = qoeRules();
    vi.mocked(resetQoeThresholdsApiV1QoeRulesCodeDelete).mockResolvedValue(
      okResult(qoeRule()) as never,
    );
    vi.mocked(listQoeRulesApiV1QoeRulesGet)
      .mockResolvedValueOnce(okResult([accruals, sbc, cfo]) as never)
      .mockResolvedValue(
        okResult([
          accruals,
          { ...sbc, warn: "0.05", alert: "0.1", overridden: false },
          cfo,
        ]) as never,
      );
    renderSettings();
    await screen.findByLabelText("SBC / revenue warn");
    expect(input("SBC / revenue warn").value).toBe("1");
    await userEvent.click(screen.getByRole("button", { name: "Reset SBC / revenue" }));
    await waitFor(() => expect(input("SBC / revenue warn").value).toBe("5"));
    expect(input("SBC / revenue alert").value).toBe("10");
    expect(screen.queryByRole("button", { name: "Reset SBC / revenue" })).not.toBeInTheDocument();
  });

  it("Save refetches and shows the saved level", async () => {
    const [accruals, sbc, cfo] = qoeRules();
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockResolvedValue(okResult(accruals) as never);
    vi.mocked(listQoeRulesApiV1QoeRulesGet)
      .mockResolvedValueOnce(okResult([accruals, sbc, cfo]) as never)
      .mockResolvedValue(
        okResult([{ ...accruals, warn: "0.07", overridden: true }, sbc, cfo]) as never,
      );
    renderSettings();
    await screen.findByLabelText("Accruals ratio warn");
    await userEvent.clear(input("Accruals ratio warn"));
    await userEvent.type(input("Accruals ratio warn"), "7");
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    await screen.findByRole("button", { name: "Reset Accruals ratio" });
    expect(input("Accruals ratio warn").value).toBe("7");
  });

  it("re-syncs unsaved text when an override equal to the defaults is reset", async () => {
    const [accruals, sbc, cfo] = qoeRules();
    const same = { ...sbc, warn: "0.05", alert: "0.1", overridden: true };
    vi.mocked(resetQoeThresholdsApiV1QoeRulesCodeDelete).mockResolvedValue(
      okResult(qoeRule()) as never,
    );
    vi.mocked(listQoeRulesApiV1QoeRulesGet)
      .mockResolvedValueOnce(okResult([accruals, same, cfo]) as never)
      .mockResolvedValue(okResult([accruals, { ...same, overridden: false }, cfo]) as never);
    renderSettings();
    await screen.findByLabelText("SBC / revenue warn");
    await userEvent.type(input("SBC / revenue warn"), "99");
    expect(input("SBC / revenue warn").value).toBe("599");
    await userEvent.click(screen.getByRole("button", { name: "Reset SBC / revenue" }));
    await waitFor(() => expect(input("SBC / revenue warn").value).toBe("5"));
  });

  it("clears the row error after a successful retry", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut)
      .mockResolvedValueOnce(errorResult(422, { detail: "warn must be below alert" }) as never)
      .mockResolvedValueOnce(okResult(qoeRule()) as never);
    await setup();
    const save = screen.getByRole("button", { name: "Save Accruals ratio" });
    await userEvent.click(save);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await userEvent.click(save);
    await waitFor(() => expect(setQoeThresholdsApiV1QoeRulesCodePut).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("starting Reset clears a Save error", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockResolvedValue(
      errorResult(422, { detail: "save failed" }) as never,
    );
    vi.mocked(resetQoeThresholdsApiV1QoeRulesCodeDelete).mockReturnValue(
      new Promise(() => {}) as never,
    );
    await setup();
    await userEvent.click(screen.getByRole("button", { name: "Save SBC / revenue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("save failed");
    await userEvent.click(screen.getByRole("button", { name: "Reset SBC / revenue" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("starting Save clears a Reset error", async () => {
    vi.mocked(resetQoeThresholdsApiV1QoeRulesCodeDelete).mockResolvedValue(
      errorResult(404, { detail: "reset failed" }) as never,
    );
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockReturnValue(new Promise(() => {}) as never);
    await setup();
    await userEvent.click(screen.getByRole("button", { name: "Reset SBC / revenue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("reset failed");
    await userEvent.click(screen.getByRole("button", { name: "Save SBC / revenue" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("rejects malformed text in the alert field only", async () => {
    await setup();
    await userEvent.clear(input("Accruals ratio alert"));
    await userEvent.type(input("Accruals ratio alert"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a number");
    expect(setQoeThresholdsApiV1QoeRulesCodePut).not.toHaveBeenCalled();
  });

  it("shows a generic message when a failure has no detail", async () => {
    vi.mocked(setQoeThresholdsApiV1QoeRulesCodePut).mockResolvedValue(
      errorResult(500, {}) as never,
    );
    await setup();
    await userEvent.click(screen.getByRole("button", { name: "Save Accruals ratio" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save the thresholds.");
  });

  it("shows a loading line while pending", async () => {
    vi.mocked(listQoeRulesApiV1QoeRulesGet).mockReturnValue(new Promise(() => {}) as never);
    renderSettings();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    vi.mocked(listQoeRulesApiV1QoeRulesGet).mockResolvedValue(errorResult(500) as never);
    renderSettings();
    expect(await screen.findByText("Could not load the thresholds.")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.mocked(listQoeRulesApiV1QoeRulesGet).mockResolvedValue(okResult([]) as never);
    renderSettings();
    expect(await screen.findByText("No rules.")).toBeInTheDocument();
  });
});
