import { render, screen } from "@testing-library/react";
import type { BarSeriesOption, EChartsOption } from "echarts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Chart } from "@/components/Chart";
import { scoreRow } from "@/test/accountability";

import { HorizonChart } from "./HorizonChart";

vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));
const chart = vi.mocked(Chart);

afterEach(() => vi.clearAllMocks());

const option = () => chart.mock.lastCall![0].option;
const series = (o: EChartsOption) => o.series as BarSeriesOption[];
const values = (s: BarSeriesOption) => (s.data as { value: number | null }[]).map((d) => d.value);

// Snapshot scores: `method` is the case.
const summary = () => [
  scoreRow({ method: "bear", horizon: 1, mape: "0.0900", n: 2 }),
  scoreRow({ method: "base", horizon: 1, mape: "0.0312", n: 2 }),
  scoreRow({ method: "base", horizon: 2, mape: "0.0800", n: 1 }),
  scoreRow({ method: "base", freq: "quarterly", horizon: 1, mape: "0.0200", n: 6 }),
  scoreRow({ method: "base", freq: "quarterly", horizon: 3, mape: "0.0450", n: 4 }),
  scoreRow({ code: "net_income", label: "Net income", method: "base", mape: "0.2" }),
];

describe("HorizonChart", () => {
  it("draws the base case's MAPE by horizon as bars, annual and quarterly as two series", () => {
    render(<HorizonChart summary={summary()} code="revenue" />);

    expect(option().xAxis).toMatchObject({ type: "category", data: ["1", "2", "3"] });
    const [annual, quarterly] = series(option());
    expect([annual!.name, annual!.type, values(annual!)]).toEqual([
      "Annual",
      "bar",
      [0.0312, 0.08, null],
    ]);
    expect([quarterly!.name, values(quarterly!)]).toEqual(["Quarterly", [0.02, null, 0.045]]);
    expect(chart.mock.lastCall![0].ariaLabel).toBe("Revenue: MAPE by horizon, Base case");
  });

  it("puts each bar's n in the tooltip", () => {
    render(<HorizonChart summary={summary()} code="revenue" />);

    const tooltip = option().tooltip as { formatter: (p: unknown) => string };
    const text = tooltip.formatter({
      seriesName: "Quarterly",
      name: "3",
      data: { value: 0.045, n: 4 },
    });
    expect(text).toContain("4.5%");
    expect(text).toContain("n = 4");
    expect(text).toContain("Quarterly, horizon 3");
  });

  it("formats the value axis as a percent", () => {
    render(<HorizonChart summary={summary()} code="revenue" />);

    const axis = option().yAxis as { axisLabel: { formatter: (v: number) => string } };
    expect(axis.axisLabel.formatter(0.125)).toBe("12.5%");
  });

  it("draws one series when only one frequency is scored", () => {
    render(<HorizonChart summary={summary()} code="net_income" />);

    expect(series(option()).map((s) => s.name)).toEqual(["Annual"]);
  });

  it("falls back to the first scored case when there is no base case", () => {
    render(
      <HorizonChart
        summary={[
          scoreRow({ method: "bull", mape: "0.05" }),
          scoreRow({ method: "bear", mape: "0.09" }),
        ]}
        code="revenue"
      />,
    );

    expect(values(series(option())[0]!)).toEqual([0.05]);
    expect(chart.mock.lastCall![0].ariaLabel).toBe("Revenue: MAPE by horizon, Bull case");
  });

  it.each([
    ["no row for the line", [scoreRow({ code: "net_income" })]],
    ["only null MAPEs", [scoreRow({ method: "base", mape: null })]],
  ])("says there is nothing to chart with %s", (_name, rows) => {
    render(<HorizonChart summary={rows} code="revenue" />);

    expect(screen.getByText("No data to chart.")).toHaveClass("text-muted-foreground");
    expect(chart).not.toHaveBeenCalled();
  });
});
