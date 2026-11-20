import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Chart } from "@/components/Chart";
import { setScale } from "@/lib/scale";
import { forecastIncome } from "@/test/scenarios";

import { ForecastHistoryChart } from "./ForecastHistoryChart";

vi.mock("@/components/Chart", () => ({ Chart: vi.fn(() => null) }));
const chart = vi.mocked(Chart);

beforeEach(() => setScale("M"));
afterEach(() => vi.clearAllMocks());

const props = () => chart.mock.lastCall![0];
const series = (o: EChartsOption) => o.series as LineSeriesOption[];

describe("ForecastHistoryChart", () => {
  it("draws revenue by default: the actuals solid, the forecast dashed from the last actual", () => {
    render(<ForecastHistoryChart data={forecastIncome()} />);

    const { option, ariaLabel, colors } = props();
    expect(ariaLabel).toBe("Revenue: actuals and forecast");
    expect(option.xAxis).toMatchObject({
      data: forecastIncome().periods.map((period) => period.label),
    });
    const [actual, forecast] = series(option);
    expect([actual!.name, actual!.data, actual!.lineStyle?.type]).toEqual([
      "Actual",
      [391035000000, 416161000000, null, null],
      "solid",
    ]);
    expect([forecast!.name, forecast!.data, forecast!.lineStyle?.type]).toEqual([
      "Forecast",
      [null, 416161000000, 425900000000, 435870000000],
      "dashed",
    ]);
    // One line in one color: the dash tells the forecast apart.
    expect(colors).toEqual(["--chart-1", "--chart-1"]);
  });

  it("charts the line chosen in the select", async () => {
    render(<ForecastHistoryChart data={forecastIncome()} />);

    const select = screen.getByRole("combobox", { name: "Chart line" });
    expect([...(select as HTMLSelectElement).options].map((o) => o.text)).toEqual([
      "Revenue",
      "Gross profit",
      "Net income",
    ]);
    await userEvent.selectOptions(select, "net_income");

    expect(props().ariaLabel).toBe("Net income: actuals and forecast");
    expect(series(props().option)[0]!.data).toEqual([93736000000, 112010000000, null, null]);
  });

  it("formats the axis in the page scale", () => {
    render(<ForecastHistoryChart data={forecastIncome()} />);

    const axis = props().option.yAxis as { axisLabel: { formatter: (v: number) => string } };
    expect(axis.axisLabel.formatter(425900000000)).toBe("425,900");
  });

  it("starts on the first line when there is no revenue line", () => {
    const data = forecastIncome();
    data.rows = data.rows.filter((row) => row.code !== "revenue");
    render(<ForecastHistoryChart data={data} />);

    expect(props().ariaLabel).toBe("Gross profit: actuals and forecast");
  });

  it("draws the actuals alone when no period is a forecast", () => {
    const data = forecastIncome();
    data.periods = data.periods.map((period) => ({ ...period, is_forecast: false }));
    render(<ForecastHistoryChart data={data} />);

    expect(series(props().option).map((s) => s.name)).toEqual(["Actual"]);
  });

  it("says there is nothing to chart when no line has a value", () => {
    const data = forecastIncome();
    data.rows = data.rows.map((row) => ({ ...row, values: row.values.map(() => null) }));
    render(<ForecastHistoryChart data={data} />);

    expect(screen.getByText("No data to chart.")).toHaveClass("text-muted-foreground");
    expect(chart).not.toHaveBeenCalled();
  });
});
