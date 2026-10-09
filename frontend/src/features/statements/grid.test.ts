import { describe, expect, it } from "vitest";

import { balanceStatement, incomeStatement } from "@/test/statements";

import { canExplain, csvLabel, rowUnitHint, toGridRows } from "./grid";

const OFF = { yoy: false, commonSize: false };

describe("toGridRows", () => {
  it("makes one row per line item, keyed by period", () => {
    const rows = toGridRows(incomeStatement(), OFF);

    expect(rows.map((row) => row.id)).toEqual(["revenue", "cost_of_revenue", "eps_diluted"]);
    expect(rows[0]).toMatchObject({
      code: "revenue",
      label: "Revenue",
      unit: "USD",
      depth: 0,
      kind: "line",
      values: { FY2023: "383285000000", FY2024: "391035000000" },
    });
  });

  it("carries provenance per period", () => {
    const [revenue] = toGridRows(incomeStatement(), OFF);

    expect(revenue?.provenance).toEqual({ FY2023: "reported", FY2024: "derived" });
  });

  it("drops line items with no value in any period", () => {
    const rows = toGridRows(incomeStatement(), OFF);

    expect(rows.find((row) => row.code === "rnd")).toBeUndefined();
  });

  it("inserts a YoY sub-row under each line when toggled", () => {
    const rows = toGridRows(incomeStatement(), { yoy: true, commonSize: false });

    expect(rows.map((row) => row.id)).toEqual([
      "revenue",
      "revenue:yoy",
      "cost_of_revenue",
      "cost_of_revenue:yoy",
      "eps_diluted",
      "eps_diluted:yoy",
    ]);
    const yoy = rows[1];
    expect(yoy).toMatchObject({
      kind: "yoy",
      label: "YoY",
      unit: "%",
      depth: 1,
      values: { FY2023: null, FY2024: "0.020219" },
    });
  });

  it("inserts a common-size sub-row only for lines that have one", () => {
    const rows = toGridRows(incomeStatement(), { yoy: false, commonSize: true });

    expect(rows.map((row) => row.id)).toEqual([
      "revenue",
      "revenue:common_size",
      "cost_of_revenue",
      "cost_of_revenue:common_size",
      "eps_diluted",
    ]);
    expect(rows[3]?.values).toEqual({ FY2023: "0.558700", FY2024: "0.537900" });
  });

  it("puts YoY before common-size when both are on", () => {
    const rows = toGridRows(incomeStatement(), { yoy: true, commonSize: true });

    expect(rows.slice(0, 3).map((row) => row.id)).toEqual([
      "revenue",
      "revenue:yoy",
      "revenue:common_size",
    ]);
  });

  it("indents a sub-row one level below its line", () => {
    const rows = toGridRows(incomeStatement(), { yoy: true, commonSize: false });

    expect(rows.find((row) => row.id === "cost_of_revenue:yoy")?.depth).toBe(2);
  });

  it("appends the balance check row for a balance sheet", () => {
    const rows = toGridRows(balanceStatement(), OFF);

    const check = rows.at(-1);
    expect(check).toMatchObject({
      id: "balance_check",
      kind: "balance_check",
      label: "Balance check",
      depth: 0,
      values: { FY2023: "0", FY2024: "-2000000" },
      ok: { FY2023: true, FY2024: false },
    });
  });

  it("has no balance check row for other statements", () => {
    expect(toGridRows(incomeStatement(), OFF).some((row) => row.kind === "balance_check")).toBe(
      false,
    );
  });
});

describe("canExplain", () => {
  const [revenue] = toGridRows(incomeStatement(), { yoy: true, commonSize: false });
  const yoy = toGridRows(incomeStatement(), { yoy: true, commonSize: false })[1];
  const annual = incomeStatement().periods[1]!;

  it("allows a value cell of a line item", () => {
    expect(canExplain(revenue!, annual)).toBe(true);
  });

  it("refuses sub-rows", () => {
    expect(canExplain(yoy!, annual)).toBe(false);
  });

  it("refuses an empty cell", () => {
    const empty = { ...revenue!, values: { ...revenue!.values, FY2024: null } };

    expect(canExplain(empty, annual)).toBe(false);
  });

  it("refuses a TTM column, which the cell endpoint does not cover", () => {
    expect(canExplain(revenue!, { ...annual, key: "TTM-FY2024Q3" })).toBe(false);
  });

  it("refuses the balance check row", () => {
    const check = toGridRows(balanceStatement(), OFF).at(-1)!;
    expect(canExplain(check, annual)).toBe(false);
  });
});

describe("rowUnitHint", () => {
  it("marks per-share and share-count rows, not USD ones", () => {
    expect(rowUnitHint("USD", "M")).toBeNull();
    expect(rowUnitHint("USD/shares", "M")).toBe("USD/share");
    expect(rowUnitHint("shares", "M")).toBe("shares millions");
    expect(rowUnitHint("%", "M")).toBeNull();
  });
});

describe("csvLabel", () => {
  it("names a sub-row after its line item, so the export is self-describing", () => {
    const rows = toGridRows(incomeStatement(), { yoy: true, commonSize: true });

    expect(csvLabel(rows[0]!)).toBe("Revenue");
    expect(csvLabel(rows[1]!)).toBe("Revenue YoY");
    expect(csvLabel(rows[2]!)).toBe("Revenue Common size");
  });
});
