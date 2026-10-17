import { describe, expect, it } from "vitest";

import {
  formatCompact,
  formatCsvPercent,
  formatCsvValue,
  formatFiscalPeriod,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatRelative,
  formatSplitRatio,
  formatValue,
  toScaledText,
  parseScaled,
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
