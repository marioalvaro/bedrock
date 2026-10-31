import { describe, expect, it } from "vitest";

import { driverGrid, driverRow } from "@/test/scenarios";

import {
  driverEdit,
  driverReset,
  forecastCell,
  formatDriverOffset,
  formatDriverValue,
  historyLabel,
  forecastLabel,
  parseDriverText,
  toDriverRows,
  toDriverText,
} from "./driverCells";

describe("column labels", () => {
  it("marks actual years A and forecast years E with two digits", () => {
    expect(historyLabel(2024)).toBe("FY24A");
    expect(forecastLabel(2027)).toBe("FY27E");
    expect(forecastLabel(2100)).toBe("FY00E");
  });
});

describe("formatDriverValue", () => {
  it("shows pct as a percent with 1 decimal, negatives in parentheses", () => {
    expect(formatDriverValue("0.0534", "pct", "M")).toBe("5.3%");
    expect(formatDriverValue("-0.028", "pct", "M")).toBe("(2.8%)");
  });

  it("shows days with 1 decimal", () => {
    expect(formatDriverValue("61.25", "days", "M")).toBe("61.3");
    expect(formatDriverValue("60", "days", "M")).toBe("60.0");
  });

  it("shows USD in the page scale", () => {
    expect(formatDriverValue("90711000000", "USD", "M")).toBe("90,711");
    expect(formatDriverValue("90711000000", "USD", "B")).toBe("90.7");
  });

  it("shows a missing value as a dash", () => {
    expect(formatDriverValue(null, "pct", "M")).toBe("—");
  });
});

describe("formatDriverOffset", () => {
  it("shows a pct offset in signed points", () => {
    expect(formatDriverOffset("0.03", "pct", "M")).toBe("+3.0 pts");
    expect(formatDriverOffset("-0.05", "pct", "M")).toBe("-5.0 pts");
  });

  it("shows a days offset in signed days", () => {
    expect(formatDriverOffset("5", "days", "M")).toBe("+5.0 days");
    expect(formatDriverOffset("-2.5", "days", "M")).toBe("-2.5 days");
  });

  it("shows a USD offset signed in the page scale", () => {
    expect(formatDriverOffset("2000000000", "USD", "M")).toBe("+2,000");
    expect(formatDriverOffset("-2000000000", "USD", "B")).toBe("-2.0");
  });

  it("gives a zero offset no sign", () => {
    expect(formatDriverOffset("0", "pct", "M")).toBe("0.0 pts");
  });
});

describe("parseDriverText", () => {
  it("reads pct as a percent, with or without '%'", () => {
    expect(parseDriverText("5", "pct", "M")).toBe("0.05");
    expect(parseDriverText("5%", "pct", "M")).toBe("0.05");
    expect(parseDriverText(" 12.5 % ", "pct", "M")).toBe("0.125");
    expect(parseDriverText("-2.5", "pct", "M")).toBe("-0.025");
    expect(parseDriverText("(2.5)", "pct", "M")).toBe("-0.025");
  });

  it("accepts a leading '+', as an offset is typed", () => {
    expect(parseDriverText("+3", "pct", "M")).toBe("0.03");
    expect(parseDriverText("+5", "days", "M")).toBe("5");
  });

  it("reads days as a plain number", () => {
    expect(parseDriverText("45.5", "days", "M")).toBe("45.5");
  });

  it("reads USD in each page scale", () => {
    expect(parseDriverText("2", "USD", "B")).toBe("2000000000");
    expect(parseDriverText("1,500", "USD", "M")).toBe("1500000000");
    expect(parseDriverText("25", "USD", "K")).toBe("25000");
  });

  it("rejects text that is not a number", () => {
    expect(parseDriverText("abc", "pct", "M")).toBeNull();
    expect(parseDriverText("1e5", "days", "M")).toBeNull();
    expect(parseDriverText("", "USD", "M")).toBeNull();
    expect(parseDriverText("+", "pct", "M")).toBeNull();
    expect(parseDriverText("++3", "pct", "M")).toBeNull();
  });
});

describe("toDriverText", () => {
  it("is the editor's text, the inverse of parseDriverText", () => {
    expect(toDriverText("0.0534", "pct", "M")).toBe("5.34");
    expect(toDriverText("60.5", "days", "M")).toBe("60.5");
    expect(toDriverText("2000000000", "USD", "B")).toBe("2");
    for (const [text, unit] of [
      ["5.34", "pct"],
      ["-2.5", "days"],
      ["1234.5", "USD"],
    ] as const) {
      expect(toDriverText(parseDriverText(text, unit, "M")!, unit, "M")).toBe(text);
    }
  });
});

describe("toDriverRows", () => {
  it("puts a heading row before each group, in payload order", () => {
    const rows = toDriverRows(driverGrid());
    expect(rows.map((row) => row.id)).toEqual([
      "group:Revenue",
      "driver:revenue_growth",
      "group:Costs",
      "driver:gross_margin",
      "group:Below the line",
      "driver:tax_rate",
      "group:Working capital",
      "driver:receivable_days",
      "group:Shareholders",
      "driver:buybacks",
    ]);
  });

  it("gives an empty grid no rows", () => {
    expect(toDriverRows(driverGrid({ rows: [] }))).toEqual([]);
  });
});

describe("forecastCell", () => {
  const years = [2023, 2024, 2025];

  it("shows an own value plain", () => {
    const row = driverRow({ values: ["0.47"], sources: ["own"], own: ["0.47"], kind: "value" });
    expect(forecastCell(row, 0, "value", "M", years)).toEqual({
      text: "47.0%",
      classes: [],
      title: "Set in this scenario",
      editText: "47",
    });
  });

  it("shows an inherited value muted and italic", () => {
    const row = driverRow({ values: ["0.47"], sources: ["base"] });
    const cell = forecastCell(row, 0, "value", "M", years);
    expect(cell.classes).toEqual(["text-muted-foreground", "italic"]);
    expect(cell.title).toBe("Inherited from Base");
    expect(cell.editText).toBe("47");
  });

  it("shows a default muted, naming the years it averages", () => {
    const cell = forecastCell(driverRow(), 0, "value", "M", years);
    expect(cell.text).toBe("2.3%");
    expect(cell.classes).toEqual(["text-muted-foreground"]);
    expect(cell.title).toBe("Default: mean of FY23–FY25");
  });

  it("names the fallback when there is no history to average", () => {
    const row = driverRow({ history: [null, null, null], values: ["0"] });
    expect(forecastCell(row, 0, "value", "M", years).title).toBe(
      "Default: no history, the driver's fallback",
    );
  });

  it("shows 'Set' in red for a required driver with no value", () => {
    const row = driverRow({ values: [null], sources: [null] });
    expect(forecastCell(row, 0, "value", "M", years)).toEqual({
      text: "Set",
      classes: ["text-negative"],
      title: "Required: set a value",
      editText: "",
    });
  });

  it("shows a line held flat", () => {
    const row = driverRow({ unit: "days", values: [null], sources: ["default"] });
    const cell = forecastCell(row, 0, "value", "M", years);
    expect(cell.text).toBe("Flat");
    expect(cell.classes).toEqual(["text-muted-foreground"]);
    expect(cell.title).toBe("Default: the line is held flat");
  });

  it("shows and edits the offset in vs Base mode, with the resolved value in the title", () => {
    const row = driverRow({
      values: ["0.0534"],
      sources: ["offset"],
      own: ["0.03"],
      kind: "offset",
    });
    expect(forecastCell(row, 0, "offset", "M", years)).toEqual({
      text: "+3.0 pts",
      classes: [],
      title: "Base + 3.0 pts = 5.3%",
      editText: "3",
    });
  });

  it("starts an empty editor on a vs Base year with no offset", () => {
    const row = driverRow({ values: ["0.0234"], sources: ["base"], own: [null] });
    const cell = forecastCell(row, 0, "offset", "M", years);
    expect(cell.text).toBe("2.3%");
    expect(cell.title).toBe("Inherited from Base");
    expect(cell.editText).toBe("");
  });
});

describe("driverEdit", () => {
  const years = [2026, 2027];

  it("sends the whole row of own values with the change", () => {
    const row = driverRow({ own: ["0.47", "0.46"], kind: "value", sources: ["own", "own"] });
    expect(driverEdit(row, "value", years, 2027, "0.5")).toEqual({
      driver_code: "revenue_growth",
      kind: "value",
      values: [
        { fiscal_year: 2026, value: "0.47" },
        { fiscal_year: 2027, value: "0.5" },
      ],
    });
  });

  it("adds a first own value to a row that has none", () => {
    expect(driverEdit(driverRow(), "value", years, 2026, "0.04")).toEqual({
      driver_code: "revenue_growth",
      kind: "value",
      values: [{ fiscal_year: 2026, value: "0.04" }],
    });
  });

  it("drops the year of an emptied cell", () => {
    const row = driverRow({ own: ["0.03", "0.03"], kind: "offset" });
    expect(driverEdit(row, "offset", years, 2026, null)).toEqual({
      driver_code: "revenue_growth",
      kind: "offset",
      values: [{ fiscal_year: 2027, value: "0.03" }],
    });
  });

  it("sends an empty row when the last own value is cleared", () => {
    const row = driverRow({ own: ["0.03", null], kind: "offset" });
    expect(driverEdit(row, "offset", years, 2026, null).values).toEqual([]);
  });

  it("keeps none of the stored values of another kind", () => {
    const row = driverRow({ own: ["0.03", "0.03"], kind: "offset" });
    expect(driverEdit(row, "value", years, 2026, "0.1").values).toEqual([
      { fiscal_year: 2026, value: "0.1" },
    ]);
  });
});

describe("driverReset", () => {
  it("sends the row with no values, in its stored kind", () => {
    expect(driverReset(driverRow({ own: ["0.03", "0.03"], kind: "offset" }))).toEqual({
      driver_code: "revenue_growth",
      kind: "offset",
      values: [],
    });
    expect(driverReset(driverRow())).toEqual({
      driver_code: "revenue_growth",
      kind: "value",
      values: [],
    });
  });
});
