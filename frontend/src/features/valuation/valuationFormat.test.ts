import { describe, expect, it } from "vitest";

import { dcf, inputRow, peResult, valuationInputs } from "@/test/valuation";

import {
  choiceLabel,
  clearText,
  discountText,
  formatPerShare,
  formatTimes,
  formatUpside,
  inputEdit,
  inputText,
  midYearText,
  parseInputText,
  percentileText,
  periodLabel,
  priceText,
  resetText,
  shownCodes,
  sourceClass,
  sourceText,
  sourceTitle,
  targetFields,
  targets,
  terminalTexts,
  upsideClass,
} from "./valuationFormat";

describe("result texts", () => {
  it("formats a value per share in dollars with 2 decimals", () => {
    expect(formatPerShare("187.4")).toBe("$187.40");
    expect(formatPerShare("131.8333307817371175593083212")).toBe("$131.83");
    expect(formatPerShare("1234.5")).toBe("$1,234.50");
    expect(formatPerShare("-12")).toBe("($12.00)");
    expect(formatPerShare(null)).toBe("—");
  });

  it("formats an upside as a signed percent and colors it by its sign", () => {
    expect(formatUpside("0.123")).toBe("+12.3%");
    expect(formatUpside("-0.6084197261955709817943139537")).toBe("-60.8%");
    expect(formatUpside("0")).toBe("0.0%");
    expect(formatUpside(null)).toBe("—");
    expect(upsideClass("0.123")).toBe("text-positive");
    expect(upsideClass("-0.01")).toBe("text-negative");
    expect(upsideClass("0")).toBe("");
    expect(upsideClass(null)).toBe("");
  });

  it("formats a multiple with ×", () => {
    expect(formatTimes("25.06")).toBe("25.1×");
    expect(formatTimes("12")).toBe("12.0×");
    expect(formatTimes(null)).toBe("—");
  });

  it("names a percentile by its ordinal", () => {
    expect(percentileText("0.5")).toBe("50th");
    expect(percentileText("0.01")).toBe("1st");
    expect(percentileText("0.22")).toBe("22nd");
    expect(percentileText("0.03")).toBe("3rd");
    expect(percentileText("0.11")).toBe("11th");
    expect(percentileText("0.12")).toBe("12th");
    expect(percentileText("0.375")).toBe("37.5th");
    expect(percentileText("0")).toBe("0th");
    expect(percentileText("1")).toBe("100th");
  });

  it("says where each multiple comes from", () => {
    const multiple = peResult().multiple!;
    expect(sourceText(multiple)).toBe("Manual");
    expect(sourceText({ ...multiple, source: "own_history", percentile: "0.5", n: 9 })).toBe(
      "Own history, 50th percentile of 9 years",
    );
    expect(
      sourceText({
        ...multiple,
        source: "peer_median",
        n: 4,
        comps_set: { id: 3, name: "Megacaps" },
      }),
    ).toBe("Peer median of Megacaps (4 peers)");
    expect(
      sourceText({ ...multiple, source: "peer_median", n: 1, comps_set: { id: 3, name: "Pair" } }),
    ).toBe("Peer median of Pair (1 peer)");
  });

  it("writes the WACC line from the API's components", () => {
    expect(discountText(dcf().discount)).toBe(
      "WACC 8.9% · cost of equity 9.0% (4.0% + 1.00 × 5.0%) · after-tax cost of debt 2.8% · debt 1.7% / equity 98.3%",
    );
  });

  it("writes a direct rate as set directly", () => {
    const discount = {
      ...dcf().discount,
      method: "direct",
      rate: "0.09",
      cost_of_equity: null,
      after_tax_cost_of_debt: null,
      risk_free_rate: null,
      equity_risk_premium: null,
      beta: null,
      cost_of_debt: null,
      tax_rate: null,
      debt_weight: null,
      equity_weight: null,
    };
    expect(discountText(discount)).toBe("Discount rate 9.0% (set directly)");
  });

  it("says whether cash flows are discounted mid-year", () => {
    expect(midYearText(true)).toBe("Mid-year discounting");
    expect(midYearText(false)).toBe("End-of-year discounting");
  });

  it("describes a Gordon terminal value with its implied exit multiple and its share of EV", () => {
    expect(terminalTexts(dcf())).toEqual({
      method: "Gordon growth 2.5%",
      implied: "Implied exit multiple 12.1× EV/EBITDA",
      share: "Terminal value is 76% of EV",
    });
  });

  it("describes an exit-multiple terminal value with its implied growth", () => {
    const exit = dcf({
      terminal: {
        ...dcf().terminal,
        method: "exit_multiple",
        growth: null,
        exit_multiple: "12",
        implied_exit_multiple: null,
        implied_growth: "0.0312",
      },
      terminal_share: null,
    });
    expect(terminalTexts(exit)).toEqual({
      method: "Exit multiple 12.0× EV/EBITDA",
      implied: "Implied perpetual growth 3.1%",
      share: null,
    });
  });

  it("marks a stub period as the rest of its year", () => {
    const [stub, full] = dcf().periods;
    expect(periodLabel(stub!)).toBe("FY26E (rest of year)");
    expect(periodLabel(full!)).toBe("FY27E");
  });

  it("writes the price line, or says there is none", () => {
    expect(priceText("172", "2026-11-04")).toBe("Price $172.00 · close of 2026-11-04");
    expect(priceText(null, null)).toBe("No price stored. Refresh the company to load prices.");
  });
});

describe("input texts", () => {
  const pct = (value: string | null) => inputRow({ code: "risk_free_rate", unit: "pct", value });

  it("shows a percent with 1 or 2 decimals, a beta with 2, a multiple with ×", () => {
    expect(inputText(pct("0.04"))).toBe("4.0%");
    expect(inputText(pct("0.025"))).toBe("2.5%");
    expect(inputText(pct("0.0225"))).toBe("2.25%");
    expect(inputText(pct("0.03374198917305102049570611096"))).toBe("3.37%");
    expect(inputText(pct(null))).toBe("");
    expect(inputText(inputRow({ value: "1.2" }))).toBe("1.20");
    expect(inputText(inputRow({ code: "exit_multiple", value: "12" }))).toBe("12.0×");
    expect(inputText(inputRow({ code: "pe_multiple", value: "22.75" }))).toBe("22.75×");
  });

  it("parses typed text to the API's value by unit", () => {
    expect(parseInputText("4.5", "pct")).toEqual({ value: "0.045" });
    expect(parseInputText(" 4.5 % ", "pct")).toEqual({ value: "0.045" });
    expect(parseInputText("-1", "pct")).toEqual({ value: "-0.01" });
    expect(parseInputText("12", "x")).toEqual({ value: "12" });
    expect(parseInputText("12.5×", "x")).toEqual({ value: "12.5" });
    expect(parseInputText("12.5x", "x")).toEqual({ value: "12.5" });
    expect(parseInputText("  ", "pct")).toEqual({ value: null });
    expect(parseInputText("abc", "pct")).toBeNull();
    expect(parseInputText("1e5", "x")).toBeNull();
  });

  it("round-trips the shown text of an own value", () => {
    for (const [value, unit] of [
      ["0.045", "pct"],
      ["0.0225", "pct"],
      ["12.5", "x"],
    ] as const) {
      const row = inputRow({
        code: unit === "x" ? "exit_multiple" : "terminal_growth",
        unit,
        value,
      });
      expect(parseInputText(inputText(row), unit)).toEqual({ value });
    }
  });

  it("builds the PUT row of an edit: the parsed value, null when emptied, nothing when unchanged", () => {
    const own = inputRow({ value: "1.2", own: "1.2", source: "own" });
    expect(inputEdit(own, "1.5")).toEqual({ code: "beta", value: "1.5" });
    expect(inputEdit(own, "")).toEqual({ code: "beta", value: null });
    expect(inputEdit(own, "1.20")).toBeNull();
    expect(inputEdit(own, "1.2")).toBeNull();
    expect(inputEdit(own, "x1")).toBe("invalid");
    const inherited = pct("0.03374198917305102049570611096");
    expect(inputEdit(inherited, "3.37%")).toBeNull();
    expect(inputEdit(inherited, "")).toBeNull();
    expect(inputEdit(inherited, "4")).toEqual({ code: "risk_free_rate", value: "0.04" });
  });

  it("labels the choices", () => {
    expect(
      [
        "wacc",
        "direct",
        "gordon",
        "exit_multiple",
        "off",
        "manual",
        "own_history",
        "peer_median",
      ].map(choiceLabel),
    ).toEqual([
      "WACC",
      "Direct rate",
      "Gordon growth",
      "Exit multiple",
      "Off",
      "Manual",
      "Own history",
      "Peer median",
    ]);
    expect(choiceLabel("other")).toBe("other");
  });

  it("styles and titles a value by its source", () => {
    expect(sourceClass("own")).toBe("");
    expect(sourceClass("base")).toBe("text-muted-foreground italic");
    expect(sourceClass("default")).toBe("text-muted-foreground");
    expect(sourceClass("derived")).toBe("text-muted-foreground");
    expect(sourceTitle(inputRow({ source: "own" }))).toBe("Set in this case");
    expect(sourceTitle(inputRow({ source: "base" }))).toBe("Inherited from Base");
    expect(sourceTitle(inputRow({ source: "default" }))).toBe("Default");
    expect(
      sourceTitle(inputRow({ source: "derived", note: "From the forecast's FY2026 tax rate" })),
    ).toBe("From the forecast's FY2026 tax rate");
  });

  it("names the clear and reset actions by case", () => {
    expect(clearText("base")).toBe("Back to the default");
    expect(clearText("bull")).toBe("Use Base's value");
    expect(clearText("bear")).toBe("Use Base's value");
    expect(resetText("base")).toBe("Every valuation input of Base goes back to its default.");
    expect(resetText("bull")).toBe("Its own inputs are removed; it follows Base again.");
  });
});

describe("display rules", () => {
  const codes = (changes: Record<string, string>) =>
    shownCodes(
      valuationInputs().rows.map((row) =>
        row.code in changes ? { ...row, value: changes[row.code]! } : row,
      ),
    );
  const discount = [
    "discount_rate",
    "risk_free_rate",
    "equity_risk_premium",
    "beta",
    "cost_of_debt",
    "tax_rate",
    "debt_weight",
  ];

  it("WACC hides the direct rate; a direct rate hides the WACC inputs", () => {
    expect(discount.filter((code) => codes({}).has(code))).toEqual(discount.slice(1));
    expect(discount.filter((code) => codes({ discount_method: "direct" }).has(code))).toEqual([
      "discount_rate",
    ]);
    expect(codes({}).has("discount_method")).toBe(true);
  });

  it("Gordon hides the exit multiple; an exit multiple hides the growth", () => {
    expect(codes({}).has("terminal_growth")).toBe(true);
    expect(codes({}).has("exit_multiple")).toBe(false);
    expect(codes({ terminal_method: "exit_multiple" }).has("terminal_growth")).toBe(false);
    expect(codes({ terminal_method: "exit_multiple" }).has("exit_multiple")).toBe(true);
    expect(codes({}).has("mid_year")).toBe(true);
  });

  it("lists the multiple targets in order, with the columns their source uses", () => {
    expect(targets(valuationInputs().rows)).toEqual([
      { code: "pe", label: "P/E" },
      { code: "ev_ebitda", label: "EV/EBITDA" },
      { code: "p_fcf", label: "P/FCF" },
      { code: "ev_sales", label: "EV/Sales" },
    ]);
    expect(targetFields("off")).toEqual({ multiple: false, percentile: false, year: false });
    expect(targetFields("manual")).toEqual({ multiple: true, percentile: false, year: true });
    expect(targetFields("own_history")).toEqual({ multiple: false, percentile: true, year: true });
    expect(targetFields("peer_median")).toEqual({ multiple: false, percentile: false, year: true });
  });
});
