import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption, XAXisComponentOption, YAXisComponentOption } from "echarts";
import EChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";

import { usePrefersReducedMotion } from "@/lib/motion";
import { useTheme, type Theme } from "@/lib/theme";

// Only what the app draws is bundled (line charts with axes, legend and tooltip).
echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const SERIES_TOKENS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5"];

// ECharts parses colors itself (hover shades) and knows no oklch(), and Chrome's canvas keeps
// "oklch(…)" in `fillStyle`: paint one pixel and read it back, which is always sRGB. Without a
// canvas (jsdom) the token is kept.
function toCanvasColor(color: string): string {
  const context = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  if (!context || color === "") return color;
  context.clearRect(0, 0, 1, 1);
  context.fillStyle = color;
  context.fillRect(0, 0, 1, 1);
  const [r = 0, g = 0, b = 0, a = 255] = context.getImageData(0, 0, 1, 1).data;
  return `rgba(${r}, ${g}, ${b}, ${Math.round((a / 255) * 1000) / 1000})`;
}

function readToken(name: string): string {
  return toCanvasColor(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
}

interface Palette {
  series: string[];
  text: string;
  muted: string;
  border: string;
}

// The tokens of `theme`: the theme store switches the `.dark` class before it notifies, so the
// computed tokens are already the new theme's when this runs (the argument keys the memo).
function readPalette(theme: Theme, seriesTokens: string[]): Palette {
  void theme;
  return {
    series: seriesTokens.map(readToken),
    text: readToken("--foreground"),
    muted: readToken("--muted-foreground"),
    border: readToken("--border"),
  };
}

type Axis = XAXisComponentOption | YAXisComponentOption;

// The palette's colors on one axis (or each of a list), keeping the caller's settings.
function colorAxis<T extends Axis>(axis: T | T[] | undefined, palette: Palette): T | T[] {
  const paint = (one: T): T => ({
    ...one,
    axisLabel: { color: palette.muted, ...one.axisLabel },
    axisLine: { ...one.axisLine, lineStyle: { color: palette.muted, ...one.axisLine?.lineStyle } },
    splitLine: {
      ...one.splitLine,
      lineStyle: { color: palette.border, ...one.splitLine?.lineStyle },
    },
  });
  if (Array.isArray(axis)) return axis.map(paint);
  return paint((axis ?? {}) as T);
}

interface ChartProps {
  option: EChartsOption;
  ariaLabel: string;
  height?: number;
  colors?: string[]; // color tokens by series position, instead of --chart-1..5
}

/**
 * The app's one ECharts wrapper: series colors from `--chart-1..5` (or the `colors` tokens), text and axes from
 * `--foreground` / `--muted-foreground` / `--border` (re-read when the theme changes), and no
 * animation when the OS asks for less motion.
 */
export function Chart({ option, ariaLabel, height = 260, colors = SERIES_TOKENS }: ChartProps) {
  const theme = useTheme();
  const reduced = usePrefersReducedMotion();

  // `colors` is a module-level constant at every caller, so the memo holds across renders.
  const palette = useMemo(() => readPalette(theme, colors), [theme, colors]);

  const themed = useMemo<EChartsOption>(
    () => ({
      ...option,
      color: palette.series,
      animation: !reduced,
      textStyle: { color: palette.text, ...option.textStyle },
      legend: {
        ...(option.legend as object),
        textStyle: {
          color: palette.text,
          ...(option.legend as { textStyle?: object } | undefined)?.textStyle,
        },
      },
      xAxis: colorAxis(option.xAxis as XAXisComponentOption | XAXisComponentOption[], palette),
      yAxis: colorAxis(option.yAxis as YAXisComponentOption | YAXisComponentOption[], palette),
    }),
    [option, palette, reduced],
  );

  return (
    <div role="img" aria-label={ariaLabel}>
      <EChartsCore echarts={echarts} option={themed} notMerge style={{ height, width: "100%" }} />
    </div>
  );
}
