import { describe, expect, it } from "vitest";

import { noteLink } from "@/test/context";

import {
  cellNotes,
  cellTarget,
  noteIndex,
  parseSubjectKey,
  subjectKey,
  subjectNotes,
} from "./subjects";

const FY2024 = { key: "FY2024", label: "FY24", fiscal_year: 2024, fiscal_period: "FY" };

const index = noteIndex([
  noteLink({ canonical_code: "capex", fiscal_year: 2024, fiscal_period: "FY", count: 3 }),
  noteLink({ canonical_code: "capex", count: 2 }),
  noteLink({
    metric_kind: "capital",
    metric_code: "capex",
    fiscal_year: 2024,
    fiscal_period: "FY",
  }),
  noteLink({
    metric_kind: "capital",
    metric_code: "capex",
    fiscal_year: 2023,
    fiscal_period: "Q2",
  }),
  noteLink({ metric_kind: "ratio", metric_code: "roe", count: 4 }),
  noteLink({
    metric_kind: "quality",
    metric_code: "custom_3",
    fiscal_year: 2024,
    fiscal_period: "Q1",
  }),
  noteLink({ fiscal_year: 2024, fiscal_period: "FY", count: 9 }),
]);

describe("subject keys", () => {
  it("joins the kind and the code", () => {
    expect(subjectKey("line", "revenue")).toBe("line:revenue");
    expect(subjectKey("quality", "custom_3")).toBe("quality:custom_3");
  });
});

describe("parseSubjectKey", () => {
  it("splits at the first colon, so a code may contain one", () => {
    expect(parseSubjectKey("ratio:roe")).toEqual({ kind: "ratio", code: "roe" });
    expect(parseSubjectKey("line:a:b")).toEqual({ kind: "line", code: "a:b" });
  });

  it("is null for no subject or an unknown kind", () => {
    expect(parseSubjectKey("")).toBeNull();
    expect(parseSubjectKey("valuation:pe")).toBeNull();
    expect(parseSubjectKey("roe")).toBeNull();
  });
});

describe("noteIndex", () => {
  it("counts the notes of a cell by kind, code, year and period", () => {
    expect(cellNotes(index, "ratio", "roe", 2024, "FY")).toBe(0);
    expect(cellNotes(index, "capital", "capex", 2024, "FY")).toBe(1);
    expect(cellNotes(index, "capital", "capex", 2023, "Q2")).toBe(1);
    expect(cellNotes(index, "quality", "custom_3", 2024, "Q1")).toBe(1);
  });

  it("counts the notes of a subject as a whole", () => {
    expect(subjectNotes(index, "ratio", "roe")).toBe(4);
    expect(subjectNotes(index, "capital", "capex")).toBe(0);
    expect(subjectNotes(index, "ratio", "no_such")).toBe(0);
  });

  it("keeps a line and a metric with the same code apart", () => {
    expect(cellNotes(index, "line", "capex", 2024, "FY")).toBe(3);
    expect(cellNotes(index, "capital", "capex", 2024, "FY")).toBe(1);
    expect(subjectNotes(index, "line", "capex")).toBe(2);
    expect(subjectNotes(index, "capital", "capex")).toBe(0);
  });

  it("ignores period-only links and an empty list", () => {
    expect(cellNotes(index, "line", "revenue", 2024, "FY")).toBe(0);
    expect(cellNotes(noteIndex([]), "ratio", "roe", 2024, "FY")).toBe(0);
    expect(subjectNotes(noteIndex([]), "ratio", "roe")).toBe(0);
  });

  it("adds the counts of links that share a key", () => {
    const twice = noteIndex([
      noteLink({ metric_kind: "ratio", metric_code: "roe", count: 1 }),
      noteLink({ metric_kind: "ratio", metric_code: "roe", count: 2 }),
    ]);
    expect(subjectNotes(twice, "ratio", "roe")).toBe(3);
  });
});

describe("cellTarget", () => {
  it("targets a metric's FY or quarter cell", () => {
    expect(cellTarget("ratio", "roe", "Return on equity", FY2024)).toEqual({
      kind: "ratio",
      code: "roe",
      label: "Return on equity",
      period: { fiscalYear: 2024, fiscalPeriod: "FY" },
    });
    expect(
      cellTarget("quality", "accruals_ratio", "Accruals", {
        ...FY2024,
        key: "Q12024",
        fiscal_period: "Q1",
      })?.period,
    ).toEqual({ fiscalYear: 2024, fiscalPeriod: "Q1" });
  });

  it("targets nothing on a TTM column", () => {
    const ttm = { ...FY2024, key: "TTM-FY2024Q3" };
    expect(cellTarget("ratio", "roe", "Return on equity", ttm)).toBeNull();
  });
});
