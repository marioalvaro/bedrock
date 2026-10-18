import { describe, expect, it } from "vitest";

import { isFormulaLevel, levelText, levelToSend } from "@/lib/levels";

describe("levelToSend", () => {
  it("sends a pct number as an exact fraction", () => {
    expect(levelToSend("5", "pct")).toBe("0.05");
    expect(levelToSend(" 12.5 ", "pct")).toBe("0.125");
  });
  it("sends an x number as typed", () => {
    expect(levelToSend("0.8", "x")).toBe("0.8");
  });
  it.each(["", "   ", "\t"])("sends no level for blank %j", (text) => {
    expect(levelToSend(text, "pct")).toBeNull();
  });
  it("sends a formula trimmed, as typed", () => {
    expect(levelToSend("  prev(sbc / revenue) + 1%  ", "pct")).toBe("prev(sbc / revenue) + 1%");
  });
  it("sends a constant expression as typed in fraction units, not divided by 100", () => {
    expect(levelToSend("4 + 1", "pct")).toBe("4 + 1");
  });
  it("sends text parseThreshold rejects (a trailing %) as typed", () => {
    expect(levelToSend("5%", "pct")).toBe("5%");
  });
});

describe("levelText", () => {
  it("prefills a formula as its text", () => {
    expect(levelText(null, "prev(sbc / revenue)", "pct")).toBe("prev(sbc / revenue)");
  });
  it("prefers the formula when both number and formula are present", () => {
    expect(levelText("0.05", "avg(x)", "pct")).toBe("avg(x)");
  });
  it("prefills a number via toThresholdText", () => {
    expect(levelText("0.05", null, "pct")).toBe("5");
    expect(levelText("0.8", null, "x")).toBe("0.8");
  });
  it("prefills nothing when there is no level", () => {
    expect(levelText(null, null, "pct")).toBe("");
  });
});

describe("isFormulaLevel", () => {
  it("is true for non-blank text that is not a number", () => {
    expect(isFormulaLevel("prev(sbc) + 1", "pct")).toBe(true);
  });
  it("is false for numbers and blanks", () => {
    expect(isFormulaLevel("5", "pct")).toBe(false);
    expect(isFormulaLevel("  ", "x")).toBe(false);
    expect(isFormulaLevel("", "x")).toBe(false);
  });
});
