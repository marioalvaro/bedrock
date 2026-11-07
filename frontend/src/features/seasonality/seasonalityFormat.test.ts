// The Seasonality tab's texts and chart options: pure layout of the backend's decomposition.
import type { LineSeriesOption } from "echarts";
import { describe, expect, it } from "vitest";

import { seasonality } from "@/test/seasonality";

import {
  FACTOR_ROWS,
  OBSERVED_COLORS,
  RESIDUAL_COLORS,
  SEASONAL_COLORS,
  factorRows,
  formatSignedAmount,
  formatSignedPct,
  formatStrength,
  seasonalityCharts,
} from "./seasonalityFormat";

const MINUS = "−";

describe("formatStrength", () => {
  it("prints 2 decimals with its scale", () => {
    expect(formatStrength(0.9769)).toBe("Seasonal strength 0.98 · 0 = none, 1 = strong");
    expect(formatStrength(0)).toBe("Seasonal strength 0.00 · 0 = none, 1 = strong");
    expect(formatStrength(1)).toBe("Seasonal strength 1.00 · 0 = none, 1 = strong");
  });
});

describe("formatSignedAmount", () => {
  it("prints USD in the page scale, signed with a true minus", () => {
    expect(formatSignedAmount(16028972000, "USD", "M")).toBe("+16,029");
    expect(formatSignedAmount(-5134170000, "USD", "M")).toBe(`${MINUS}5,134`);
    expect(formatSignedAmount(16028972000, "USD", "B")).toBe("+16.0");
    expect(formatSignedAmount(-5134170000, "USD", "K")).toBe(`${MINUS}5,134,170`);
  });

  it("scales share counts like USD", () => {
    expect(formatSignedAmount(-2500000, "shares", "M")).toBe(`${MINUS}3`);
  });

  it("keeps per-share amounts unscaled with 2 decimals", () => {
    expect(formatSignedAmount(0.4321, "USD/shares", "M")).toBe("+0.43");
    expect(formatSignedAmount(-0.1, "USD/shares", "B")).toBe(`${MINUS}0.10`);
  });

  it("drops the sign of a value that rounds to zero", () => {
    expect(formatSignedAmount(0, "USD", "M")).toBe("0");
    expect(formatSignedAmount(-400000, "USD", "M")).toBe("0");
    expect(formatSignedAmount(-0.001, "USD/shares", "M")).toBe("0.00");
  });
});

describe("formatSignedPct", () => {
  it("prints a fraction as a signed percent with 1 decimal", () => {
    expect(formatSignedPct(0.2305)).toBe("+23.1%");
    expect(formatSignedPct(-0.0738)).toBe(`${MINUS}7.4%`);
  });

  it("drops the sign at zero and prints null as a dash", () => {
    expect(formatSignedPct(-0.0001)).toBe("0.0%");
    expect(formatSignedPct(null)).toBe("—");
  });
});

describe("factorRows", () => {
  it("has an Amount row in the page scale and a % of trend row, Q1..Q4", () => {
    expect(factorRows(seasonality(), "M")).toEqual([
      { label: "Amount", cells: [`${MINUS}5,134`, `${MINUS}4,949`, `${MINUS}5,945`, "+16,029"] },
      { label: "% of trend", cells: [`${MINUS}7.4%`, `${MINUS}7.1%`, `${MINUS}8.6%`, "+23.1%"] },
    ]);
    expect(FACTOR_ROWS).toEqual(["Amount", "% of trend"]);
  });

  it("puts each factor under its quarter, whatever the payload order", () => {
    const view = seasonality();
    const rows = factorRows({ ...view, factors: [...view.factors].reverse() }, "M");
    expect(rows[0]!.cells[3]).toBe("+16,029");
  });

  it("prints a missing pct as a dash", () => {
    const view = seasonality();
    const factors = view.factors.map((f) => ({ ...f, pct: null }));
    expect(factorRows({ ...view, factors }, "M")[1]!.cells).toEqual(["—", "—", "—", "—"]);
  });
});

describe("seasonalityCharts", () => {
  const charts = seasonalityCharts(seasonality(), "M");
  const series = (option: typeof charts.observed) => option.series as LineSeriesOption[];
  const labels = seasonality().periods.map((p) => p.label);

  it("shares the period labels as x in all three charts, each on its tick", () => {
    for (const option of [charts.observed, charts.seasonal, charts.residual]) {
      expect(option.xAxis).toMatchObject({ type: "category", data: labels, boundaryGap: false });
    }
  });

  it("lines the three plots up: one left margin wide enough for every y label", () => {
    const grids = [charts.observed, charts.seasonal, charts.residual].map(
      (option) => option.grid as { left: number; containLabel?: boolean },
    );
    const left = grids[0]!.left;
    for (const grid of grids) expect(grid).toMatchObject({ left, containLabel: false });
    // The widest label is around "(10,000.0)" or "100,000.0" in M; in K it is 1,000 times wider.
    const inK = seasonalityCharts(seasonality(), "K").observed.grid as { left: number };
    expect(left).toBeGreaterThanOrEqual(60);
    expect(inK.left).toBeGreaterThan(left);
  });

  it("shows a legend only on the two-series chart", () => {
    expect(charts.observed.legend).toMatchObject({ data: ["Observed", "Trend"] });
    expect(charts.seasonal.legend).toEqual({ show: false });
    expect(charts.residual.legend).toEqual({ show: false });
  });

  it("draws observed and trend in the page scale", () => {
    const [observed, trend] = series(charts.observed);
    expect(observed).toMatchObject({ type: "line", name: "Observed" });
    expect(trend).toMatchObject({ type: "line", name: "Trend" });
    expect(observed!.data).toHaveLength(12);
    expect(observed!.data![0]).toBeCloseTo(57799);
    expect(trend!.data![11]).toBeCloseTo(78085.065);
    expect(series(charts.observed)).toHaveLength(2);
  });

  it("draws the seasonal component alone", () => {
    expect(series(charts.seasonal)).toHaveLength(1);
    expect(series(charts.seasonal)[0]).toMatchObject({ type: "line", name: "Seasonal" });
    expect(series(charts.seasonal)[0]!.data![3]).toBeCloseTo(14891.521);
  });

  it("draws the residual as a line with points", () => {
    const [residual] = series(charts.residual);
    expect(series(charts.residual)).toHaveLength(1);
    expect(residual).toMatchObject({ type: "line", name: "Residual", symbol: "circle" });
    expect(residual!.data![0]).toBeCloseTo(93.028);
  });

  it("colors observed, trend, seasonal and residual from their tokens", () => {
    expect(OBSERVED_COLORS).toEqual(["--chart-1", "--chart-2"]);
    expect(SEASONAL_COLORS).toEqual(["--chart-3"]);
    expect(RESIDUAL_COLORS).toEqual(["--muted-foreground"]);
  });

  it("keeps per-share values unscaled", () => {
    const eps = seasonalityCharts(
      seasonality({ unit: "USD/shares", observed: Array(12).fill(1.25) }),
      "B",
    );
    expect(series(eps.observed)[0]!.data![0]).toBe(1.25);
  });

  it("formats the axis labels in the unit", () => {
    const axis = charts.observed.yAxis as { axisLabel: { formatter: (n: number) => string } };
    expect(axis.axisLabel.formatter(-1234.5)).toBe("(1,234.5)");
  });

  it("formats the tooltip values in the unit", () => {
    const tooltip = charts.seasonal.tooltip as {
      trigger: string;
      valueFormatter: (v: unknown) => string;
    };
    expect(tooltip.trigger).toBe("axis");
    expect(tooltip.valueFormatter(14891.521)).toBe("14,891.5");
    expect(tooltip.valueFormatter(undefined)).toBe("—");
  });

  it("handles a decomposition with no quarters", () => {
    const empty = seasonalityCharts(
      seasonality({ periods: [], observed: [], trend: [], seasonal: [], residual: [] }),
      "M",
    );
    expect(empty.observed.xAxis).toMatchObject({ data: [] });
    expect(series(empty.observed)[0]!.data).toEqual([]);
  });
});
