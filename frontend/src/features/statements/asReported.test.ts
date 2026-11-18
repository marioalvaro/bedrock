import { describe, expect, it } from "vitest";

import { asReportedBalanceSheet, asReportedLine } from "@/test/classification";

import {
  bedrockRowText,
  filingOptionText,
  NOT_FOOTING_TITLE,
  periodHeader,
  periodKeys,
  toAsReportedRows,
} from "./asReported";

describe("periodHeader", () => {
  it("names an instant by its end date", () => {
    expect(periodHeader({ start: null, end: "2025-09-27" })).toBe("2025-09-27");
  });

  it("names a duration as start – end", () => {
    expect(periodHeader({ start: "2024-09-29", end: "2025-09-27" })).toBe(
      "2024-09-29 – 2025-09-27",
    );
  });
});

describe("periodKeys", () => {
  it("gives one key per face period, in the payload's order", () => {
    expect(periodKeys(asReportedBalanceSheet().periods)).toEqual(["p0", "p1"]);
    expect(periodKeys([])).toEqual([]);
  });
});

describe("bedrockRowText", () => {
  it("names the rows of a mapped line", () => {
    expect(
      bedrockRowText(
        asReportedLine({
          codes: [
            { code: "cash", label: "Cash and equivalents" },
            { code: "short_term_investments", label: "Short-term investments" },
          ],
        }),
      ),
    ).toEqual({ text: "Cash and equivalents, Short-term investments", muted: false });
  });

  it("says Other for a line in a residual, followed by the rows it names", () => {
    expect(
      bedrockRowText(asReportedLine({ kind: "other", codes: [{ code: "sga", label: "SG&A" }] })),
    ).toEqual({ text: "Other: SG&A", muted: false });
    expect(bedrockRowText(asReportedLine({ kind: "other", codes: [] }))).toEqual({
      text: "Other",
      muted: false,
    });
  });

  it("says Not classified for an open line", () => {
    expect(bedrockRowText(asReportedLine({ kind: "open", codes: [] }))).toEqual({
      text: "Not classified",
      muted: false,
    });
  });

  it("shows a muted dash for a line outside the tree that sits in a residual", () => {
    expect(bedrockRowText(asReportedLine({ kind: "other", codes: [], in_tree: false }))).toEqual({
      text: "—",
      muted: true,
    });
  });

  it("says Not classified for an open line outside the tree too", () => {
    expect(bedrockRowText(asReportedLine({ kind: "open", codes: [], in_tree: false }))).toEqual({
      text: "Not classified",
      muted: false,
    });
  });

  it("still names the row of a mapped line outside the tree", () => {
    expect(bedrockRowText(asReportedLine({ in_tree: false })).text).toBe("Cash and equivalents");
  });
});

describe("filingOptionText", () => {
  it("reads form, period end and filed date", () => {
    expect(
      filingOptionText({
        accession_no: "0000320193-25-000079",
        form: "10-K",
        filed_at: "2025-10-31",
        period_end: "2025-09-27",
      }),
    ).toBe("10-K · period ended 2025-09-27 · filed 2025-10-31");
  });
});

describe("toAsReportedRows", () => {
  it("keeps the filing's order, labels, depth and totals", () => {
    const rows = toAsReportedRows(asReportedBalanceSheet());
    expect(rows.map((r) => r.label)).toEqual([
      "Cash and cash equivalents",
      "Accounts receivable, net",
      "Vendor non-trade receivables",
      "Other current assets",
      "Total current assets",
      "Commitments and contingencies",
    ]);
    expect(rows.map((r) => r.id)).toEqual(["1", "2", "3", "4", "5", "6"]);
    expect(rows[0]).toMatchObject({ depth: 1, isTotal: false, unit: "USD" });
    expect(rows[4]).toMatchObject({ depth: 0, isTotal: true });
  });

  it("aligns each value with its face period, the API's decimal strings unchanged", () => {
    const total = toAsReportedRows(asReportedBalanceSheet())[4];
    expect(total?.values).toEqual({ p0: "147957000000", p1: "152987000000" });
    expect(toAsReportedRows(asReportedBalanceSheet())[5]?.values).toEqual({ p0: null, p1: null });
  });

  it("flags only the periods where a total does not foot", () => {
    const rows = toAsReportedRows(asReportedBalanceSheet());
    expect(rows[4]?.notFooting).toEqual({ p0: true, p1: false });
    expect(rows[0]?.notFooting).toEqual({ p0: false, p1: false }); // not checked is not a failure
    expect(NOT_FOOTING_TITLE).toBe("Does not equal the sum of its lines in this filing");
  });

  it("carries the Bedrock row text", () => {
    const rows = toAsReportedRows(asReportedBalanceSheet());
    expect(rows.map((r) => r.bedrock.text)).toEqual([
      "Cash and equivalents",
      "Receivables",
      "Not classified",
      "Other: Receivables",
      "Total current assets",
      "—",
    ]);
  });

  it("treats a line without a unit as USD", () => {
    const view = asReportedBalanceSheet({ lines: [asReportedLine({ unit: null })] });
    expect(toAsReportedRows(view)[0]?.unit).toBe("USD");
  });

  it("gives no rows for a company with no parsed filing", () => {
    expect(
      toAsReportedRows(
        asReportedBalanceSheet({ filing: null, filings: [], periods: [], lines: [], foots: null }),
      ),
    ).toEqual([]);
  });
});
