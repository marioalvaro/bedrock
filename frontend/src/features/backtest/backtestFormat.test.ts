import type { LineSeriesOption } from "echarts";
import { describe, expect, it } from "vitest";

import { backtest, backtestSummary, noBacktest, scoreRow } from "@/test/accountability";

import {
  backtestStatus,
  failedRuns,
  formatAuditValue,
  formatLocalTime,
  formatStat,
  horizonChartOption,
  methodLabel,
  metricOptions,
  resolveSelection,
  scoreTableRows,
  utcDate,
} from "./backtestFormat";

const DASH = "—";
const MINUS = "−";
const NO_ASK = { metric: null, freq: null, stat: null };

describe("utcDate", () => {
  it("reads the API's offset-less timestamps as UTC", () => {
    expect(utcDate("2026-11-10T12:30:00").toISOString()).toBe("2026-11-10T12:30:00.000Z");
  });

  it("keeps an explicit offset", () => {
    expect(utcDate("2026-11-10T12:30:00Z").toISOString()).toBe("2026-11-10T12:30:00.000Z");
    expect(utcDate("2026-11-10T12:30:00+02:00").toISOString()).toBe("2026-11-10T10:30:00.000Z");
  });
});

describe("formatLocalTime", () => {
  it("prints the instant in the browser's time zone", () => {
    expect(formatLocalTime("2026-11-10T12:30:00")).toBe(
      new Date(Date.UTC(2026, 10, 10, 12, 30)).toLocaleString("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
      }),
    );
  });
});

describe("formatAuditValue", () => {
  it.each([
    [null, "pct", DASH],
    [null, null, DASH],
    ["0.05", "pct", "5.0%"],
    ["0.0725", "pct", "7.25%"],
    ["-0.02", "pct", "(2.0%)"],
    ["0", "pct", "0.0%"],
    ["45", "days", "45 days"],
    ["45.5", "days", "45.5 days"],
    ["1500000000", "USD", "1.5B"],
    ["-25000000", "USD", "(25.0M)"],
    ["annual", null, "annual"],
    ["arima", "pct", "arima"],
    ["12.5", "x", "12.5"],
    ["2030", "year", "2030"],
  ])("%s in %s reads %s", (value, unit, text) => {
    expect(formatAuditValue(value, unit)).toBe(text);
  });

  it.each([
    ["offset:0.01", "pct", "+1.0 pts"],
    ["offset:-0.0325", "pct", `${MINUS}3.25 pts`],
    ["offset:0", "pct", "0.0 pts"],
    ["offset:2", "days", "+2 days"],
    ["offset:-1.5", "days", `${MINUS}1.5 days`],
    ["offset:1500000000", "USD", "+1.5B"],
    ["offset:-25000000", "USD", `${MINUS}25.0M`],
    ["offset:0.5", null, "+0.5"],
    ["offset:abc", "pct", "offset:abc"],
  ])("the offset %s in %s reads %s", (value, unit, text) => {
    expect(formatAuditValue(value, unit)).toBe(text);
  });
});

describe("formatStat", () => {
  it.each([
    ["mape", "0.0512", "5.1%"],
    ["mape", null, DASH],
    ["bias", "0.0213", "+2.1%"],
    ["bias", "-0.03", "-3.0%"],
    ["bias", null, DASH],
    ["hit_rate", "0.8", "80%"],
    ["hit_rate", null, DASH],
  ] as const)("%s of %s reads %s", (stat, value, text) => {
    expect(formatStat(stat, value)).toBe(text);
  });
});

describe("methodLabel", () => {
  it.each([
    ["auto", "Auto"],
    ["mean", "Mean (3 yr)"],
    ["arima", "ARIMA"],
    ["ets", "ETS"],
    ["blend", "Blend"],
    ["stl", "STL"],
    ["base", "Base"],
    ["bull", "Bull"],
    ["bear", "Bear"],
    ["later", "later"],
  ])("%s reads %s", (code, label) => expect(methodLabel(code)).toBe(label));
});

describe("metricOptions", () => {
  it("lists each line, then each driver, once", () => {
    expect(metricOptions(backtestSummary())).toEqual({
      lines: [{ code: "revenue", label: "Revenue" }],
      drivers: [{ code: "gross_margin", label: "Gross margin" }],
    });
  });

  it("is empty for an empty summary", () => {
    expect(metricOptions([])).toEqual({ lines: [], drivers: [] });
  });
});

describe("resolveSelection", () => {
  it("is null for an empty summary", () => {
    expect(resolveSelection([], NO_ASK)).toBeNull();
  });

  it("defaults to annual revenue MAPE", () => {
    expect(resolveSelection(backtestSummary(), NO_ASK)).toEqual({
      code: "revenue",
      label: "Revenue",
      kind: "line",
      freq: "annual",
      stat: "mape",
      hitRateAvailable: false,
    });
  });

  it("falls back from an unknown metric to revenue", () => {
    const asked = { ...NO_ASK, metric: "nope" };
    expect(resolveSelection(backtestSummary(), asked)?.code).toBe("revenue");
  });

  it("falls back to the first metric when revenue was never scored", () => {
    const summary = [scoreRow({ code: "cash", label: "Cash" })];
    expect(resolveSelection(summary, NO_ASK)?.code).toBe("cash");
  });

  it("falls back from unknown freq and stat values", () => {
    const asked = { metric: "revenue", freq: "weekly", stat: "rmse" };
    expect(resolveSelection(backtestSummary(), asked)).toMatchObject({
      freq: "annual",
      stat: "mape",
    });
  });

  it("keeps a line's quarterly choice and forces a driver to annual", () => {
    expect(resolveSelection(backtestSummary(), { ...NO_ASK, freq: "quarterly" })?.freq).toBe(
      "quarterly",
    );
    expect(
      resolveSelection(backtestSummary(), { ...NO_ASK, metric: "gross_margin", freq: "quarterly" })
        ?.freq,
    ).toBe("annual");
  });

  it("offers the hit rate only when a row of the selection has a range", () => {
    const asked = { metric: "gross_margin", freq: null, stat: "hit_rate" };
    expect(resolveSelection(backtestSummary(), asked)).toMatchObject({
      stat: "hit_rate",
      hitRateAvailable: true,
    });
  });

  it("drops an asked hit rate the selection cannot show", () => {
    expect(resolveSelection(backtestSummary(), { ...NO_ASK, stat: "hit_rate" })).toMatchObject({
      stat: "mape",
      hitRateAvailable: false,
    });
  });

  it("judges the hit rate on the selected frequency alone", () => {
    const summary = [
      scoreRow({ hit_rate: "1", n_range: 3 }),
      scoreRow({ freq: "quarterly", n_range: 0 }),
    ];
    expect(resolveSelection(summary, { ...NO_ASK, freq: "quarterly" })?.hitRateAvailable).toBe(
      false,
    );
  });
});

const selection = (over: object = {}) => ({
  ...resolveSelection(backtestSummary(), NO_ASK)!,
  ...over,
});

describe("scoreTableRows", () => {
  it("lays methods out in their order, by horizon, with n in the title", () => {
    expect(scoreTableRows(backtestSummary(), selection())).toEqual({
      horizons: [1, 2],
      rows: [
        {
          method: "auto",
          label: "Auto",
          cells: [
            { horizon: 1, text: "5.1%", title: "n = 10" },
            { horizon: 2, text: "12.5%", title: "n = 8" },
          ],
        },
        {
          method: "arima",
          label: "ARIMA",
          cells: [
            { horizon: 1, text: "7.0%", title: "n = 9" },
            { horizon: 2, text: DASH, title: undefined },
          ],
        },
      ],
    });
  });

  it("formats the chosen stat", () => {
    const { rows } = scoreTableRows(backtestSummary(), selection({ stat: "bias" }));
    expect(rows[1]!.cells[0]!.text).toBe("-3.0%");
  });

  it("keeps to the selected frequency", () => {
    const table = scoreTableRows(backtestSummary(), selection({ freq: "quarterly" }));
    expect(table.horizons).toEqual([1]);
    expect(table.rows.map((row) => row.method)).toEqual(["auto"]);
  });

  it("orders a snapshot's cases Base, Bull, Bear", () => {
    const summary = ["bear", "bull", "base"].map((method) => scoreRow({ method }));
    const table = scoreTableRows(summary, selection());
    expect(table.rows.map((row) => row.label)).toEqual(["Base", "Bull", "Bear"]);
  });

  it("is empty when nothing matches", () => {
    expect(scoreTableRows([], selection())).toEqual({ horizons: [], rows: [] });
  });
});

describe("horizonChartOption", () => {
  const seriesOf = (over: object = {}) =>
    horizonChartOption(backtestSummary(), selection(over)).series as LineSeriesOption[];

  it("draws one line per method, in percent, by horizon", () => {
    const option = horizonChartOption(backtestSummary(), selection());
    expect((option.xAxis as { data: string[] }).data).toEqual(["1", "2"]);
    expect(seriesOf().map((s) => [s.name, s.type])).toEqual([
      ["Auto", "line"],
      ["ARIMA", "line"],
    ]);
    expect(seriesOf()[0]!.data![0]).toBeCloseTo(5.12);
    expect(seriesOf()[0]!.data![1]).toBeCloseTo(12.5);
  });

  it("leaves a gap for a horizon a method has no score at", () => {
    expect(seriesOf()[1]!.data![1]).toBeNull();
  });

  it("names the axis after the frequency", () => {
    const axis = (over: object) =>
      (horizonChartOption(backtestSummary(), selection(over)).xAxis as { name: string }).name;
    expect(axis({})).toBe("Years ahead");
    expect(axis({ freq: "quarterly" })).toBe("Quarters ahead");
  });

  it("prints the tooltip in the stat's format", () => {
    const option = horizonChartOption(backtestSummary(), selection({ stat: "bias" }));
    const format = (option.tooltip as { valueFormatter: (value: unknown) => string })
      .valueFormatter;
    expect(format(2.13)).toBe("+2.1%");
    expect(format(null)).toBe(DASH);
  });
});

describe("backtestStatus", () => {
  const now = new Date(Date.UTC(2026, 10, 10, 14, 0));

  it("counts the origins and the runs that could not run", () => {
    expect(backtestStatus(backtest(), now)).toBe(
      "Last run 2h ago · 2 origins, 1 method run could not run",
    );
  });

  it("uses the plural for several failures and none", () => {
    const fails = (error: string | null) =>
      backtest({
        origins: [
          {
            as_of_date: "2024-11-01",
            runs: [
              { method: "auto", error },
              { method: "ets", error },
            ],
          },
        ],
      });
    expect(backtestStatus(fails("x"), now)).toBe(
      "Last run 2h ago · 1 origin, 2 method runs could not run",
    );
    expect(backtestStatus(fails(null), now)).toBe(
      "Last run 2h ago · 1 origin, 0 method runs could not run",
    );
  });
});

describe("failedRuns", () => {
  it("lists date, method and error for each failed run", () => {
    expect(failedRuns(backtest())).toEqual(["2024-11-01 · ARIMA: Set these drivers: gross_margin"]);
  });

  it("is empty before a run", () => {
    expect(failedRuns(noBacktest())).toEqual([]);
  });
});
