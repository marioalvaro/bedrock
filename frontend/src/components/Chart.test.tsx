import { act, render, screen } from "@testing-library/react";
import type { EChartsOption } from "echarts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setTheme } from "@/lib/theme";

import { Chart } from "./Chart";

// jsdom cannot draw a canvas: the tests read the `option` the wrapper hands to ECharts.
vi.mock("echarts-for-react/esm/core", () => ({
  default: vi.fn(() => null),
}));

const { default: EChartsCore } = await import("echarts-for-react/esm/core");
const echarts = vi.mocked(EChartsCore);

const lastOption = () => {
  const props = echarts.mock.lastCall?.[0] as unknown as { option: EChartsOption };
  return props.option;
};

const original = window.matchMedia;

function setReducedMotion(reduced: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)" && reduced,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
}

function setTokens(tokens: Record<string, string>) {
  for (const [name, value] of Object.entries(tokens)) {
    document.documentElement.style.setProperty(name, value);
  }
}

const LIGHT = {
  "--chart-1": "#111111",
  "--chart-2": "#222222",
  "--chart-3": "#333333",
  "--chart-4": "#444444",
  "--chart-5": "#555555",
  "--foreground": "#000000",
  "--muted-foreground": "#777777",
  "--border": "#dddddd",
};

const OPTION: EChartsOption = {
  xAxis: { type: "category", data: ["FY26E", "FY27E"] },
  yAxis: { type: "value" },
  series: [{ type: "line", name: "Base", data: [1, 2] }],
};

beforeEach(() => {
  setReducedMotion(false);
  setTokens(LIGHT);
  setTheme("light");
});

afterEach(() => {
  window.matchMedia = original;
  document.documentElement.removeAttribute("style");
  vi.clearAllMocks();
});

describe("Chart", () => {
  it("colors the series from the --chart-1..5 tokens", () => {
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    expect(lastOption().color).toEqual(["#111111", "#222222", "#333333", "#444444", "#555555"]);
  });

  it("colors the series from the given tokens when the caller names them", () => {
    setTokens({ "--positive": "#0a0a0a", "--negative": "#0b0b0b" });
    render(
      <Chart option={OPTION} ariaLabel="Revenue by case" colors={["--positive", "--negative"]} />,
    );
    expect(lastOption().color).toEqual(["#0a0a0a", "#0b0b0b"]);
  });

  it("hands ECharts an rgb color for an oklch token, as Chrome's canvas keeps oklch()", () => {
    // Chrome's `fillStyle` getter returns "oklch(…)" unchanged; only the painted pixel is sRGB.
    // ECharts cannot parse oklch() for its hover color, so the hovered line vanished.
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      () =>
        ({
          fillStyle: "",
          fillRect: () => {},
          clearRect: () => {},
          getImageData: () => ({ data: new Uint8ClampedArray([18, 52, 86, 255]) }),
        }) as unknown as CanvasRenderingContext2D,
    );
    setTokens({ "--chart-1": "oklch(0.6 0.1 250)", "--border": "oklch(1 0 0 / 10%)" });
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    expect((lastOption().color as string[])[0]).toBe("rgba(18, 52, 86, 1)");
    getContext.mockRestore();
  });

  it("keeps the caller's series and axes", () => {
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    expect(lastOption().series).toEqual(OPTION.series);
    expect(lastOption().xAxis).toMatchObject({ type: "category", data: ["FY26E", "FY27E"] });
  });

  it("takes text from --foreground and axis labels and lines from --muted-foreground", () => {
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    const option = lastOption();
    expect(option.textStyle).toMatchObject({ color: "#000000" });
    expect(option.xAxis).toMatchObject({
      axisLabel: { color: "#777777" },
      axisLine: { lineStyle: { color: "#777777" } },
    });
    expect(option.yAxis).toMatchObject({
      axisLabel: { color: "#777777" },
      splitLine: { lineStyle: { color: "#dddddd" } },
    });
    expect(option.legend).toMatchObject({ textStyle: { color: "#000000" } });
  });

  it("lets the caller's legend text style win", () => {
    render(
      <Chart
        option={{ ...OPTION, legend: { textStyle: { fontSize: 10 } } }}
        ariaLabel="Revenue by scenario"
      />,
    );
    expect(lastOption().legend).toMatchObject({ textStyle: { color: "#000000", fontSize: 10 } });
  });

  it("re-reads the tokens when the theme changes", () => {
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    setTokens({ "--chart-1": "#abcdef", "--foreground": "#fafafa" });
    act(() => setTheme("dark"));
    expect((lastOption().color as string[])[0]).toBe("#abcdef");
    expect(lastOption().textStyle).toMatchObject({ color: "#fafafa" });
  });

  it("animates unless the OS asks to reduce motion", () => {
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    expect(lastOption().animation).toBe(true);
  });

  it("turns animation off under reduced motion", () => {
    setReducedMotion(true);
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    expect(lastOption().animation).toBe(false);
  });

  it("labels the chart for assistive technology", () => {
    render(<Chart option={OPTION} ariaLabel="Revenue by scenario" />);
    expect(screen.getByRole("img", { name: "Revenue by scenario" })).toBeInTheDocument();
  });
});
