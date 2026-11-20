import { render, screen } from "@testing-library/react";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Sparkline } from "./Sparkline";

// jsdom cannot draw a canvas: the tests read the `option` and size handed to ECharts.
vi.mock("echarts-for-react/esm/core", () => ({
  default: vi.fn(() => null),
}));

const { default: EChartsCore } = await import("echarts-for-react/esm/core");
const echarts = vi.mocked(EChartsCore);

const lastProps = () =>
  echarts.mock.lastCall?.[0] as unknown as { option: EChartsOption; style: { height: number } };
const series = () => (lastProps().option.series as LineSeriesOption[])[0]!;

afterEach(() => vi.clearAllMocks());

describe("Sparkline", () => {
  it("draws the values as one line, oldest first, keeping a gap for a missing year", () => {
    render(<Sparkline values={[null, "0.553", "0.548", "0.564"]} label="ROIC trend" />);

    expect(series().type).toBe("line");
    expect(series().data).toEqual([null, 0.553, 0.548, 0.564]);
    expect(series().connectNulls).toBe(false);
    expect(series().showSymbol).toBe(false);
  });

  it("marks the point of a metric with a single year, which a line alone cannot show", () => {
    render(<Sparkline values={[null, null, "7.46"]} label="EPS trend" />);

    expect(series().showSymbol).toBe(true);
  });

  it("has no axes, no tooltip and no legend", () => {
    render(<Sparkline values={["1", "2"]} label="Revenue trend" />);

    const { option } = lastProps();
    expect(option.xAxis).toMatchObject({ show: false });
    expect(option.yAxis).toMatchObject({ show: false, scale: true });
    expect(option.tooltip).toBeUndefined();
    expect(option.legend).toMatchObject({ show: false });
    expect(option.grid).toMatchObject({ top: 2, bottom: 2, left: 0, right: 0 });
  });

  it("is 80 by 20 pixels and named for screen readers", () => {
    render(<Sparkline values={["1", "2"]} label="Revenue trend" />);

    const image = screen.getByRole("img", { name: "Revenue trend" });
    expect(image.parentElement).toHaveStyle({ width: "80px" });
    expect(lastProps().style.height).toBe(20);
  });

  it.each([
    ["no values", []],
    ["only missing values", [null, null]],
  ])("draws nothing for %s", (_name, values) => {
    const { container } = render(<Sparkline values={values} label="Empty trend" />);

    expect(container).toBeEmptyDOMElement();
    expect(echarts).not.toHaveBeenCalled();
  });
});
