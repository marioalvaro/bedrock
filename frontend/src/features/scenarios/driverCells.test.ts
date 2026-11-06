import { describe, expect, it } from "vitest";

import { driverGrid, driverRow, modesOf, quarterlyGrid } from "@/test/scenarios";

import {
  canReset,
  driverClear,
  driverEdit,
  driverReset,
  engineOptions,
  forecastCell,
  formatEngineError,
  formatSeasonalIndex,
  formatDriverOffset,
  formatDriverValue,
  parseDriverText,
  periodName,
  toDriverRows,
  toDriverText,
} from "./driverCells";

describe("periodName", () => {
  it("names a year FYyy and a quarter Qn FYyy, with two digits", () => {
    expect(periodName(2024, "FY")).toBe("FY24");
    expect(periodName(2026, "Q1")).toBe("Q1 FY26");
    expect(periodName(2100, "Q4")).toBe("Q4 FY00");
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
  const grid = driverGrid();

  it("shows an own value plain", () => {
    const row = driverRow({ values: ["0.47"], sources: ["own"], own: ["0.47"], kind: "value" });
    expect(forecastCell(row, 0, "value", "M", grid)).toEqual({
      text: "47.0%",
      classes: [],
      title: "Set in this scenario",
      editText: "47",
    });
  });

  it("shows an inherited value muted and italic", () => {
    const row = driverRow({ values: ["0.47"], sources: ["base"] });
    const cell = forecastCell(row, 0, "value", "M", grid);
    expect(cell.classes).toEqual(["text-muted-foreground", "italic"]);
    expect(cell.title).toBe("Inherited from Base");
    expect(cell.editText).toBe("47");
  });

  it("shows a default muted, naming the years it averages", () => {
    const cell = forecastCell(driverRow(), 0, "value", "M", grid);
    expect(cell.text).toBe("2.3%");
    expect(cell.classes).toEqual(["text-muted-foreground"]);
    expect(cell.title).toBe("Default: mean of FY23–FY25");
  });

  it("names the fallback when there is no history to average", () => {
    const row = driverRow({ history: [null, null, null], values: ["0"] });
    expect(forecastCell(row, 0, "value", "M", grid).title).toBe(
      "Default: no history, the driver's fallback",
    );
  });

  it("shows 'Set' in red for a required driver with no value", () => {
    const row = driverRow({ values: [null], sources: [null] });
    expect(forecastCell(row, 0, "value", "M", grid)).toEqual({
      text: "Set",
      classes: ["text-negative"],
      title: "Required: set a value",
      editText: "",
    });
  });

  it("shows a line held flat", () => {
    const row = driverRow({ unit: "days", values: [null], sources: ["default"] });
    const cell = forecastCell(row, 0, "value", "M", grid);
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
    expect(forecastCell(row, 0, "offset", "M", grid)).toEqual({
      text: "+3.0 pts",
      classes: [],
      title: "Base + 3.0 pts = 5.3%",
      editText: "3",
    });
  });

  it("leaves the resolved value out of the title while it is unknown (a save is pending)", () => {
    const row = driverRow({ values: [null], sources: ["offset"], own: ["-0.05"], kind: "offset" });
    expect(forecastCell(row, 0, "offset", "M", grid)).toMatchObject({
      text: "-5.0 pts",
      title: "Base - 5.0 pts",
    });
  });

  it("starts an empty editor on a vs Base year with no offset", () => {
    const row = driverRow({ values: ["0.0234"], sources: ["base"], own: [null] });
    const cell = forecastCell(row, 0, "offset", "M", grid);
    expect(cell.text).toBe("2.3%");
    expect(cell.title).toBe("Inherited from Base");
    expect(cell.editText).toBe("");
  });

  describe("in the quarterly grid", () => {
    const quarters = quarterlyGrid();

    it("shows a quarter that takes its year's value muted, naming the year", () => {
      const row = driverRow({ values: ["0.47"], sources: ["year"] });
      const cell = forecastCell(row, 0, "value", "M", quarters);
      expect(cell).toEqual({
        text: "47.0%",
        classes: ["text-muted-foreground"],
        title: "From FY26 (annual)",
        editText: "47",
      });
    });

    it("starts the editor of a year-sourced quarter from the year's value in Value mode", () => {
      const row = driverRow({ values: ["0.47", "0.47"], sources: ["year", "year"] });
      expect(forecastCell(row, 1, "value", "M", quarters).editText).toBe("47");
      expect(forecastCell(row, 1, "offset", "M", quarters).editText).toBe("");
    });

    it("shows an own quarter value plain", () => {
      const row = quarters.rows[1]!;
      expect(forecastCell(row, 0, "value", "M", quarters)).toMatchObject({
        text: "48.0%",
        classes: [],
        title: "Set in this scenario",
        editText: "48",
      });
    });

    it("keeps 'Set' for a required driver the year has no value for", () => {
      const row = quarters.rows[2]!;
      expect(forecastCell(row, 0, "value", "M", quarters).text).toBe("Set");
    });
  });
});

describe("driverEdit", () => {
  const grid = driverGrid(); // forecast years 2026, 2027

  it("sends the whole row of own values with the change", () => {
    const row = driverRow({ own: ["0.47", "0.46"], kind: "value", sources: ["own", "own"] });
    expect(driverEdit(grid, row, "value", 1, "0.5")).toEqual({
      driver_code: "revenue_growth",
      kind: "value",
      values: [
        { fiscal_year: 2026, value: "0.47" },
        { fiscal_year: 2027, value: "0.5" },
      ],
    });
  });

  it("adds a first own value to a row that has none", () => {
    expect(driverEdit(grid, driverRow(), "value", 0, "0.04")).toEqual({
      driver_code: "revenue_growth",
      kind: "value",
      values: [{ fiscal_year: 2026, value: "0.04" }],
    });
  });

  it("drops the year of an emptied cell", () => {
    const row = driverRow({ own: ["0.03", "0.03"], kind: "offset" });
    expect(driverEdit(grid, row, "offset", 0, null)).toEqual({
      driver_code: "revenue_growth",
      kind: "offset",
      values: [{ fiscal_year: 2027, value: "0.03" }],
    });
  });

  it("sends an empty row when the last own value is cleared", () => {
    const row = driverRow({ own: ["0.03", null], kind: "offset" });
    expect(driverEdit(grid, row, "offset", 0, null).values).toEqual([]);
  });

  it("keeps none of the stored values of another kind", () => {
    const row = driverRow({ own: ["0.03", "0.03"], kind: "offset" });
    expect(driverEdit(grid, row, "value", 0, "0.1").values).toEqual([
      { fiscal_year: 2026, value: "0.1" },
    ]);
  });

  describe("in the quarterly grid", () => {
    const quarters = quarterlyGrid(); // forecast quarters Q1 FY26, Q2 FY26

    it("sends a quarterly row whose values name their quarter", () => {
      const row = quarters.rows[1]!; // own 0.48 in Q1
      expect(driverEdit(quarters, row, "value", 1, "0.5")).toEqual({
        driver_code: "gross_margin",
        kind: "value",
        freq: "quarterly",
        values: [
          { fiscal_year: 2026, fiscal_period: "Q1", value: "0.48" },
          { fiscal_year: 2026, fiscal_period: "Q2", value: "0.5" },
        ],
      });
    });

    it("sets one quarter of a driver with no own quarters, the other left to Base or the default", () => {
      expect(driverEdit(quarters, quarters.rows[0]!, "value", 0, "0.06")).toEqual({
        driver_code: "revenue_growth",
        kind: "value",
        freq: "quarterly",
        values: [{ fiscal_year: 2026, fiscal_period: "Q1", value: "0.06" }],
      });
    });

    it("clears a quarter of a by-quarter year by leaving it out", () => {
      const cleared = driverEdit(quarters, quarters.rows[1]!, "value", 0, null);
      expect(cleared.values).toEqual([]);
    });
  });
});

describe("driverReset", () => {
  it("sends the row with no values, in its stored kind", () => {
    const grid = driverGrid();
    expect(driverReset(grid, driverRow({ own: ["0.03", "0.03"], kind: "offset" }))).toEqual({
      driver_code: "revenue_growth",
      kind: "offset",
      values: [],
    });
    expect(driverReset(grid, driverRow())).toEqual({
      driver_code: "revenue_growth",
      kind: "value",
      values: [],
    });
  });

  it("resets only the quarterly rows in the quarterly grid", () => {
    const quarters = quarterlyGrid();
    expect(driverReset(quarters, quarters.rows[1]!)).toEqual({
      driver_code: "gross_margin",
      kind: "value",
      freq: "quarterly",
      values: [],
    });
  });
});

describe("driverClear", () => {
  it("is an empty row of a frequency in a kind, for a mode switch", () => {
    expect(driverClear("tax_rate", "offset", "annual")).toEqual({
      driver_code: "tax_rate",
      kind: "offset",
      values: [],
    });
    expect(driverClear("tax_rate", "offset", "quarterly")).toEqual({
      driver_code: "tax_rate",
      kind: "offset",
      freq: "quarterly",
      values: [],
    });
  });
});

describe("year modes", () => {
  // Two forecast years: FY2026 is in the quarterly span, FY2027 is not.
  const annualByQuarter = driverGrid({ year_modes: modesOf("quarterly") });
  const quartersByYear = quarterlyGrid({ year_modes: modesOf("annual") });

  describe("the annual grid", () => {
    it("shows a by-quarter year's roll-up, read-only, labelled 'Quarters'", () => {
      const row = driverRow({ rollup: ["0.0501", null], values: ["0.0234", "0.0234"] });
      expect(forecastCell(row, 0, "value", "M", annualByQuarter)).toEqual({
        text: "5.0%",
        classes: ["text-muted-foreground"],
        title: "Built from Q1–Q4. Switch FY26 to Annual to set it here.",
        editText: "",
        locked: true,
        note: "Quarters",
      });
    });

    it("shows a dash when the roll-up has no figure", () => {
      const row = driverRow({ rollup: [null, null] });
      expect(forecastCell(row, 0, "value", "M", annualByQuarter)).toMatchObject({
        text: "—",
        locked: true,
        note: "Quarters",
      });
    });

    it("shows the roll-up as a value even for a row in vs Base mode", () => {
      const row = driverRow({ rollup: ["0.0501", null], own: ["0.03", "0.03"], kind: "offset" });
      expect(forecastCell(row, 0, "offset", "M", annualByQuarter).text).toBe("5.0%");
    });

    it("leaves an annually set year and a year after the span as they were", () => {
      const row = driverRow({ rollup: ["0.0501", null] });
      const mixed = driverGrid({ year_modes: modesOf("annual") });
      expect(forecastCell(row, 0, "value", "M", mixed).locked).toBeUndefined();
      expect(forecastCell(row, 1, "value", "M", annualByQuarter).locked).toBeUndefined();
      expect(forecastCell(row, 1, "value", "M", annualByQuarter).note).toBeUndefined();
    });
  });

  describe("the quarterly grid", () => {
    it("locks the quarters of an annually set year, showing its value and naming the year", () => {
      const row = driverRow({ values: ["0.47", "0.47"], sources: ["year", "year"] });
      expect(forecastCell(row, 0, "value", "M", quartersByYear)).toEqual({
        text: "47.0%",
        classes: ["text-muted-foreground"],
        title: "FY26 is set annually. Switch it to By quarter to edit quarters.",
        editText: "47",
        locked: true,
        note: "FY26",
      });
    });

    it("keeps the STL explanation on a locked seasonal quarter", () => {
      const row = driverRow({ values: ["0.468", "0.452"], sources: ["seasonal", "seasonal"] });
      const cell = forecastCell(row, 0, "value", "M", quartersByYear);
      expect(cell.locked).toBe(true);
      expect(cell.title).toBe(
        "FY26 value + the seasonal index (STL). FY26 is set annually. Switch it to By quarter to edit quarters.",
      );
    });

    it("leaves the quarters of a by-quarter year editable", () => {
      const quarters = quarterlyGrid();
      const cell = forecastCell(quarters.rows[1]!, 0, "value", "M", quarters);
      expect(cell.locked).toBeUndefined();
      expect(cell.note).toBeUndefined();
    });
  });

  describe("driverEdit", () => {
    it("never sends an annual value for a by-quarter year", () => {
      const row = driverRow({ own: ["0.03", "0.04"], kind: "value" }); // FY2026's is the hidden one
      expect(driverEdit(annualByQuarter, row, "value", 1, "0.05")).toEqual({
        driver_code: "revenue_growth",
        kind: "value",
        values: [{ fiscal_year: 2027, value: "0.05" }],
      });
    });

    it("sends only the quarters set in the case: the others follow Base or the default", () => {
      const quarters = quarterlyGrid();
      const row = driverRow({
        code: "gross_margin",
        values: ["0.48", "0.47"],
        sources: ["base", "base"],
        own: [null, null],
        kind: null,
      });
      expect(driverEdit(quarters, row, "value", 0, "0.5")).toEqual({
        driver_code: "gross_margin",
        kind: "value",
        freq: "quarterly",
        values: [{ fiscal_year: 2026, fiscal_period: "Q1", value: "0.5" }],
      });
      expect(driverEdit(quarters, row, "offset", 1, "0.01").values).toEqual([
        { fiscal_year: 2026, fiscal_period: "Q2", value: "0.01" },
      ]);
    });

    it("keeps a quarter's own value and drops an emptied one", () => {
      const quarters = quarterlyGrid();
      const own = driverRow({ values: ["0.48", "0.47"], own: ["0.48", null], kind: "value" });
      expect(driverEdit(quarters, own, "value", 1, "0.5").values).toEqual([
        { fiscal_year: 2026, fiscal_period: "Q1", value: "0.48" },
        { fiscal_year: 2026, fiscal_period: "Q2", value: "0.5" },
      ]);
      expect(driverEdit(quarters, own, "value", 0, null).values).toEqual([]);
    });
  });

  describe("canReset", () => {
    const own = driverRow({ own: ["0.03", null], kind: "value" });

    it("needs an own value in a column that is set", () => {
      expect(canReset(driverGrid(), driverRow())).toBe(false);
      expect(canReset(driverGrid(), own)).toBe(true);
    });

    it("ignores the hidden annual value of a by-quarter year", () => {
      expect(canReset(annualByQuarter, own)).toBe(false);
      expect(canReset(annualByQuarter, driverRow({ own: ["0.03", "0.04"], kind: "value" }))).toBe(
        true,
      );
    });

    it("is offered in the quarterly grid of a by-quarter year (its quarters fall back to Base)", () => {
      const quarters = quarterlyGrid();
      expect(canReset(quarters, quarters.rows[1]!)).toBe(true);
      expect(canReset(quarters, quarters.rows[0]!)).toBe(false);
    });
  });
});

describe("engine defaults (M6)", () => {
  const grid = driverGrid();
  const engineRow = (overrides: Parameters<typeof driverRow>[0] = {}) =>
    driverRow({
      code: "gross_margin",
      values: ["0.4578", "0.4484"],
      sources: ["engine", "engine"],
      engine_used: "arima",
      seasonal: true,
      ...overrides,
    });

  it("shows an engine default muted, naming the engine and Auto's rule", () => {
    const cell = forecastCell(engineRow(), 0, "value", "M", grid);
    expect(cell.text).toBe("45.8%");
    expect(cell.classes).toEqual(["text-muted-foreground"]);
    expect(cell.title).toBe("Default: ARIMA forecast · Auto: lowest holdout error");
    expect(cell.editText).toBe("45.78");
  });

  it("names an explicitly chosen engine without Auto's rule", () => {
    const row = engineRow({ engine: "ets", engine_used: "ets" });
    expect(forecastCell(row, 1, "value", "M", grid).title).toBe("Default: ETS forecast");
  });

  it("names the blend", () => {
    const row = engineRow({ engine: "blend", engine_used: "blend" });
    expect(forecastCell(row, 0, "value", "M", grid).title).toBe("Default: Blend forecast");
  });

  it("puts the engine note in place of Auto's rule", () => {
    const row = engineRow({ engine_used: "blend", engine_note: "Auto: 9 years of history; blend" });
    expect(forecastCell(row, 0, "value", "M", grid).title).toBe(
      "Default: Blend forecast · Auto: 9 years of history; blend",
    );
  });

  it("adds the note to a 3-year-mean default (Auto fell back)", () => {
    const row = driverRow({ engine_note: "Auto: 6 years of history (needs 8); 3-year mean" });
    expect(forecastCell(row, 0, "value", "M", grid).title).toBe(
      "Default: mean of FY23–FY25 · Auto: 6 years of history (needs 8); 3-year mean",
    );
  });

  it("titles a seasonal quarter by its year's value and the STL index", () => {
    const quarters = quarterlyGrid();
    const row = driverRow({ values: ["0.47", "0.46"], sources: ["seasonal", "seasonal"] });
    const cell = forecastCell(row, 1, "value", "M", quarters);
    expect(cell.text).toBe("46.0%");
    expect(cell.classes).toEqual(["text-muted-foreground"]);
    expect(cell.title).toBe("FY26 value + the seasonal index (STL)");
  });
});

describe("cross-check (M6)", () => {
  const grid = driverGrid();
  const checked = (
    unit: "pct" | "days" | "USD",
    value: string,
    p05: string,
    p95: string,
    outside: boolean,
  ) =>
    driverRow({
      unit,
      values: [value, value],
      sources: ["own", "own"],
      own: [value, value],
      kind: "value",
      check: [{ engine: "arima", p05, p95, outside }, null],
    });

  it("adds the range to the title of a value within it", () => {
    const cell = forecastCell(
      checked("pct", "0.45", "0.4186", "0.4970", false),
      0,
      "value",
      "M",
      grid,
    );
    expect(cell.classes).toEqual([]);
    expect(cell.title).toBe("Set in this scenario · Within the ARIMA 90% range (41.9%–49.7%)");
  });

  it("marks a value outside the range", () => {
    const cell = forecastCell(
      checked("pct", "0.9", "0.4186", "0.4970", true),
      0,
      "value",
      "M",
      grid,
    );
    expect(cell.classes).toEqual(["cell-check-outside"]);
    expect(cell.title).toBe("Set in this scenario · Outside the ARIMA 90% range (41.9%–49.7%)");
  });

  it("formats the range by the row's unit", () => {
    expect(
      forecastCell(checked("days", "70", "55.04", "64.96", true), 0, "value", "M", grid).title,
    ).toBe("Set in this scenario · Outside the ARIMA 90% range (55.0–65.0)");
    expect(
      forecastCell(checked("USD", "1", "80000000000", "95500000000", false), 0, "value", "B", grid)
        .title,
    ).toBe("Set in this scenario · Within the ARIMA 90% range (80.0–95.5)");
  });

  it("checks an inherited or offset value too, and leaves a year without a check alone", () => {
    const row = driverRow({
      values: ["0.45", "0.46"],
      sources: ["base", "base"],
      check: [{ engine: "blend", p05: "0.42", p95: "0.50", outside: false }, null],
    });
    expect(forecastCell(row, 0, "value", "M", grid).title).toBe(
      "Inherited from Base · Within the Blend 90% range (42.0%–50.0%)",
    );
    expect(forecastCell(row, 1, "value", "M", grid).title).toBe("Inherited from Base");
    const offset = driverRow({
      values: ["0.48", null],
      sources: ["offset", "base"],
      own: ["0.01", null],
      kind: "offset",
      check: [{ engine: "ets", p05: "0.42", p95: "0.47", outside: true }, null],
    });
    const cell = forecastCell(offset, 0, "offset", "M", grid);
    expect(cell.classes).toEqual(["cell-check-outside"]);
    expect(cell.title).toBe("Base + 1.0 pts = 48.0% · Outside the ETS 90% range (42.0%–47.0%)");
  });
});

describe("engineOptions", () => {
  it("lists Auto with its pick, Mean, ARIMA, ETS and Blend", () => {
    expect(engineOptions(driverRow({ engine: "auto", engine_used: "ets" }))).toEqual([
      { value: "auto", label: "Auto · ETS" },
      { value: "mean", label: "Mean (3 yr)" },
      { value: "arima", label: "ARIMA" },
      { value: "ets", label: "ETS" },
      { value: "blend", label: "Blend" },
    ]);
  });

  it("adds STL for a seasonal driver", () => {
    const labels = engineOptions(driverRow({ seasonal: true })).map((o) => o.label);
    expect(labels.at(-1)).toBe("STL");
    expect(labels).toHaveLength(6);
  });

  it("reads 'Auto · Mean' when Auto fell back to the mean", () => {
    expect(engineOptions(driverRow({ engine: "auto", engine_used: "mean" }))[0]!.label).toBe(
      "Auto · Mean",
    );
  });

  it("reads plain 'Auto' when another engine is chosen (Auto's pick is not known)", () => {
    expect(engineOptions(driverRow({ engine: "arima", engine_used: "arima" }))[0]!.label).toBe(
      "Auto",
    );
  });
});

describe("engine sheet texts", () => {
  it("shows a holdout error unsigned in the unit", () => {
    expect(formatEngineError("0.0549612179", "pct", "M")).toBe("5.5 pts");
    expect(formatEngineError("2.14", "days", "M")).toBe("2.1 days");
    expect(formatEngineError("1500000000", "USD", "B")).toBe("1.5");
    expect(formatEngineError(null, "pct", "M")).toBe("—");
  });

  it("signs a seasonal index with a true minus, zero without a sign", () => {
    expect(formatSeasonalIndex("0.012", "pct", "M")).toBe("+1.2 pts");
    expect(formatSeasonalIndex("-3", "days", "M")).toBe("\u22123.0 days");
    expect(formatSeasonalIndex("-0.0003", "pct", "M")).toBe("0.0 pts");
  });
});
