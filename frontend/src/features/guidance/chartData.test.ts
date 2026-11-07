import { describe, expect, it } from "vitest";

import type { CompareOut, GuidanceEntryOut, HistoryPointOut } from "@/api/generated/types.gen";
import { guidanceEntry } from "@/test/context";

import {
  chartMetrics,
  chartPoints,
  defaultChartMetric,
  defaultFreq,
  forecastValues,
  guidanceChart,
} from "./chartData";

const revenue = (overrides: Partial<GuidanceEntryOut>) => guidanceEntry(overrides);

describe("chartMetrics", () => {
  it("lists each metric with latest entries in the frequency once, by label", () => {
    const entries = [
      revenue({ id: 1 }),
      revenue({ id: 2, source: "consensus" }),
      revenue({ id: 3, metric: "eps", label: "EPS", unit: "USD/shares" }),
      revenue({ id: 4, metric: "gross_margin", label: "Gross margin", fiscal_period: "Q1" }),
      revenue({ id: 5, metric: "opex", label: "Opex", latest: false }),
    ];
    expect(chartMetrics(entries, "annual")).toEqual([
      { key: "eps|reported", label: "EPS", unit: "USD/shares" },
      { key: "revenue|reported", label: "Revenue", unit: "USD" },
    ]);
    expect(chartMetrics(entries, "quarterly")).toEqual([
      { key: "gross_margin|reported", label: "Gross margin", unit: "USD" },
    ]);
  });

  it("names the basis only when a metric has both", () => {
    const entries = [revenue({ id: 1 }), revenue({ id: 2, basis: "normalized" })];
    expect(chartMetrics(entries, "annual").map((m) => m.label)).toEqual([
      "Revenue (normalized)",
      "Revenue (reported)",
    ]);
  });
});

describe("defaultFreq / defaultChartMetric", () => {
  it("prefers annual, else quarterly when only quarters are guided", () => {
    expect(defaultFreq([revenue({})])).toBe("annual");
    expect(defaultFreq([revenue({ fiscal_period: "Q2" })])).toBe("quarterly");
  });

  it("prefers reported revenue, else the first metric", () => {
    const eps = { key: "eps|reported", label: "EPS", unit: "USD/shares" };
    const rev = { key: "revenue|reported", label: "Revenue", unit: "USD" };
    expect(defaultChartMetric([eps, rev])).toBe("revenue|reported");
    expect(defaultChartMetric([eps])).toBe("eps|reported");
    expect(defaultChartMetric([])).toBeUndefined();
  });
});

describe("chartPoints", () => {
  it("one point per period in order, with the actual and each source's latest range", () => {
    const entries = [
      revenue({ id: 1, fiscal_year: 2025, latest: false, low: "1", high: "2" }),
      revenue({
        id: 2,
        fiscal_year: 2025,
        low: "100",
        high: "110",
        actual: "112",
        verdict: "beat",
      }),
      revenue({
        id: 3,
        fiscal_year: 2025,
        source: "consensus",
        low: "104",
        high: "108",
        actual: "112",
        verdict: "beat",
      }),
      revenue({ id: 4, fiscal_year: 2024, low: "90", high: "90", actual: "88", verdict: "miss" }),
      revenue({
        id: 5,
        fiscal_year: 2026,
        source: "consensus",
        low: "120",
        high: "130",
        actual: null,
        verdict: "pending",
      }),
      revenue({ id: 6, fiscal_year: 2025, basis: "normalized", low: "0", high: "0" }),
    ];
    expect(chartPoints(entries, "revenue|reported", "annual")).toEqual([
      {
        label: "FY2024",
        actual: 88,
        management: { low: 90, high: 90, mid: 90, verdict: "miss" },
        consensus: null,
        forecast: null,
      },
      {
        label: "FY2025",
        actual: 112,
        management: { low: 100, high: 110, mid: 105, verdict: "beat" },
        consensus: { low: 104, high: 108, mid: 106, verdict: "beat" },
        forecast: null,
      },
      {
        label: "FY2026",
        actual: null,
        management: null,
        consensus: { low: 120, high: 130, mid: 125, verdict: "pending" },
        forecast: null,
      },
    ]);
  });

  it("starts 2 years before the latest actual, older guided years left to the log", () => {
    const year = (fiscal_year: number, value: string): HistoryPointOut => ({
      fiscal_year,
      fiscal_period: "FY",
      value,
    });
    const history = [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024].map((y) =>
      year(y, String(y)),
    );
    const entries = [
      revenue({ id: 1, fiscal_year: 2019, low: "1", high: "3", actual: "2019" }),
      revenue({ id: 2, fiscal_year: 2023, low: "1", high: "3", actual: "2023" }),
      revenue({ id: 3, fiscal_year: 2026, actual: null, verdict: "pending", low: "5", high: "5" }),
    ];
    const points = chartPoints(entries, "revenue|reported", "annual", history, [
      { fiscal_year: 2025, fiscal_period: "FY", value: 7 },
    ]);
    expect(points.map((p) => p.label)).toEqual(["FY2022", "FY2023", "FY2024", "FY2025", "FY2026"]);
    expect(points[0]).toEqual({
      label: "FY2022",
      actual: 2022,
      management: null,
      consensus: null,
      forecast: null,
    });
    expect(points[1]!.management?.mid).toBe(2);
    expect(points.at(-1)!.actual).toBeNull();
  });

  it("starts 4 quarters before the latest actual quarter", () => {
    const history: HistoryPointOut[] = [2022, 2023, 2024].flatMap((y) =>
      (["Q1", "Q2", "Q3", "Q4"] as const).map((q) => ({
        fiscal_year: y,
        fiscal_period: q,
        value: "1",
      })),
    );
    const entries = [
      revenue({ id: 1, fiscal_year: 2023, fiscal_period: "Q2" }),
      revenue({ id: 2, fiscal_year: 2025, fiscal_period: "Q1", actual: null, verdict: "pending" }),
    ];
    const points = chartPoints(entries, "revenue|reported", "quarterly", history);
    expect(points.map((p) => p.label)).toEqual([
      "Q4 FY2023",
      "Q1 FY2024",
      "Q2 FY2024",
      "Q3 FY2024",
      "Q4 FY2024",
      "Q1 FY2025",
    ]);
  });

  it("keeps every period when nothing is reported yet", () => {
    const entries = [
      revenue({ id: 1, fiscal_year: 2026, actual: null, verdict: "pending" }),
      revenue({ id: 2, fiscal_year: 2027, actual: null, verdict: "pending" }),
    ];
    expect(chartPoints(entries, "revenue|reported", "annual").map((p) => p.label)).toEqual([
      "FY2026",
      "FY2027",
    ]);
  });

  it("adds the forecast periods and values of the user's forecast", () => {
    const entries = [revenue({ id: 1, fiscal_year: 2025, actual: "100" })];
    const forecast = [
      { fiscal_year: 2025, fiscal_period: "FY", value: 101 },
      { fiscal_year: 2027, fiscal_period: "FY", value: 130 },
      { fiscal_year: 2026, fiscal_period: "Q1", value: 30 },
    ];
    const points = chartPoints(entries, "revenue|reported", "annual", [], forecast);
    expect(points.map((p) => [p.label, p.actual, p.forecast])).toEqual([
      ["FY2025", 100, 101],
      ["FY2027", null, 130],
    ]);
  });

  it("orders quarters within a year and skips the annual entries", () => {
    const entries = [
      revenue({ id: 1, fiscal_year: 2025, fiscal_period: "Q2" }),
      revenue({ id: 2, fiscal_year: 2024, fiscal_period: "Q4" }),
      revenue({ id: 3, fiscal_year: 2025, fiscal_period: "Q1" }),
      revenue({ id: 4, fiscal_year: 2025, fiscal_period: "FY" }),
    ];
    expect(chartPoints(entries, "revenue|reported", "quarterly").map((p) => p.label)).toEqual([
      "Q4 FY2024",
      "Q1 FY2025",
      "Q2 FY2025",
    ]);
  });
});

describe("forecastValues", () => {
  const compare = (overrides: Partial<CompareOut> = {}): CompareOut => ({
    periods: [
      { key: "FY2025", label: "FY25", fiscal_year: 2025, fiscal_period: "FY", is_forecast: false },
      { key: "FY2026", label: "FY26E", fiscal_year: 2026, fiscal_period: "FY", is_forecast: true },
      { key: "FY2027", label: "FY27E", fiscal_year: 2027, fiscal_period: "FY", is_forecast: true },
    ].map((p) => ({ ...p, period_start: "", period_end: "" })),
    codes: [{ code: "revenue", label: "Revenue", unit: "USD" }],
    cases: [
      { case: "bull", label: "Bull", error: null, values: { revenue: ["1", "9", "9"] } },
      { case: "base", label: "Base", error: null, values: { revenue: ["1", "120", null] } },
    ],
    built_from_quarters: [],
    ...overrides,
  });

  it("reads the base case's forecast periods of the code, skipping gaps and actuals", () => {
    expect(forecastValues(compare(), "revenue")).toEqual([
      { fiscal_year: 2026, fiscal_period: "FY", value: 120 },
    ]);
  });

  it("is empty without a base case, its values or the code", () => {
    expect(forecastValues(compare(), "eps_diluted")).toEqual([]);
    expect(forecastValues(compare({ cases: [] }), "revenue")).toEqual([]);
    expect(forecastValues(undefined, "revenue")).toEqual([]);
  });
});

describe("guidanceChart", () => {
  type Bar = { type: string; name: string; data: unknown[]; barGap?: string };
  const points = chartPoints(
    [
      revenue({ id: 1, low: "380000000000", high: "390000000000", actual: "391035000000" }),
      revenue({
        id: 2,
        fiscal_year: 2025,
        source: "consensus",
        low: "400000000000",
        high: "420000000000",
        actual: null,
        verdict: "pending",
      }),
      revenue({
        id: 3,
        fiscal_year: 2023,
        source: "consensus",
        low: "380000000000",
        high: "380000000000",
        actual: "383285000000",
        verdict: "miss",
      }),
    ],
    "revenue|reported",
    "annual",
    [],
    [{ fiscal_year: 2025, fiscal_period: "FY", value: 415000000000 }],
  );
  const { option, colors } = guidanceChart(points, "USD", "B");
  const series = option.series as Bar[];

  it("draws actual, consensus, guidance and forecast as bars that touch, consensus next to actual", () => {
    expect((option.xAxis as { data: string[] }).data).toEqual(["FY2023", "FY2024", "FY2025"]);
    expect(series.map((s) => [s.type, s.name])).toEqual([
      ["bar", "Actual"],
      ["bar", "Consensus"],
      ["bar", "Guidance"],
      ["bar", "Forecast"],
      ["custom", "Consensus range"],
    ]);
    expect(series[0]!.data).toEqual([383285000000, 391035000000, null]);
    expect(series[1]!.data).toEqual([380000000000, null, 410000000000]);
    expect(series[2]!.data).toEqual([null, 385000000000, null]);
    expect(series[3]!.data).toEqual([null, null, 415000000000]);
    expect(series.filter((s) => s.type === "bar").every((s) => s.barGap === "0%")).toBe(true);
    expect(colors).toEqual(["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--foreground"]);
  });

  it("puts the consensus range on whiskers, none for a point estimate", () => {
    expect(series[4]!.data).toEqual([
      [0, "-", "-"],
      [1, "-", "-"],
      [2, 400000000000, 420000000000],
    ]);
  });

  it("leaves out the series without data, with their colors", () => {
    const only = guidanceChart(points.slice(1, 2), "USD", "B");
    expect((only.option.series as Bar[]).map((s) => s.name)).toEqual(["Actual", "Guidance"]);
    expect(only.colors).toEqual(["--chart-1", "--chart-3"]);
    expect((only.option.legend as { data: string[] }).data).toEqual(["Actual", "Guidance"]);
  });

  it("leaves headroom above the highest value (whiskers included) on clean steps from zero", () => {
    // Highest drawn value: the 420 B whisker; +10% of the 0–420 span = 462 B, up to the 100 B step.
    expect(option.yAxis).toMatchObject({ min: 0, max: 500000000000, interval: 100000000000 });
  });

  it("extends below zero for negative values (capex)", () => {
    const capex = chartPoints(
      [revenue({ id: 1, low: "-11", high: "-10", actual: "-12" })],
      "revenue|reported",
      "annual",
    );
    expect(guidanceChart(capex, null, "B").option.yAxis).toMatchObject({
      min: -15,
      max: 0,
      interval: 5,
    });
  });

  it("formats the axis in the page scale", () => {
    const axis = option.yAxis as { axisLabel: { formatter: (v: number) => string } };
    expect(axis.axisLabel.formatter(391035000000)).toBe("391.0");
  });

  it("shows ranges, the forecast and verdicts colored green or red in the tooltip", () => {
    const tooltip = option.tooltip as { formatter: (p: { dataIndex: number }[]) => string };
    const miss = tooltip.formatter([{ dataIndex: 0 }]);
    expect(miss).toContain("FY2023");
    expect(miss).toContain("Actual: 383.3");
    expect(miss).toContain('Consensus: 380.0 · <span style="color:var(--negative)">Miss</span>');
    const beat = tooltip.formatter([{ dataIndex: 1 }]);
    expect(beat).toContain(
      'Guidance: 380.0 – 390.0 · <span style="color:var(--positive)">Beat</span>',
    );
    expect(beat).not.toContain("Consensus");
    const future = tooltip.formatter([{ dataIndex: 2 }]);
    expect(future).toContain("Actual: —");
    expect(future).toContain("Consensus: 400.0 – 420.0 · Pending");
    expect(future).toContain("Forecast: 415.0");
  });
});
