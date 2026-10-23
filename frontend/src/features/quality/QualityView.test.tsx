import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createNoteApiV1CompaniesTickerNotesPost,
  getFlagsApiV1CompaniesTickerFlagsGet,
  listLinksApiV1CompaniesTickerNotesLinksGet,
  listNotesApiV1CompaniesTickerNotesGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { flags } from "@/test/analysis";
import { note, noteLink } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";

import { QualityView } from "./QualityView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getFlagsApiV1CompaniesTickerFlagsGet: vi.fn(),
  listLinksApiV1CompaniesTickerNotesLinksGet: vi.fn(),
  listNotesApiV1CompaniesTickerNotesGet: vi.fn(),
  createNoteApiV1CompaniesTickerNotesPost: vi.fn(),
}));
const links = vi.mocked(listLinksApiV1CompaniesTickerNotesLinksGet);
const listNotes = vi.mocked(listNotesApiV1CompaniesTickerNotesGet);
const createNote = vi.mocked(createNoteApiV1CompaniesTickerNotesPost);

vi.mock("./OffBalanceItems", () => ({
  OffBalanceItems: ({ ticker }: { ticker: string }) => (
    <section data-testid="off-balance" data-ticker={ticker} />
  ),
}));

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <QualityView ticker="AAPL" />
    </QueryClientProvider>,
  );
}

const cell = (row: string, period: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${period}"]`) as HTMLElement;

beforeEach(() => {
  setScale("M");
  vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(okResult(flags()) as never);
  links.mockResolvedValue(okResult([]) as never);
  listNotes.mockResolvedValue(okResult([]) as never);
  createNote.mockResolvedValue(okResult(note({ id: 9 }), 201) as never);
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("QualityView", () => {
  it("colors period cells by severity and shows formatted values", async () => {
    renderView();
    await waitFor(() => expect(cell("accruals_ratio", "FY2023")).not.toBeNull());

    expect(cell("accruals_ratio", "FY2023")).toHaveTextContent("6.2%");
    expect(cell("accruals_ratio", "FY2023")).toHaveClass("flag-warn");
    expect(cell("accruals_ratio", "FY2024")).toHaveTextContent("15.0%");
    expect(cell("accruals_ratio", "FY2024")).toHaveClass("flag-alert");
    expect(cell("cfo_to_net_income", "FY2023")).toHaveTextContent("1.2x");
    expect(cell("cfo_to_net_income", "FY2023")).not.toHaveClass("flag-warn");
    expect(cell("cfo_to_net_income", "FY2023")).not.toHaveClass("flag-alert");
    expect(cell("cfo_to_net_income", "FY2024")).toHaveTextContent("—");
    expect(cell("cfo_to_net_income", "FY2024")).not.toHaveClass("flag-warn");
    expect(cell("cfo_to_net_income", "FY2024")).not.toHaveClass("flag-alert");
    expect(cell("goodwill_impairment", "FY2024")).not.toHaveClass("flag-warn");
    expect(cell("goodwill_impairment", "FY2024")).not.toHaveClass("flag-alert");
  });

  it("shows the label, the rule text and the thresholds", async () => {
    renderView();
    expect(await screen.findByText("Accruals ratio")).toHaveAttribute("title", "accruals_ratio");
    const rule = screen.getByText("cfo ÷ net_income; null when net_income ≤ 0");
    expect(rule).toHaveAttribute("title", "cfo ÷ net_income; null when net_income ≤ 0");
    expect(screen.getByText("warn > 5% · alert > 10%")).toBeInTheDocument();
    expect(screen.getByText("warn < 0.8x · alert < 0x")).toBeInTheDocument();
    expect(screen.getByText("warn > 0%")).toBeInTheDocument();
  });

  it("shows a dash when both thresholds are null", async () => {
    const payload = flags();
    payload.rules = [{ ...payload.rules[0]!, warn: null, alert: null }];
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(okResult(payload) as never);
    renderView();
    await waitFor(() => expect(cell("accruals_ratio", "FY2023")).not.toBeNull());
    expect(
      document.querySelector('[row-id="accruals_ratio"] [col-id="thresholds"]'),
    ).toHaveTextContent("—");
  });

  it("requests annual, then TTM after toggling; the active item cannot deselect", async () => {
    const user = userEvent.setup();
    renderView();
    await screen.findByText("Accruals ratio");
    expect(getFlagsApiV1CompaniesTickerFlagsGet).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: { freq: "annual" } }),
    );

    await user.click(screen.getByRole("radio", { name: "Annual" }));
    expect(screen.getByRole("radio", { name: "Annual" })).toBeChecked();

    await user.click(screen.getByRole("radio", { name: "TTM" }));
    await waitFor(() =>
      expect(getFlagsApiV1CompaniesTickerFlagsGet).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: { freq: "ttm" } }),
      ),
    );
    await user.click(screen.getByRole("radio", { name: "TTM" }));
    expect(screen.getByRole("radio", { name: "TTM" })).toBeChecked();
  });

  it("renders OffBalanceItems for the ticker once the flags load", async () => {
    renderView();
    await screen.findByText("Accruals ratio");
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows a loading line while pending, with OffBalanceItems already present", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows an error line when the request fails and still renders OffBalanceItems", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText(/Could not load/)).toHaveClass("text-destructive");
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows the empty state and still renders OffBalanceItems", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(
      okResult(flags({ rules: [] })) as never,
    );
    renderView();
    expect(await screen.findByText("No quality flags for this company.")).toBeInTheDocument();
    expect(screen.getByTestId("off-balance")).toHaveAttribute("data-ticker", "AAPL");
  });

  it("shows the empty state when there are no periods", async () => {
    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(
      okResult(flags({ periods: [] })) as never,
    );
    renderView();
    expect(await screen.findByText("No quality flags for this company.")).toBeInTheDocument();
  });

  describe("custom rules and formula levels", () => {
    const [builtIn] = flags().rules;
    const custom = {
      ...builtIn!,
      code: "custom_sbc",
      label: "SBC creep",
      rule: "sbc / revenue",
      custom: true,
      warn: null,
      alert: "0.1",
      warn_formula: "prev(sbc / revenue) + 2%",
      alert_formula: null,
      warn_levels: ["0.041", null],
      alert_levels: [null, "0.1"],
      values: ["0.05", "0.12"],
      severity: ["warn", "alert"] as ("warn" | "alert")[],
    };
    const broken = {
      ...custom,
      code: "custom_bad",
      label: "Broken rule",
      warn_formula: "foo(",
      warn_levels: [null, null],
      alert: null,
      alert_levels: [null, null],
      values: [null, null],
      severity: [null, null],
      error: "unknown name foo",
    };

    async function renderWith(rules: (typeof builtIn)[]) {
      vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(
        okResult(flags({ rules: rules as never })) as never,
      );
      renderView();
      await waitFor(() => expect(cell(rules[0]!.code, "FY2023")).not.toBeNull());
    }

    it("tags only custom rows with a muted custom tag", async () => {
      await renderWith([builtIn, custom] as never);
      const rows = (code: string) => document.querySelector(`[row-id="${code}"]`) as HTMLElement;
      expect(within(rows("custom_sbc")).getByText("custom")).toHaveClass("text-muted-foreground");
      expect(within(rows("accruals_ratio")).queryByText("custom")).toBeNull();
    });

    it("shows a formula level as written and a number level as before", async () => {
      await renderWith([builtIn, custom] as never);
      const thresholds = (code: string) =>
        document.querySelector(`[row-id="${code}"] [col-id="thresholds"]`);
      expect(thresholds("custom_sbc")).toHaveTextContent(
        "warn > prev(sbc / revenue) + 2% · alert > 10%",
      );
      expect(thresholds("accruals_ratio")).toHaveTextContent("warn > 5% · alert > 10%");
    });

    it("gives each period's levels in the cell title, with a dash for none", async () => {
      await renderWith([builtIn, custom] as never);
      expect(cell("custom_sbc", "FY2023").querySelector("[title]")).toHaveAttribute(
        "title",
        "warn 4.1% · alert —",
      );
      expect(cell("custom_sbc", "FY2024").querySelector("[title]")).toHaveAttribute(
        "title",
        "warn — · alert 10.0%",
      );
      expect(cell("accruals_ratio", "FY2023").querySelector("[title]")).toHaveAttribute(
        "title",
        "warn 5.0% · alert 10.0%",
      );
    });

    it("shows a rule's error in the Definition cell and dashes for values", async () => {
      await renderWith([broken] as never);
      const definition = document.querySelector(
        '[row-id="custom_bad"] [col-id="rule"]',
      ) as HTMLElement;
      const error = within(definition).getByText("unknown name foo");
      expect(error).toHaveClass("text-destructive");
      expect(error).toHaveAttribute("title", "unknown name foo");
      expect(cell("custom_bad", "FY2023")).toHaveTextContent("—");
      expect(cell("custom_bad", "FY2024")).toHaveTextContent("—");
    });
  });
});

describe("QualityView notes", () => {
  const accruals = (overrides = {}) =>
    noteLink({ metric_kind: "quality", metric_code: "accruals_ratio", ...overrides });

  it("marks the cell of a rule note, keeping the severity colour", async () => {
    links.mockResolvedValue(
      okResult([
        accruals({ fiscal_year: 2023, fiscal_period: "FY" }),
        noteLink({
          metric_kind: "ratio",
          metric_code: "cfo_to_net_income",
          fiscal_year: 2024,
          fiscal_period: "FY",
        }),
      ]) as never,
    );
    renderView();
    await screen.findByText("Accruals ratio");
    await waitFor(() => expect(cell("accruals_ratio", "FY2023")).toHaveClass("has-note"));
    expect(cell("accruals_ratio", "FY2023")).toHaveClass("flag-warn");
    expect(cell("accruals_ratio", "FY2024")).not.toHaveClass("has-note");
    expect(cell("cfo_to_net_income", "FY2024")).not.toHaveClass("has-note");
  });

  it("shows a label marker for a rule with notes and opens its notes", async () => {
    links.mockResolvedValue(okResult([accruals()]) as never);
    listNotes.mockResolvedValue(
      okResult([
        note({
          id: 6,
          body_md: "Watch the working-capital build",
          canonical_code: null,
          metric_kind: "quality",
          metric_code: "accruals_ratio",
          label: "Accruals ratio",
          fiscal_year: null,
          fiscal_period: null,
        }),
      ]) as never,
    );
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Notes on Accruals ratio" }));
    expect(await screen.findByText("Watch the working-capital build")).toBeVisible();
    expect(listNotes).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: { metric_kind: "quality", metric_code: "accruals_ratio" },
    });
  });

  it("opens a cell's notes on a click and adds a note linked to the rule and period", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 23, 22, 30));
    renderView();
    await waitFor(() => expect(cell("accruals_ratio", "FY2024")).not.toBeNull());
    await userEvent.click(cell("accruals_ratio", "FY2024"));
    const sheet = await screen.findByRole("dialog");
    expect(listNotes).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      query: {
        metric_kind: "quality",
        metric_code: "accruals_ratio",
        fiscal_year: 2024,
        fiscal_period: "FY",
      },
    });
    await userEvent.click(await within(sheet).findByRole("button", { name: "Add note" }));
    expect(within(sheet).getByText("Linked to Accruals ratio · FY2024")).toBeVisible();
    await userEvent.type(within(sheet).getByLabelText("Note"), "Alert: one-off");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(createNote).toHaveBeenCalledTimes(1));
    expect(createNote).toHaveBeenCalledWith({
      path: { ticker: "AAPL" },
      body: {
        body_md: "Alert: one-off",
        canonical_code: null,
        metric_kind: "quality",
        metric_code: "accruals_ratio",
        fiscal_year: 2024,
        fiscal_period: "FY",
        note_date: "2026-10-23",
      },
    });
  });

  it("opens no sheet from the rule, definition or thresholds cells or a TTM column", async () => {
    renderView();
    await waitFor(() => expect(cell("accruals_ratio", "rule")).not.toBeNull());
    for (const col of ["label", "rule", "thresholds"]) {
      await userEvent.click(cell("accruals_ratio", col));
    }
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    vi.mocked(getFlagsApiV1CompaniesTickerFlagsGet).mockResolvedValue(
      okResult(
        flags({
          freq: "ttm",
          periods: flags().periods.map((p) => ({ ...p, key: `TTM-${p.key}` })),
        }),
      ) as never,
    );
    await userEvent.click(screen.getByRole("radio", { name: "TTM" }));
    await userEvent.click(await waitFor(() => cell("accruals_ratio", "TTM-FY2024")));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the grid without markers when the links cannot load", async () => {
    links.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("Accruals ratio")).toBeVisible();
    expect(document.querySelector(".has-note")).toBeNull();
  });
});
