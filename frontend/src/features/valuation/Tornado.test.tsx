import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BarSeriesOption, EChartsOption } from "echarts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { tornado, tornadoBar } from "@/test/valuation";

import { Tornado } from "./Tornado";

// jsdom cannot draw a canvas: the tests read the `option` handed to ECharts.
vi.mock("echarts-for-react/esm/core", () => ({ default: vi.fn(() => null) }));
const { default: EChartsCore } = await import("echarts-for-react/esm/core");
const echarts = vi.mocked(EChartsCore);

const lastOption = () => {
  const props = echarts.mock.lastCall?.[0] as unknown as { option: EChartsOption };
  return props.option;
};
const lastSeries = () => lastOption().series as BarSeriesOption[];
const categories = () => (lastOption().yAxis as { data: string[] }).data;

// Twelve bars that run, by range, then the fixture's error bar.
function many() {
  const bars = Array.from({ length: 12 }, (_, i) =>
    tornadoBar({
      code: `d${i}`,
      label: `Driver ${i}`,
      low_change: `-${12 - i}`,
      high_change: `${12 - i}`,
    }),
  );
  return tornado({ bars: [...bars, ...tornado().bars.filter((bar) => bar.error !== null)] });
}

beforeEach(() => {
  document.documentElement.style.setProperty("--chart-1", "#0000aa");
  document.documentElement.style.setProperty("--chart-2", "#aaaa00");
});

afterEach(() => {
  document.documentElement.removeAttribute("style");
  vi.clearAllMocks();
});

describe("Tornado", () => {
  it("lists the bars with their steps in the API's order, the largest at the top", () => {
    render(<Tornado tornado={tornado()} />);
    expect(categories()).toEqual([
      "Discount rate ±0.5 pt",
      "Revenue growth ±1 pt",
      "Terminal growth ±0.5 pt",
      "Receivable days ±5 days",
    ]);
    // A category axis draws its first item at the bottom unless inverted.
    expect(lastOption().yAxis).toMatchObject({ type: "category", inverse: true });
    expect(
      screen.getByRole("img", { name: "Tornado: change in DCF value per share by input" }),
    ).toBeInTheDocument();
  });

  it("keeps the legend above the bars, clear of the first one", () => {
    render(<Tornado tornado={tornado()} />);
    expect(lastOption().legend).toMatchObject({ top: 0, data: ["Input lower", "Input higher"] });
    expect((lastOption().grid as { top: number }).top).toBeGreaterThanOrEqual(32);
  });

  it("draws the lower and higher input as two bars from 0, in two neutral hues", () => {
    render(<Tornado tornado={tornado()} />);
    expect(lastSeries().map((series) => series.name)).toEqual(["Input lower", "Input higher"]);
    expect(lastSeries()[0]).toMatchObject({ type: "bar", data: [11, -7.37, -6, 0.53] });
    expect(lastSeries()[1]).toMatchObject({ type: "bar", data: [-9.3, 7.73, 7.2, -0.53] });
    // Both bars of an input share one row and start at 0 (no stacking).
    expect(lastSeries()[1]).toMatchObject({ barGap: "-100%" });
    expect(lastSeries().some((series) => "stack" in series)).toBe(false);
    expect(lastSeries()[0]?.markLine).toMatchObject({ data: [{ xAxis: 0 }] });
    // Neutral hues: red and green would read as bad and good, not as the input's direction.
    expect(lastOption().color).toEqual(["#0000aa", "#aaaa00"]);
  });

  it("names the x axis with the base value and labels changes with their sign", () => {
    render(<Tornado tornado={tornado()} />);
    const xAxis = lastOption().xAxis as {
      name: string;
      axisLabel: { formatter: (value: number) => string };
    };
    expect(xAxis.name).toBe("Change in value per share vs $132.47");
    expect(xAxis.axisLabel.formatter(-10)).toBe("−$10.00");
    expect(xAxis.axisLabel.formatter(5)).toBe("+$5.00");
  });

  it("shows each input's values at either step in the tooltip", () => {
    render(<Tornado tornado={tornado()} />);
    const tooltip = lastOption().tooltip as {
      formatter: (params: { dataIndex: number }[]) => string;
    };
    expect(tooltip.formatter([{ dataIndex: 1 }])).toBe(
      "Revenue growth −1 pt: $125.10 · +1 pt: $140.20",
    );
    expect(tooltip.formatter([{ dataIndex: 0 }])).toBe(
      "Discount rate −0.5 pt: $143.47 · +0.5 pt: $123.17",
    );
  });

  it("escapes the tooltip's text, which ECharts renders as HTML", () => {
    render(<Tornado tornado={tornado({ bars: [tornadoBar({ label: "<b>Odd</b>" })] })} />);
    const tooltip = lastOption().tooltip as {
      formatter: (params: { dataIndex: number }[]) => string;
    };
    expect(tooltip.formatter([{ dataIndex: 0 }])).toContain("&lt;b&gt;Odd&lt;/b&gt;");
  });

  it("lists the bars that could not run under the chart", () => {
    render(<Tornado tornado={tornado()} />);
    const list = screen.getByRole("list", { name: "Inputs that could not run" });
    expect(within(list).getByText("Could not run: Buybacks: r must exceed g")).toBeInTheDocument();
    expect(categories()).not.toContain("Buybacks ±10%");
  });

  it("shows the top 10 bars, then all of them on request", async () => {
    render(<Tornado tornado={many()} />);
    expect(categories()).toHaveLength(10);
    expect(categories()[0]).toBe("Driver 0 ±1 pt");
    await userEvent.click(screen.getByRole("button", { name: "Show all 12" }));
    expect(categories()).toHaveLength(12);
    await userEvent.click(screen.getByRole("button", { name: "Show top 10" }));
    expect(categories()).toHaveLength(10);
  });

  it("has no toggle with 10 bars or fewer", () => {
    render(<Tornado tornado={tornado()} />);
    expect(screen.queryByRole("button", { name: /Show/ })).not.toBeInTheDocument();
  });

  it("says so when no input could run, with no chart", () => {
    render(
      <Tornado tornado={tornado({ bars: tornado().bars.filter((bar) => bar.error !== null) })} />,
    );
    expect(screen.getByText("No input could be moved.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Could not run: Buybacks: r must exceed g")).toBeInTheDocument();
  });
});
