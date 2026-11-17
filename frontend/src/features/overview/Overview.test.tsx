import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete,
  getClassificationsOfApiV1CompaniesTickerClassificationsGet,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  getStatusApiV1ClassificationStatusGet,
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet,
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet,
  listImportsApiV1CompaniesTickerImportsGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { adjustment, corporateActions } from "@/test/adjustments";
import { classifications, classifierStatus, noClassifierStatus } from "@/test/classification";
import type { MappingGapsOut } from "@/api/generated/types.gen";
import { companyItem, mappingGaps } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import { Overview } from "./Overview";

vi.mock("@/api/generated/sdk.gen", () => ({
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet: vi.fn(),
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet: vi.fn(),
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete: vi.fn(),
  listImportsApiV1CompaniesTickerImportsGet: vi.fn(),
  importStatementsApiV1CompaniesTickerImportsPost: vi.fn(),
  deleteImportApiV1CompaniesTickerImportsImportIdDelete: vi.fn(),
  getStatusApiV1ClassificationStatusGet: vi.fn(),
  getClassificationsOfApiV1CompaniesTickerClassificationsGet: vi.fn(),
  startRunApiV1CompaniesTickerClassificationsRunPost: vi.fn(),
  decideApiV1CompaniesTickerClassificationsClassificationIdPut: vi.fn(),
  answerApiV1CompaniesTickerClassificationsPut: vi.fn(),
  setModeApiV1CompaniesTickerClassificationModePut: vi.fn(),
}));

const listAdjustments = vi.mocked(listAdjustmentsApiV1CompaniesTickerAdjustmentsGet);
const listActions = vi.mocked(listCorporateActionsApiV1CompaniesTickerCorporateActionsGet);
const remove = vi.mocked(deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete);

beforeEach(() => {
  vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
    okResult(mappingGaps()) as never,
  );
  listAdjustments.mockResolvedValue(okResult([]) as never);
  listActions.mockResolvedValue(okResult([]) as never);
  vi.mocked(listImportsApiV1CompaniesTickerImportsGet).mockResolvedValue(okResult([]) as never);
  remove.mockResolvedValue(okResult(null, 204) as never);
  // The classify panel (features/classification, tested on its own): no key by default.
  vi.mocked(getStatusApiV1ClassificationStatusGet).mockResolvedValue(
    okResult(noClassifierStatus()) as never,
  );
  vi.mocked(getClassificationsOfApiV1CompaniesTickerClassificationsGet).mockResolvedValue(
    okResult(classifications()) as never,
  );
});

function renderOverview() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <Overview company={companyItem()} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
  setScale("M");
});

describe("Overview", () => {
  it("shows the key stats, with a dash for one that is missing", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    renderOverview();

    const stats = await screen.findByRole("region", { name: "Key stats" });
    expect(within(stats).getByText("Price")).toBeInTheDocument();
    expect(within(stats).getByText("231.40")).toBeInTheDocument();
    expect(within(stats).getByText("3.5T")).toBeInTheDocument();
    expect(within(stats).getByText("34.2x")).toBeInTheDocument();
    expect(within(stats).getByText("5.1%")).toBeInTheDocument();
    expect(within(stats).getByText("—")).toBeInTheDocument();
  });

  it("lists the missing items with their statement and fiscal years", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    renderOverview();

    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    const row = (await within(gaps).findByText("Short-term debt")).closest("tr") as HTMLElement;
    expect(within(row).getByText("BS")).toBeInTheDocument();
    expect(within(row).getByText("FY2008, FY2009, FY2010")).toBeInTheDocument();
  });

  it("lists the unmapped concepts with their latest value", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    renderOverview();

    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    const row = (
      await within(gaps).findByText("us-gaap:IncreaseDecreaseInOtherOperatingCapitalNet")
    ).closest("tr") as HTMLElement;
    expect(within(row).getByText("(1,200)")).toBeInTheDocument();
    expect(within(row).getByText("2025-09-27")).toBeInTheDocument();
  });

  it("shows the suggested codes of an unmapped concept, and nothing where there is none", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult(mappingGaps()) as never,
    );
    renderOverview();

    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    expect(
      await within(gaps).findByRole("columnheader", { name: "Suggested" }),
    ).toBeInTheDocument();
    const suggested = (await within(gaps).findByText("us-gaap:LongTermDebtCurrent")).closest(
      "tr",
    ) as HTMLElement;
    expect(within(suggested).getByText("short_term_debt, long_term_debt")).toBeInTheDocument();
    // the concept with a suggestion is listed first
    const rows = within(gaps).getAllByRole("row");
    expect(rows.findIndex((r) => r === suggested)).toBeLessThan(
      rows.findIndex((r) => within(r).queryByText(/IncreaseDecrease/) !== null),
    );
  });

  describe("classified concepts", () => {
    async function openGaps() {
      vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
        okResult(mappingGaps()) as never,
      );
      renderOverview();
      return screen.findByRole("region", { name: "Data gaps" });
    }

    it("counts only the unclassified concepts and hides the classified by default", async () => {
      const gaps = await openGaps();

      expect(
        await within(gaps).findByText(/Unmapped concepts in the latest 10-K \(2\)/),
      ).toBeVisible();
      expect(within(gaps).getByText("us-gaap:LongTermDebtCurrent")).toBeInTheDocument();
      expect(
        within(gaps).queryByText("us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"),
      ).not.toBeInTheDocument();
      expect(within(gaps).queryByText("us-gaap:Land")).not.toBeInTheDocument();
      expect(within(gaps).getByRole("button", { name: "Show classified (2)" })).toBeInTheDocument();
    });

    it("shows each classified concept with its type and reason when asked", async () => {
      const gaps = await openGaps();

      await userEvent.click(
        await within(gaps).findByRole("button", { name: "Show classified (2)" }),
      );

      const ladder = (
        await within(gaps).findByText(
          "us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
        )
      ).closest("tr") as HTMLElement;
      expect(within(ladder).getByText("disclosure")).toBeInTheDocument();
      expect(within(ladder).getByText("debt maturity schedule")).toBeInTheDocument();
      const land = within(gaps).getByText("us-gaap:Land").closest("tr") as HTMLElement;
      expect(within(land).getByText("component")).toBeInTheDocument();
      expect(within(land).getByText("ppe_net")).toBeInTheDocument();
      expect(
        within(land).getByText("gross property component of the PP&E note"),
      ).toBeInTheDocument();
      // the open concepts stay listed, and the button now hides the classified again
      expect(within(gaps).getByText("us-gaap:LongTermDebtCurrent")).toBeInTheDocument();
      await userEvent.click(within(gaps).getByRole("button", { name: "Hide classified (2)" }));
      expect(within(gaps).queryByText("us-gaap:Land")).not.toBeInTheDocument();
    });

    it("has no toggle when nothing is classified", async () => {
      const open = mappingGaps().unmapped_concepts.filter((c) => c.classification === null);
      vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
        okResult({ ...mappingGaps(), missing_items: [], unmapped_concepts: open }) as never,
      );
      renderOverview();

      const gaps = await screen.findByRole("region", { name: "Data gaps" });
      expect(await within(gaps).findByText("us-gaap:LongTermDebtCurrent")).toBeInTheDocument();
      expect(within(gaps).queryByRole("button", { name: /classified/ })).not.toBeInTheDocument();
    });

    it("says nothing is left to classify when every concept has a verdict", async () => {
      const done = mappingGaps().unmapped_concepts.filter((c) => c.classification !== null);
      vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
        okResult({ ...mappingGaps(), missing_items: [], unmapped_concepts: done }) as never,
      );
      renderOverview();

      expect(await screen.findByText("No unclassified concepts.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Show classified (2)" })).toBeInTheDocument();
    });
  });

  it("says so when there are no gaps", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult({
        ...mappingGaps(),
        missing_items: [],
        unmapped_concepts: [],
        rule_warnings: [],
      }) as never,
    );
    renderOverview();

    expect(await screen.findByText("No missing items.")).toBeInTheDocument();
    expect(screen.getByText("No unmapped concepts.")).toBeInTheDocument();
  });

  describe("coverage and rule warnings", () => {
    async function gapsRegion() {
      renderOverview();
      return screen.findByRole("region", { name: "Data gaps" });
    }

    it("shows the coverage of every statement and frequency", async () => {
      const gaps = await gapsRegion();

      const table = await within(gaps).findByRole("table", { name: "Coverage" });
      const income = within(table)
        .getAllByText("Income statement")[0]!
        .closest("tr") as HTMLElement;
      expect(within(income).getByText("Annual")).toBeInTheDocument();
      expect(within(income).getByText("95.0% (applicable 95.0%)")).toBeInTheDocument();
      expect(within(income).getByText("95 / 100")).toBeInTheDocument();
      const quarterly = within(table)
        .getByText("88.8% (applicable 88.8%)")
        .closest("tr") as HTMLElement;
      expect(within(quarterly).getByText("Quarterly")).toBeInTheDocument();
      expect(within(table).getByText("Balance sheet")).toBeInTheDocument();
      expect(within(table).getByText("75.0% (applicable 75.0%)")).toBeInTheDocument();
    });

    it("breaks the empty cells down by cause and the filled ones by provenance", async () => {
      const gaps = await gapsRegion();

      const table = await within(gaps).findByRole("table", { name: "Coverage" });
      const headers = within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent);
      expect(headers).toEqual([
        "Statement",
        "Frequency",
        "Coverage",
        "Filled",
        "Inferred 0",
        "Approximated",
        "No filing data",
        "Not applicable",
        "Included in",
        "Structural",
        "Rule rejected",
        "Annual only",
        "Unclassified line",
        "Not reported",
      ]);
      const quarterly = within(table)
        .getByText("88.8% (applicable 88.8%)")
        .closest("tr") as HTMLElement;
      const cells = within(quarterly)
        .getAllByRole("cell")
        .map((c) => c.textContent);
      expect(cells.slice(4)).toEqual(["12", "8", "17", "0", "0", "4", "0", "0", "0", "39"]);
    });

    it("shows a dash where a statement has nothing to cover", async () => {
      const empty = mappingGaps();
      empty.coverage = [
        { ...empty.coverage[0]!, cells: 0, filled: 0, fraction: null, fraction_applicable: null },
      ];
      vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
        okResult(empty) as never,
      );
      const gaps = await gapsRegion();

      const table = await within(gaps).findByRole("table", { name: "Coverage" });
      const row = within(table).getByText("Income statement").closest("tr") as HTMLElement;
      expect(within(row).getByText("— (applicable —)")).toBeInTheDocument();
      expect(within(row).getByText("0 / 0")).toBeInTheDocument();
    });

    it("shows strict and applicable coverage and names what applicable leaves out", async () => {
      const gaps0 = mappingGaps();
      gaps0.coverage = [
        {
          ...gaps0.coverage[0]!,
          fraction: "0.800000",
          fraction_applicable: "0.920000",
          empty_by_cause: {
            ...gaps0.coverage[0]!.empty_by_cause,
            no_filing_data: 4,
            not_applicable: 9,
            included_in: 2,
          },
        },
      ];
      vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
        okResult(gaps0) as never,
      );
      const gaps = await gapsRegion();

      const table = await within(gaps).findByRole("table", { name: "Coverage" });
      const coverage = within(table).getByText("80.0% (applicable 92.0%)");
      expect(coverage).toHaveAttribute(
        "title",
        "Both leave out No filing data (4). Applicable also leaves out Not applicable (9) and " +
          "Included in (2): cells that cannot hold a value.",
      );
    });

    it("explains every cause of an empty cell in one line", async () => {
      const gaps = await gapsRegion();

      const causes = await within(gaps).findByRole("list", { name: "Empty-cell causes" });
      const terms = within(causes)
        .getAllByRole("term")
        .map((t) => t.textContent);
      expect(terms).toEqual([
        "No filing data",
        "Not applicable",
        "Included in",
        "Structural",
        "Rule rejected",
        "Annual only",
        "Unclassified line",
        "Not reported",
      ]);
      expect(within(causes).getAllByRole("definition")).toHaveLength(8);
      expect(
        within(causes).getByText(/inside a combined line/, { selector: "dd" }),
      ).toBeInTheDocument();
    });

    it("lists the rule warnings with line, period, value and reason", async () => {
      const gaps = await gapsRegion();

      const warnings = await within(gaps).findByRole("table", { name: "Rule warnings" });
      const fx = within(warnings).getByText("FX effect on cash").closest("tr") as HTMLElement;
      expect(within(fx).getByText("cash_rollforward")).toBeInTheDocument();
      expect(within(fx).getByText("FY2020")).toBeInTheDocument();
      expect(within(fx).getByText("(1,250)")).toBeInTheDocument();
      expect(within(fx).getByText("exceeds 5% of the largest other term")).toBeInTheDocument();
      const eps = within(warnings).getByText("Diluted EPS").closest("tr") as HTMLElement;
      expect(within(eps).getByText("Q4 FY2023")).toBeInTheDocument();
      expect(within(eps).getByText("2.51")).toBeInTheDocument();
      expect(screen.getByText("Rule warnings (3)")).toBeInTheDocument();
    });

    it("shows a dash for a warning with no value (a guard refused to solve)", async () => {
      const gaps = await gapsRegion();

      const warnings = await within(gaps).findByRole("table", { name: "Rule warnings" });
      const row = within(warnings)
        .getByText("Non-controlling interest")
        .closest("tr") as HTMLElement;
      expect(within(row).getByText("—")).toBeInTheDocument();
      expect(within(row).getByText("operands come from different filings")).toBeInTheDocument();
    });

    it("says so when there are no warnings or no statement data", async () => {
      vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
        okResult({ ...mappingGaps(), coverage: [], rule_warnings: [] }) as never,
      );
      const gaps = await gapsRegion();

      expect(await within(gaps).findByText("No rule warnings.")).toBeInTheDocument();
      expect(within(gaps).getByText("No statement data yet.")).toBeInTheDocument();
      expect(within(gaps).queryByRole("table", { name: "Coverage" })).not.toBeInTheDocument();
    });
  });

  it("shows an error when the gaps fail to load, and keeps the key stats", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      errorResult(500) as never,
    );
    renderOverview();

    expect(await screen.findByText("Could not load the data gaps.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Key stats" })).toBeInTheDocument();
  });

  it("shows an error for a gaps report without coverage or warnings (an old API)", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult({ missing_items: [], unmapped_concepts: [] }) as never,
    );
    renderOverview();

    expect(await screen.findByText("Could not load the data gaps.")).toBeInTheDocument();
  });

  it("shows an error for a 200 that is not a gaps report (G2/G4)", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult("<!doctype html>") as never,
    );
    renderOverview();

    expect(await screen.findByText("Could not load the data gaps.")).toBeInTheDocument();
  });

  describe("Adjustments", () => {
    it("lists an adjustment's period, line, amount in scale, category and reason", async () => {
      listAdjustments.mockResolvedValue(okResult([adjustment()]) as never);
      renderOverview();

      const section = await screen.findByRole("region", { name: "Adjustments" });
      expect(
        await within(section).findByRole("columnheader", { name: "Amount (USD millions)" }),
      ).toBeInTheDocument();
      const row = (await within(section).findByText("Legal settlement")).closest(
        "tr",
      ) as HTMLElement;
      expect(within(row).getByText("FY2024")).toBeInTheDocument();
      expect(within(row).getByText("SG&A")).toBeInTheDocument();
      expect(within(row).getByText("(25)")).toBeInTheDocument();
      expect(within(row).getByText("one-off")).toBeInTheDocument();
    });

    it("labels a quarter adjustment with its quarter", async () => {
      listAdjustments.mockResolvedValue(okResult([adjustment({ fiscal_period: "Q2" })]) as never);
      renderOverview();

      const section = await screen.findByRole("region", { name: "Adjustments" });
      expect(await within(section).findByText("Q2 FY2024")).toBeInTheDocument();
    });

    it("shows the amount in the page scale", async () => {
      setScale("B");
      listAdjustments.mockResolvedValue(okResult([adjustment({ amount: "-2500000000" })]) as never);
      renderOverview();

      const section = await screen.findByRole("region", { name: "Adjustments" });
      expect(
        await within(section).findByRole("columnheader", { name: "Amount (USD billions)" }),
      ).toBeInTheDocument();
      expect(await within(section).findByText("(2.5)")).toBeInTheDocument();
    });

    it("says so when there are none", async () => {
      renderOverview();
      expect(await screen.findByText("No adjustments.")).toBeInTheDocument();
    });

    it("shows an error when the list fails", async () => {
      listAdjustments.mockResolvedValue(errorResult(500) as never);
      renderOverview();
      expect(await screen.findByText("Could not load the adjustments.")).toBeInTheDocument();
    });

    it("shows an error for a 200 with a non-array body (G4)", async () => {
      listAdjustments.mockResolvedValue(okResult("<!doctype html>") as never);
      renderOverview();
      expect(await screen.findByText("Could not load the adjustments.")).toBeInTheDocument();
    });

    it("deletes only after the confirmation", async () => {
      listAdjustments.mockResolvedValue(okResult([adjustment({ id: 7 })]) as never);
      renderOverview();
      const button = { name: "Delete adjustment Legal settlement" };
      await userEvent.click(await screen.findByRole("button", button));
      const dialog = await screen.findByRole("alertdialog");
      expect(within(dialog).getByText("Delete this adjustment?")).toBeInTheDocument();
      await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(remove).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole("button", button));
      await userEvent.click(
        within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
      );
      await waitFor(() =>
        expect(remove).toHaveBeenCalledWith({ path: { ticker: "AAPL", adjustment_id: 7 } }),
      );
    });

    it("removes the row after a confirmed delete", async () => {
      listAdjustments
        .mockResolvedValueOnce(okResult([adjustment({ id: 7 })]) as never)
        .mockResolvedValue(okResult([]) as never);
      renderOverview();
      const section = await screen.findByRole("region", { name: "Adjustments" });
      await userEvent.click(
        await within(section).findByRole("button", { name: "Delete adjustment Legal settlement" }),
      );
      await userEvent.click(
        within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
      );
      expect(await within(section).findByText("No adjustments.")).toBeInTheDocument();
      expect(within(section).queryByText("Legal settlement")).not.toBeInTheDocument();
    });

    it("shows Loading… while the adjustments are pending", () => {
      listAdjustments.mockReturnValue(new Promise(() => {}) as never);
      renderOverview();
      const section = screen.getByRole("region", { name: "Adjustments" });
      expect(within(section).getByText("Loading…")).toBeInTheDocument();
    });

    it("shows the API detail when the delete fails", async () => {
      remove.mockResolvedValue(errorResult(404, { detail: "Adjustment not found" }) as never);
      listAdjustments.mockResolvedValue(okResult([adjustment({ id: 7 })]) as never);
      renderOverview();
      await userEvent.click(
        await screen.findByRole("button", { name: "Delete adjustment Legal settlement" }),
      );
      await userEvent.click(
        within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent("Adjustment not found");
    });
  });

  describe("Corporate actions", () => {
    it("lists the splits oldest first, with the reverse split as 1-for-10", async () => {
      listActions.mockResolvedValue(okResult(corporateActions()) as never);
      renderOverview();

      const section = await screen.findByRole("region", { name: "Corporate actions" });
      expect(await within(section).findByText("7-for-1")).toBeInTheDocument();
      const rows = within(section)
        .getAllByRole("row")
        .map((r) => r.textContent);
      expect(rows.some((t) => t === "2014-06-097-for-1")).toBe(true);
      expect(rows.some((t) => t === "2020-08-314-for-1")).toBe(true);
      expect(rows.some((t) => t === "2023-05-011-for-10")).toBe(true);
      expect(rows.findIndex((t) => t?.startsWith("2014"))).toBeLessThan(
        rows.findIndex((t) => t?.startsWith("2020")),
      );
    });

    it("says so when there are none", async () => {
      renderOverview();
      expect(await screen.findByText("No corporate actions.")).toBeInTheDocument();
    });

    it("shows Loading… while the corporate actions are pending", () => {
      listActions.mockReturnValue(new Promise(() => {}) as never);
      renderOverview();
      const section = screen.getByRole("region", { name: "Corporate actions" });
      expect(within(section).getByText("Loading…")).toBeInTheDocument();
    });

    it("shows an error when the list fails", async () => {
      listActions.mockResolvedValue(errorResult(500) as never);
      renderOverview();
      expect(await screen.findByText("Could not load the corporate actions.")).toBeInTheDocument();
    });

    it("shows an error for a 200 with a non-array body (G4)", async () => {
      listActions.mockResolvedValue(okResult({ splits: [] }) as never);
      renderOverview();
      expect(await screen.findByText("Could not load the corporate actions.")).toBeInTheDocument();
    });
  });
});

describe("Overview import", () => {
  it("opens the import sheet from the Data gaps section", async () => {
    renderOverview();
    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    await userEvent.click(within(gaps).getByRole("button", { name: "Import" }));
    expect(await screen.findByText("Import statements")).toBeVisible();
  });
});

describe("lines to classify (M7b S8)", () => {
  function withLines(lines: MappingGapsOut["unclassified_lines"]) {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult({ ...mappingGaps(), unclassified_lines: lines }) as never,
    );
  }

  it("lists the face lines nobody classified, with what to do about them", async () => {
    withLines([
      {
        statement: "CF",
        taxonomy: "msft",
        concept: "DepreciationAmortizationAndOther",
        label: "Depreciation, amortization, and other",
        latest_value: "22287000000",
        latest_period_end: "2024-06-30",
        filings: ["0000950170-24-087843", "0000950170-24-118967"],
      },
    ]);
    renderOverview();

    const table = await screen.findByRole("table", { name: "Lines to classify" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Statement",
      "Label",
      "Concept",
      "Latest value (USD millions)",
      "Period end",
      "Filings",
    ]);
    const row = within(table)
      .getByText("Depreciation, amortization, and other")
      .closest("tr") as HTMLElement;
    expect(within(row).getByText("Cash flow")).toBeInTheDocument();
    expect(within(row).getByText("msft:DepreciationAmortizationAndOther")).toBeInTheDocument();
    expect(within(row).getByText("22,287")).toBeInTheDocument();
    expect(within(row).getByText("2024-06-30")).toBeInTheDocument();
    expect(within(row).getByText("0000950170-24-087843, 0000950170-24-118967")).toBeInTheDocument();
    expect(screen.getByText("Lines to classify (1)")).toBeInTheDocument();
    expect(
      screen.getByText("Map it in the company's override file, or list it under other_lines."),
    ).toBeInTheDocument();
  });

  it("says no classifier is configured, and offers no classify button (M7d S5)", async () => {
    withLines([]);
    renderOverview();

    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    expect(
      await within(gaps).findByText("No classifier is configured. See Settings."),
    ).toBeInTheDocument();
    expect(within(gaps).queryByRole("button", { name: /^Classify/ })).not.toBeInTheDocument();
  });

  it("offers the classify panel when a classifier has a key (M7d S5)", async () => {
    vi.mocked(getStatusApiV1ClassificationStatusGet).mockResolvedValue(
      okResult(classifierStatus()) as never,
    );
    renderOverview();

    const gaps = await screen.findByRole("region", { name: "Data gaps" });
    expect(
      await within(gaps).findByRole("button", { name: "Classify 2 lines" }),
    ).toBeInTheDocument();
    expect(within(gaps).getByText("Marketing expense")).toBeInTheDocument();
  });

  it("says so when every face line is classified", async () => {
    withLines([]);
    renderOverview();

    expect(await screen.findByText("No lines to classify.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Lines to classify" })).not.toBeInTheDocument();
  });
});
