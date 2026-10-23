import { describe, expect, it } from "vitest";

import {
  formatCompact,
  formatCsvPercent,
  formatCsvRatio,
  formatCsvValue,
  formatFiscalPeriod,
  formatGuidanceValue,
  formatHitRate,
  formatRange,
  formatRank,
  formatSignedPercent,
  formatVsMedian,
  parseGuidanceValue,
  toGuidanceText,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatRatio,
  formatThreshold,
  formatRelative,
  formatSegmentValue,
  parseSegmentValue,
  toSegmentText,
  formatSplitRatio,
  formatValue,
  toScaledText,
  parseScaled,
  parseThreshold,
  toThresholdText,
  scaleLabel,
} from "./format";

describe("formatValue", () => {
  it("shows an em dash for null", () => {
    expect(formatValue(null, "USD", "M")).toBe("—");
  });

  it("divides USD by the scale divisor with thousands separators and no decimals in M", () => {
    expect(formatValue("391035000000", "USD", "M")).toBe("391,035");
  });

  it("shows one decimal in B", () => {
    expect(formatValue("391035000000", "USD", "B")).toBe("391.0");
  });

  it("shows no decimals in K", () => {
    expect(formatValue("391035000000", "USD", "K")).toBe("391,035,000");
  });

  it("puts negatives in parentheses", () => {
    expect(formatValue("-1234000000", "USD", "M")).toBe("(1,234)");
  });

  it("does not show a negative zero", () => {
    expect(formatValue("-300000", "USD", "M")).toBe("0");
  });

  it("never scales USD/shares and shows two decimals", () => {
    expect(formatValue("6.11", "USD/shares", "B")).toBe("6.11");
    expect(formatValue("-0.5", "USD/shares", "K")).toBe("(0.50)");
  });

  it("scales shares with the current scale", () => {
    expect(formatValue("15343783000", "shares", "M")).toBe("15,344");
  });

  it("is not fooled by a decimal string with padding", () => {
    expect(formatValue("336.8450000000", "USD/shares", "M")).toBe("336.85");
  });
});

describe("formatPercent", () => {
  it("renders a fraction as a percentage with one decimal", () => {
    expect(formatPercent("0.0512")).toBe("5.1%");
    expect(formatPercent("0.333")).toBe("33.3%");
  });

  it("puts negatives in parentheses", () => {
    expect(formatPercent("-0.028")).toBe("(2.8%)");
  });

  it("shows an em dash for null", () => {
    expect(formatPercent(null)).toBe("—");
  });

  it("does not show a negative zero", () => {
    expect(formatPercent("-0.00001")).toBe("0.0%");
  });
});

describe("scaleLabel", () => {
  it.each([
    ["USD", "K", "USD thousands"],
    ["USD", "M", "USD millions"],
    ["USD", "B", "USD billions"],
    ["shares", "M", "shares millions"],
    ["USD/shares", "B", "USD/share"],
  ] as const)("%s at %s is %s", (unit, scale, label) => {
    expect(scaleLabel(unit, scale)).toBe(label);
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-10-08T12:00:00Z");

  it.each([
    ["2026-10-08T11:59:40Z", "just now"],
    ["2026-10-08T11:55:00Z", "5m ago"],
    ["2026-10-08T10:00:00Z", "2h ago"],
    ["2026-10-05T12:00:00Z", "3d ago"],
  ])("%s -> %s", (iso, text) => {
    expect(formatRelative(iso, now)).toBe(text);
  });

  it("says never for null", () => {
    expect(formatRelative(null, now)).toBe("never");
  });

  it("treats a future timestamp as just now", () => {
    expect(formatRelative("2026-10-08T12:05:00Z", now)).toBe("just now");
  });
});

describe("CSV values", () => {
  it("uses the current scale, a plain minus sign and no thousands separators", () => {
    expect(formatCsvValue("391035000000", "USD", "M")).toBe("391035");
    expect(formatCsvValue("-1234000000", "USD", "M")).toBe("-1234");
    expect(formatCsvValue("391035000000", "USD", "B")).toBe("391.0");
  });

  it("keeps per-share values unscaled with two decimals", () => {
    expect(formatCsvValue("6.08", "USD/shares", "B")).toBe("6.08");
  });

  it("is empty for null", () => {
    expect(formatCsvValue(null, "USD", "M")).toBe("");
    expect(formatCsvPercent(null)).toBe("");
  });

  it("writes ratios as percentages a spreadsheet reads as numbers", () => {
    expect(formatCsvPercent("0.0512")).toBe("5.1%");
    expect(formatCsvPercent("-0.028")).toBe("-2.8%");
  });

  it("does not write a negative zero", () => {
    expect(formatCsvValue("-300000", "USD", "M")).toBe("0");
  });
});

describe("key stats", () => {
  it("compacts a market cap to T, B or M", () => {
    expect(formatCompact("3500000000000.00")).toBe("3.5T");
    expect(formatCompact("245600000000")).toBe("245.6B");
    expect(formatCompact("12300000")).toBe("12.3M");
    expect(formatCompact(null)).toBe("—");
  });

  it("shows a price with two decimals and a separator", () => {
    expect(formatPrice("1234.5")).toBe("1,234.50");
    expect(formatPrice(null)).toBe("—");
  });

  it("shows a multiple with one decimal and an x", () => {
    expect(formatMultiple("34.21")).toBe("34.2x");
    expect(formatMultiple(null)).toBe("—");
  });
});

describe("parseScaled", () => {
  it.each([
    ["25", "M", "25000000"],
    ["-25", "M", "-25000000"],
    ["(25)", "M", "-25000000"],
    ["1,234.5", "M", "1234500000"],
    ["0.0000005", "M", "0.5"],
    ["1.5", "B", "1500000000"],
    ["2", "K", "2000"],
    [" 25 ", "M", "25000000"],
    ["0", "M", "0"],
    ["-0", "M", "0"],
    ["(0.0)", "B", "0"],
    ["007", "M", "7000000"],
    [".5", "K", "500"],
    ["1.250", "K", "1250"],
    ["999999999999", "B", "999999999999000000000"],
    ["0.1", "M", "100000"],
    ["1,234,567", "M", "1234567000000"],
  ] as const)("parses %j in %s as %j", (text, scale, expected) => {
    expect(parseScaled(text, scale)).toBe(expected);
  });

  it.each([
    "",
    "   ",
    "abc",
    "1.2.3",
    "--5",
    "1e6",
    "(5",
    "5)",
    "-(5)",
    "1,23",
    ",5",
    "1,2345",
    ".",
    // A leading plus sign is not accepted (pinned current behaviour).
    "+5",
  ])("rejects %j", (text) => {
    expect(parseScaled(text, "M")).toBeNull();
  });
});

describe("formatSplitRatio", () => {
  it.each([
    ["4", "4-for-1"],
    ["7", "7-for-1"],
    ["0.1", "1-for-10"],
    ["0.25", "1-for-4"],
    ["1.5", "3-for-2"],
    ["1", "1-for-1"],
    ["4.0000000000", "4-for-1"],
    ["0.3333333333", "1-for-3"],
  ])("formats %j as %j", (ratio, expected) => {
    expect(formatSplitRatio(ratio)).toBe(expected);
  });

  it.each(["0", "-1", "abc"])("returns %j unchanged when it is not a positive number", (ratio) => {
    expect(formatSplitRatio(ratio)).toBe(ratio);
  });

  it("falls back to <number>-for-1 when no pair fits within a denominator of 1000", () => {
    expect(formatSplitRatio("0.0001234")).toBe("0.0001234-for-1");
  });
});

describe("toScaledText", () => {
  it.each([
    ["-25000000", "M", "-25"],
    ["-25500000", "M", "-25.5"],
    ["1500000000", "B", "1.5"],
    ["0", "M", "0"],
    ["123", "M", "0.000123"],
    ["25000", "K", "25"],
  ] as const)("shows %s in %s as %s", (units, scale, text) => {
    expect(toScaledText(units, scale)).toBe(text);
  });

  it.each(["1E-7", "-2.5e+3", "1e6"])("returns the exponent form %j unchanged", (units) => {
    expect(toScaledText(units, "M")).toBe(units);
  });

  it("round-trips with parseScaled", () => {
    for (const scale of ["K", "M", "B"] as const) {
      for (const units of ["-25000000", "0", "123", "1500000000", "-7", "12345678901.5"]) {
        expect(parseScaled(toScaledText(units, scale), scale)).toBe(units);
      }
    }
  });
});

describe("formatFiscalPeriod", () => {
  it("names a year and a quarter", () => {
    expect(formatFiscalPeriod(2024, "FY")).toBe("FY2024");
    expect(formatFiscalPeriod(2024, "Q1")).toBe("Q1 FY2024");
  });
});

describe("formatRatio", () => {
  it.each([
    ["0.123", "pct", "12.3%"],
    ["-0.034", "pct", "(3.4%)"],
    ["12.34", "x", "12.3x"],
    ["-1.23", "x", "(1.2x)"],
    ["45.4", "days", "45"],
    ["1234", "days", "1,234"],
    ["-1234.4", "days", "(1,234)"],
    ["6.1111", "USD/shares", "6.11"],
    ["-6.1111", "USD/shares", "(6.11)"],
    ["1234.5", "USD/shares", "1,234.50"],
  ] as const)("formats %s as %s -> %s", (value, unit, text) => {
    expect(formatRatio(value, unit)).toBe(text);
  });

  it("shows an em dash for null in every unit", () => {
    for (const unit of ["pct", "x", "days", "USD/shares"] as const) {
      expect(formatRatio(null, unit)).toBe("—");
    }
  });

  it("gives a value rounding to zero no sign", () => {
    expect(formatRatio("-0.00001", "pct")).toBe("0.0%");
    expect(formatRatio("-0.04", "x")).toBe("0.0x");
    expect(formatRatio("-0.4", "days")).toBe("0");
    expect(formatRatio("-0.001", "USD/shares")).toBe("0.00");
    expect(formatRatio("-0", "x")).toBe("0.0x");
  });
});

describe("formatCsvRatio", () => {
  it.each([
    ["-0.028", "pct", "-2.8%"],
    ["12.34", "x", "12.3"],
    ["-12.34", "x", "-12.3"],
    ["1234.4", "days", "1234"],
    ["45", "days", "45"],
    ["6.1111", "USD/shares", "6.11"],
    ["-1234.567", "USD/shares", "-1234.57"],
  ] as const)("writes %s as %s -> %s", (value, unit, text) => {
    expect(formatCsvRatio(value, unit)).toBe(text);
  });

  it("writes null as an empty cell", () => {
    for (const unit of ["pct", "x", "days", "USD/shares"] as const) {
      expect(formatCsvRatio(null, unit)).toBe("");
    }
  });

  it("never writes -0", () => {
    expect(formatCsvRatio("-0.00001", "pct")).toBe("0%");
    expect(formatCsvRatio("-0.04", "x")).toBe("0");
    expect(formatCsvRatio("-0.4", "days")).toBe("0");
    expect(formatCsvRatio("-0.001", "USD/shares")).toBe("0");
  });
});

describe("parseThreshold", () => {
  it.each([
    ["5", "pct", "0.05"],
    ["12.5", "pct", "0.125"],
    ["-3", "pct", "-0.03"],
    ["0", "pct", "0"],
    ["-0", "pct", "0"],
    ["(5)", "pct", "-0.05"],
    ["1,000", "pct", "10"],
    [" 5 ", "pct", "0.05"],
    ["150", "pct", "1.5"],
    ["0.001", "pct", "0.00001"],
    ["10.0", "pct", "0.1"],
    ["007", "pct", "0.07"],
    [".5", "pct", "0.005"],
    ["0.80", "x", "0.8"],
    ["00.5", "x", "0.5"],
    ["-1.50", "x", "-1.5"],
    ["(2)", "x", "-2"],
    ["1,234.5", "x", "1234.5"],
    ["0.0", "x", "0"],
    ["-0.0", "x", "0"],
    ["0", "x", "0"],
  ] as const)("parses %j (%s) as %j", (text, unit, level) => {
    expect(parseThreshold(text, unit)).toBe(level);
  });

  it.each([
    "+5",
    "1e3",
    "1E-7",
    "5.",
    "1,23",
    "abc",
    "",
    "  ",
    "-",
    "()",
    "--5",
    "(5",
    "5)",
    "1 000",
  ])("rejects %j", (text) => {
    expect(parseThreshold(text, "pct")).toBeNull();
    expect(parseThreshold(text, "x")).toBeNull();
  });
});

describe("toThresholdText", () => {
  it.each([
    ["0.05", "pct", "5"],
    ["0.125", "pct", "12.5"],
    ["-0.03", "pct", "-3"],
    ["0", "pct", "0"],
    ["0.1", "pct", "10"],
    ["1.5", "pct", "150"],
    ["0.8", "x", "0.8"],
    ["0.80", "x", "0.8"],
    ["-2", "x", "-2"],
    ["12.50", "x", "12.5"],
    ["1E-7", "pct", "0.00001"],
    ["5E+1", "pct", "5000"],
    ["1E-7", "x", "0.0000001"],
    ["5E+1", "x", "50"],
    ["-2.5e-2", "pct", "-2.5"],
  ] as const)("shows %j (%s) as %j", (level, unit, text) => {
    expect(toThresholdText(level, unit)).toBe(text);
  });

  it("round-trips with parseThreshold to the canonical level", () => {
    const levels: [string, string][] = [
      ["0.05", "0.05"],
      ["0.125", "0.125"],
      ["-0.03", "-0.03"],
      ["0", "0"],
      ["0.1", "0.1"],
      ["0.10", "0.1"],
      ["1.5", "1.5"],
      ["1234.5", "1234.5"],
      ["-7", "-7"],
      ["0.00001", "0.00001"],
      ["1E-7", "0.0000001"],
      ["5E+1", "50"],
      ["100", "100"],
      ["0.8", "0.8"],
    ];
    for (const unit of ["pct", "x"] as const) {
      for (const [level, canonical] of levels) {
        expect(parseThreshold(toThresholdText(level, unit), unit)).toBe(canonical);
      }
    }
  });
});

describe("formatThreshold", () => {
  it.each([
    ["0.05", "pct", "5%"],
    ["0.125", "pct", "12.5%"],
    ["-0.03", "pct", "-3%"],
    ["0", "pct", "0%"],
    ["0.8", "x", "0.8x"],
    ["0", "x", "0x"],
    ["1E-7", "x", "0.0000001x"],
  ] as const)("shows %j (%s) as %j", (level, unit, text) => {
    expect(formatThreshold(level, unit)).toBe(text);
  });
});

describe("segment values by unit", () => {
  it.each([
    ["USD", "M", "391,035", "391035000000"],
    ["USD", "B", "(1.5)", "-1500000000"],
    ["pct", "M", "5.2", "0.052"],
    ["pct", "M", "5.2%", "0.052"],
    ["pct", "M", " (3) % ", "-0.03"],
    ["count", "M", "4,230", "4230"],
    ["count", "B", "1.5", "1.5"],
    ["USD_per_unit", "M", "4.50", "4.5"],
  ] as const)("parses %s typed in %s as %j", (unit, scale, text, stored) => {
    expect(parseSegmentValue(text, unit, scale)).toBe(stored);
  });

  it.each([
    ["USD", "abc"],
    ["USD", "1e3"],
    ["pct", "5.2 percent"],
    ["pct", "%"],
    ["count", "1,23"],
    ["USD_per_unit", "$4"],
  ] as const)("rejects %s text %j", (unit, text) => {
    expect(parseSegmentValue(text, unit, "M")).toBeNull();
  });

  it("shows a stored value as editable text that parses back to it", () => {
    const cases = [
      ["USD", "167045000000", "167045"],
      ["pct", "0.052", "5.2"],
      ["count", "4230", "4230"],
      ["USD_per_unit", "4.5", "4.5"],
    ] as const;
    for (const [unit, stored, text] of cases) {
      expect(toSegmentText(stored, unit, "M")).toBe(text);
      expect(parseSegmentValue(text, unit, "M")).toBe(stored);
    }
  });

  it.each([
    ["USD", "167045000000", "167,045"],
    ["USD", "-1500000", "(2)"],
    ["pct", "0.052", "5.2%"],
    ["pct", "-0.031", "(3.1%)"],
    ["count", "4230", "4,230"],
    ["count", "1.5", "1.5"],
    ["count", "1.234", "1.23"],
    ["USD_per_unit", "4.5", "4.50"],
  ] as const)("formats %s %s as %j", (unit, value, text) => {
    expect(formatSegmentValue(value, unit, "M")).toBe(text);
  });

  it("formats null as an em dash", () => {
    expect(formatSegmentValue(null, "USD", "M")).toBe("—");
  });
});

describe("formatSignedPercent", () => {
  it.each([
    ["0.123", "+12.3%"],
    ["-0.0512", "-5.1%"],
    ["0", "0.0%"],
    ["-0.0001", "0.0%"],
    [null, "—"],
  ] as const)("formats %j as %j", (value, text) => {
    expect(formatSignedPercent(value)).toBe(text);
  });
});

describe("formatVsMedian", () => {
  it.each([
    ["0.123", "x", "+12.3%"],
    ["-0.25", "days", "-25.0%"],
    ["0.021", "pct", "+2.1 pts"],
    ["-0.0345", "pct", "-3.5 pts"],
    ["0", "pct", "0.0 pts"],
    [null, "x", "—"],
  ] as const)("formats %j %s as %j", (value, unit, text) => {
    expect(formatVsMedian(value, unit)).toBe(text);
  });
});

describe("formatRange", () => {
  it("joins the peer min and max by unit", () => {
    expect(formatRange("12.1", "30.4", "x")).toBe("12.1x – 30.4x");
    expect(formatRange("-0.02", "0.31", "pct")).toBe("(2.0%) – 31.0%");
  });

  it("is an em dash when either end is missing", () => {
    expect(formatRange(null, null, "x")).toBe("—");
    expect(formatRange("1", null, "x")).toBe("—");
  });
});

describe("formatRank", () => {
  it("ranks the target among itself and the peers used", () => {
    expect(formatRank(2, 3)).toBe("2 / 4");
    expect(formatRank(1, 1)).toBe("1 / 2");
  });

  it("is an em dash with no peer values or no target", () => {
    expect(formatRank(1, 0)).toBe("—");
    expect(formatRank(null, 3)).toBe("—");
  });
});

describe("guidance values", () => {
  it.each([
    ["USD", "391035000000", "391,035"],
    ["shares", "15000000000", "15,000"],
    ["USD/shares", "6.11", "6.11"],
    ["pct", "0.462", "46.2%"],
    ["x", "1.5", "1.5x"],
    ["days", "45", "45"],
    ["count", "4230", "4,230"],
    ["USD_per_unit", "4.5", "4.50"],
  ] as const)("formats %s %s as %j in M", (unit, value, text) => {
    expect(formatGuidanceValue(value, unit, "M")).toBe(text);
  });

  it("formats null as an em dash and an unknown unit (a deleted KPI) as a plain number", () => {
    expect(formatGuidanceValue(null, "USD", "M")).toBe("—");
    expect(formatGuidanceValue("12.5", null, "M")).toBe("12.5");
  });

  it.each([
    ["USD", "380", "B", "380000000000"],
    ["USD", "-11", "B", "-11000000000"],
    ["shares", "15,000", "M", "15000000000"],
    ["pct", "46", "M", "0.46"],
    ["pct", "46.5%", "M", "0.465"],
    ["x", "1.5", "M", "1.5"],
    ["USD/shares", "6.11", "B", "6.11"],
    ["count", "4230", "B", "4230"],
    ["USD_per_unit", "4.5", "B", "4.5"],
  ] as const)("parses %s %j in %s as %j", (unit, text, scale, value) => {
    expect(parseGuidanceValue(text, unit, scale)).toBe(value);
  });

  it("rejects malformed text", () => {
    expect(parseGuidanceValue("abc", "USD", "M")).toBeNull();
    expect(parseGuidanceValue("", "pct", "M")).toBeNull();
  });

  it.each([
    ["USD", "380000000000", "B", "380"],
    ["pct", "0.465", "M", "46.5"],
    ["USD/shares", "6.11", "M", "6.11"],
  ] as const)("prefills %s %s in %s as %j", (unit, value, scale, text) => {
    expect(toGuidanceText(value, unit, scale)).toBe(text);
    expect(parseGuidanceValue(text, unit, scale)).toBe(value);
  });
});

describe("formatHitRate", () => {
  it.each([
    ["0.500000", "50%"],
    ["0.846154", "85%"],
    ["1.000000", "100%"],
    ["0.000000", "0%"],
    [null, "—"],
  ] as const)("formats %j as %j", (value, text) => {
    expect(formatHitRate(value)).toBe(text);
  });
});
