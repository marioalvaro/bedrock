import { render, screen } from "@testing-library/react";
import type { BarSeriesOption, EChartsOption, LineSeriesOption } from "echarts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Chart } from "@/components/Chart";
import { capitalAllocation } from "@/test/analysis";

import { CapitalBars } from "./CapitalBars";

vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));
const chart = vi.mocked(Chart);

afterEach(() => vi.clearAllMocks());

const option = () => chart.mock.lastCall![0].option;
const series = (o: EChartsOption) => o.series as (BarSeriesOption | LineSeriesOption)[];

describe("CapitalBars", () => {
  it("stacks capex, acquisitions, buybacks and dividends as returned, with CFO as a line", () => {
    render(<CapitalBars data={capitalAllocation()} />);

    expect(option().xAxis).toMatchObject({ type: "category", data: ["FY2023", "FY2024"] });
    expect(series(option()).map((s) => [s.name, s.type, s.stack, s.data])).toEqual([
      ["Capital expenditures", "bar", "uses", [-10959000000, -9447000000]],
      ["Acquisitions", "bar", "uses", [null, null]],
      ["Buybacks", "bar", "uses", [-77550000000, -94949000000]],
      ["Dividends", "bar", "uses", [-15025000000, -15234000000]],
      ["Cash from operations", "line", undefined, [110543000000, 118254000000]],
    ]);
    expect(chart.mock.lastCall![0].ariaLabel).toBe("Capital allocation by period");
  });

  it("formats the axis and tooltip in the chosen scale", () => {
    render(<CapitalBars data={capitalAllocation()} />);

    const axis = option().yAxis as { axisLabel: { formatter: (v: number) => string } };
    expect(axis.axisLabel.formatter(-94949000000)).toBe("(94,949)");
  });

  it("leaves out a line the payload does not have", () => {
    const data = capitalAllocation();
    data.rows = data.rows.filter((row) => row.code !== "acquisitions" && row.code !== "cfo");
    render(<CapitalBars data={data} />);

    expect(series(option()).map((s) => s.name)).toEqual([
      "Capital expenditures",
      "Buybacks",
      "Dividends",
    ]);
  });

  it("says there is nothing to chart when no charted line has a value", () => {
    const data = capitalAllocation();
    data.rows = data.rows.map((row) => ({ ...row, values: row.values.map(() => null) }));
    render(<CapitalBars data={data} />);

    expect(screen.getByText("No data to chart.")).toHaveClass("text-muted-foreground");
    expect(chart).not.toHaveBeenCalled();
  });
});
