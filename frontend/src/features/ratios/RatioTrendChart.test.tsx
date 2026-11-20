import { render, screen } from "@testing-library/react";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Chart } from "@/components/Chart";
import { ratios } from "@/test/analysis";

import { RatioTrendChart } from "./RatioTrendChart";

vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));
const chart = vi.mocked(Chart);

afterEach(() => vi.clearAllMocks());

const drawn = () =>
  chart.mock.calls.map(([props]) => ({
    ariaLabel: props.ariaLabel,
    option: props.option,
  }));
const series = (option: EChartsOption) => option.series as LineSeriesOption[];

describe("RatioTrendChart", () => {
  it("draws one chart per unit of the chosen ratios, each ratio a line over the periods", () => {
    render(
      <RatioTrendChart payload={ratios()} codes={["gross_margin", "debt_to_equity", "roe"]} />,
    );

    const charts = drawn();
    expect(charts.map((c) => c.ariaLabel)).toEqual([
      "Ratio trends, percent",
      "Ratio trends, multiple",
    ]);
    const [pct, x] = charts;
    expect(pct!.option.xAxis).toMatchObject({ type: "category", data: ["FY2023", "FY2024"] });
    expect(series(pct!.option).map((s) => [s.name, s.type, s.data])).toEqual([
      ["Gross margin", "line", [0.441311, 0.462063]],
      ["Return on equity", "line", [-0.034, 1.645935]],
    ]);
    expect(series(x!.option).map((s) => [s.name, s.data])).toEqual([
      ["Debt / equity", [2.8401, 2.4512]],
    ]);
  });

  it("labels the value axis in the unit's format", () => {
    render(<RatioTrendChart payload={ratios()} codes={["gross_margin", "eps_diluted", "dso"]} />);

    const formatters = drawn().map(
      (c) =>
        (c.option.yAxis as { axisLabel: { formatter: (v: number) => string } }).axisLabel.formatter,
    );
    expect(formatters.map((f, at) => f([0.25, 6.11, 45][at]!))).toEqual(["25.0%", "6.11", "45"]);
    expect(drawn().map((c) => c.ariaLabel)).toEqual([
      "Ratio trends, percent",
      "Ratio trends, USD per share",
      "Ratio trends, days",
    ]);
  });

  it("keeps a gap for a missing value", () => {
    const payload = ratios();
    payload.rows[0]!.values = [null, "0.46"];
    render(<RatioTrendChart payload={payload} codes={["gross_margin"]} />);

    expect(series(drawn()[0]!.option)[0]!.data).toEqual([null, 0.46]);
  });

  it("says there is nothing to chart when the chosen ratios have no value", () => {
    render(<RatioTrendChart payload={ratios()} codes={["interest_coverage"]} />);

    expect(screen.getByText("No data to chart.")).toHaveClass("text-muted-foreground");
    expect(chart).not.toHaveBeenCalled();
  });

  it("ignores a code the table does not have", () => {
    render(<RatioTrendChart payload={ratios()} codes={["nope", "dso"]} />);

    expect(drawn().map((c) => c.ariaLabel)).toEqual(["Ratio trends, days"]);
  });

  it("draws nothing when no ratio is chosen", () => {
    const { container } = render(<RatioTrendChart payload={ratios()} codes={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
