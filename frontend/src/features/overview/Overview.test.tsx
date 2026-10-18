import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete,
  getMappingGapsApiV1CompaniesTickerMappingGapsGet,
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet,
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { adjustment, corporateActions } from "@/test/adjustments";
import { companyItem, mappingGaps } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import { Overview } from "./Overview";

vi.mock("@/api/generated/sdk.gen", () => ({
  getMappingGapsApiV1CompaniesTickerMappingGapsGet: vi.fn(),
  listAdjustmentsApiV1CompaniesTickerAdjustmentsGet: vi.fn(),
  listCorporateActionsApiV1CompaniesTickerCorporateActionsGet: vi.fn(),
  deleteAdjustmentApiV1CompaniesTickerAdjustmentsAdjustmentIdDelete: vi.fn(),
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
  remove.mockResolvedValue(okResult(null, 204) as never);
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

  it("says so when there are no gaps", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      okResult({ missing_items: [], unmapped_concepts: [] }) as never,
    );
    renderOverview();

    expect(await screen.findByText("No missing items.")).toBeInTheDocument();
    expect(screen.getByText("No unmapped concepts.")).toBeInTheDocument();
  });

  it("shows an error when the gaps fail to load, and keeps the key stats", async () => {
    vi.mocked(getMappingGapsApiV1CompaniesTickerMappingGapsGet).mockResolvedValue(
      errorResult(500) as never,
    );
    renderOverview();

    expect(await screen.findByText("Could not load the data gaps.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Key stats" })).toBeInTheDocument();
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
