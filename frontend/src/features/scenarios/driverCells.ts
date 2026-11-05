import type {
  DriverGridOut,
  DriverRowIn,
  DriverRowOut,
  GridPeriodOut,
} from "@/api/generated/types.gen";
import {
  formatRatio,
  formatValue,
  parseScaled,
  parseThreshold,
  toScaledText,
  toThresholdText,
} from "@/lib/format";
import type { Scale } from "@/lib/scale";

// The driver grid's text and edits. The backend resolves every value; this module only formats,
// parses and builds the PUT row of an edit.

export type DriverUnit = DriverRowOut["unit"];
export type DriverMode = DriverRowIn["kind"]; // "value", or "offset" (vs Base)

const DASH = "—";
const MUTED = "text-muted-foreground";

const shortYear = (year: number) => String(year % 100).padStart(2, "0");

/** A period's name in text: "FY26" for a year, "Q1 FY26" for a quarter. */
export const periodName = (year: number, period: GridPeriodOut["fiscal_period"]) =>
  period === "FY" ? `FY${shortYear(year)}` : `${period} FY${shortYear(year)}`;

// |number| with 1 decimal, negatives in parentheses (the app's convention).
function oneDecimal(number: number): string {
  const text = Math.abs(number).toFixed(1);
  return number < 0 && Number(text) !== 0 ? `(${text})` : text;
}

/** A driver value by unit: pct "5.3%", days "61.3", USD in the page scale; null "—". */
export function formatDriverValue(value: string | null, unit: DriverUnit, scale: Scale): string {
  if (value === null) return DASH;
  if (unit === "pct") return formatRatio(value, "pct");
  if (unit === "days") return oneDecimal(Number(value));
  return formatValue(value, "USD", scale);
}

/** An offset on Base, signed: "+3.0 pts", "-2.5 days", "+2,000" (USD in the page scale). */
export function formatDriverOffset(offset: string, unit: DriverUnit, scale: Scale): string {
  const number = Number(offset);
  let text: string;
  if (unit === "pct") text = `${Math.abs(number * 100).toFixed(1)} pts`;
  else if (unit === "days") text = `${Math.abs(number).toFixed(1)} days`;
  else text = formatValue(String(Math.abs(number)), "USD", scale);
  if (/^[0.,]+(?: |$)/.test(text)) return text; // rounds to zero: no sign
  return `${number < 0 ? "-" : "+"}${text}`;
}

/**
 * Text typed in a driver cell, to the API's decimal string: pct as a percent with an optional
 * "%" ("5" → "0.05"), days plain, USD in the page scale. One leading "+" is allowed (offsets).
 * Null for blank or malformed text; the caller treats blank as "clear".
 */
export function parseDriverText(text: string, unit: DriverUnit, scale: Scale): string | null {
  let body = text.trim();
  if (body.startsWith("+")) body = body.slice(1);
  if (unit === "pct") return parseThreshold(body.replace(/\s*%$/, ""), "pct");
  if (unit === "days") return parseThreshold(body, "x");
  return parseScaled(body, scale);
}

/** The exact inverse of `parseDriverText`, for the cell editor's starting text. */
export function toDriverText(value: string, unit: DriverUnit, scale: Scale): string {
  if (unit === "USD") return toScaledText(value, scale);
  return toThresholdText(value, unit === "pct" ? "pct" : "x");
}

export type DriverGridRow =
  | { id: string; type: "group"; label: string }
  | { id: string; type: "driver"; driver: DriverRowOut };

/** The grid's rows: a heading row before each group, then its drivers, in the API's order. */
export function toDriverRows(grid: DriverGridOut): DriverGridRow[] {
  const rows: DriverGridRow[] = [];
  let group: string | null = null;
  for (const driver of grid.rows) {
    if (driver.group !== group) {
      group = driver.group;
      rows.push({ id: `group:${group}`, type: "group", label: group });
    }
    rows.push({ id: `driver:${driver.code}`, type: "driver", driver });
  }
  return rows;
}

export interface ForecastCell {
  text: string;
  classes: string[];
  title: string; // names the source
  editText: string; // the editor's starting text
  /** The year's mode makes this cell read-only (a roll-up, or a quarter of an annually set year). */
  locked?: true;
  /** A small caption under the number, set with `locked`: "Quarters" (a roll-up) or "FY26" (a quarter of that annual year). */
  note?: string;
}

type GridColumns = Pick<
  DriverGridOut,
  "freq" | "history_periods" | "forecast_periods" | "forecast_years" | "year_modes"
>;

// The forecast years set by quarter (FR-FCST-13): their annual cell is a roll-up and their quarters
// hold the drivers.
function byQuarterYears(grid: Pick<DriverGridOut, "year_modes">): Set<number> {
  return new Set(grid.year_modes.filter((m) => m.mode === "quarterly").map((m) => m.fiscal_year));
}

function defaultTitle(row: DriverRowOut, { history_periods }: GridColumns): string {
  const window = history_periods.slice(-3);
  const averaged = row.history.slice(-3).some((value) => value !== null);
  if (!averaged || window.length === 0) return "Default: no history, the driver's fallback";
  const first = periodName(window[0]!.fiscal_year, "FY");
  const last = periodName(window.at(-1)!.fiscal_year, "FY");
  return `Default: mean of ${first}–${last}`;
}

/**
 * A forecast cell of `row` at forecast column `index` of `grid` (a year or a quarter). In vs Base
 * mode a column with an offset shows the offset; every other cell shows the resolved value, styled
 * by its source: `own` plain, `base` muted italic, `default` and `year` (a quarter taking its
 * year's value) muted, a required driver with no value "Set" in red.
 */
export function forecastCell(
  row: DriverRowOut,
  index: number,
  mode: DriverMode,
  scale: Scale,
  grid: GridColumns,
): ForecastCell {
  const period = grid.forecast_periods[index];
  const year = period && grid.year_modes.find((m) => m.fiscal_year === period.fiscal_year);
  if (period && year?.in_span) {
    const name = periodName(period.fiscal_year, "FY");
    if (grid.freq === "annual" && year.mode === "quarterly") {
      // The roll-up of the year's quarters: the backend's figure, not editable here.
      const figure = row.rollup[grid.forecast_years.indexOf(period.fiscal_year)] ?? null;
      return {
        text: formatDriverValue(figure, row.unit, scale),
        classes: [MUTED],
        title: `Built from Q1–Q4. Switch ${name} to Annual to set it here.`,
        editText: "",
        locked: true,
        note: "Quarters",
      };
    }
    if (grid.freq === "quarterly" && year.mode === "annual") {
      return {
        ...sourcedCell(row, index, mode, scale, grid),
        title: `${name} is set annually. Switch it to By quarter to edit quarters.`,
        locked: true,
        note: name,
      };
    }
  }
  return sourcedCell(row, index, mode, scale, grid);
}

function sourcedCell(
  row: DriverRowOut,
  index: number,
  mode: DriverMode,
  scale: Scale,
  grid: GridColumns,
): ForecastCell {
  const value = row.values[index] ?? null;
  const source = row.sources[index] ?? null;
  const own = row.kind === mode ? (row.own[index] ?? null) : null;

  if (mode === "offset" && own !== null) {
    const offset = formatDriverOffset(own, row.unit, scale);
    const sign = offset.startsWith("-") ? "-" : "+";
    return {
      text: offset,
      classes: [],
      // The resolved value is unknown while the offset's save is pending (`withDriverRows`).
      title:
        `Base ${sign} ${offset.replace(/^[+-]/, "")}` +
        (value === null ? "" : ` = ${formatDriverValue(value, row.unit, scale)}`),
      editText: toDriverText(own, row.unit, scale),
    };
  }
  const editText = mode === "value" && value !== null ? toDriverText(value, row.unit, scale) : "";
  if (source === null) {
    return { text: "Set", classes: ["text-negative"], title: "Required: set a value", editText };
  }
  if (value === null) {
    return { text: "Flat", classes: [MUTED], title: "Default: the line is held flat", editText };
  }
  const text = formatDriverValue(value, row.unit, scale);
  if (source === "base") {
    return { text, classes: [MUTED, "italic"], title: "Inherited from Base", editText };
  }
  if (source === "default") {
    return { text, classes: [MUTED], title: defaultTitle(row, grid), editText };
  }
  if (source === "year") {
    const column = grid.forecast_periods[index];
    const title = column
      ? `From ${periodName(column.fiscal_year, "FY")} (annual)`
      : "From the year";
    return { text, classes: [MUTED], title, editText };
  }
  return { text, classes: [], title: "Set in this scenario", editText };
}

/** An empty PUT row of `freq` in `kind`: it drops the driver's own values of that frequency. */
export function driverClear(
  code: string,
  kind: DriverMode,
  freq: DriverGridOut["freq"],
): DriverRowIn {
  return freq === "quarterly"
    ? { driver_code: code, kind, freq, values: [] }
    : { driver_code: code, kind, values: [] };
}

/**
 * The PUT row for an edit of forecast column `index` of `grid` to `value` (null: the cell was
 * emptied): the row's own values of `mode` in the grid's columns (years, or quarters in a
 * quarterly row), with that column replaced or dropped. Stored values of another kind are not kept
 * (one driver stores one kind).
 */
export function driverEdit(
  grid: Pick<DriverGridOut, "freq" | "forecast_periods" | "year_modes">,
  row: DriverRowOut,
  mode: DriverMode,
  index: number,
  value: string | null,
): DriverRowIn {
  const byQuarter = byQuarterYears(grid);
  const values = grid.forecast_periods.flatMap(({ fiscal_year, fiscal_period }, i) => {
    // A year set by quarter takes no annual value: the API refuses one, and its stored annual value
    // is kept out of sight.
    if (grid.freq === "annual" && byQuarter.has(fiscal_year)) return [];
    let own = i === index ? value : row.kind === mode ? (row.own[i] ?? null) : null;
    // A quarterly row replaces the driver's quarters and must give every quarter of a by-quarter
    // year a value (the API refuses a gap): those not edited keep their current figure.
    if (own === null && grid.freq === "quarterly" && byQuarter.has(fiscal_year)) {
      own = quarterFiller(row, i, mode);
    }
    if (own === null) return [];
    return [
      grid.freq === "quarterly"
        ? { fiscal_year, fiscal_period, value: own }
        : { fiscal_year, value: own },
    ];
  });
  return { ...driverClear(row.code, mode, grid.freq), values };
}

// A by-quarter quarter's value when its row is rewritten: an offset of 0 (it follows Base), or the
// value it resolves to now; null when there is none (a line held flat, a required driver unset).
function quarterFiller(row: DriverRowOut, index: number, mode: DriverMode): string | null {
  return mode === "offset" ? "0" : (row.values[index] ?? null);
}

/** Whether the cell at forecast column `index` can be emptied: not a quarter of a by-quarter year. */
export function canClear(
  grid: Pick<DriverGridOut, "freq" | "forecast_periods" | "year_modes">,
  index: number,
): boolean {
  const period = grid.forecast_periods[index];
  return !(grid.freq === "quarterly" && period && byQuarterYears(grid).has(period.fiscal_year));
}

/**
 * Whether `row` has own values the grid on screen can drop. The annual grid ignores the stored
 * annual value of a by-quarter year; the quarterly grid offers no reset while a year is set by
 * quarter, because a quarter of such a year cannot be cleared.
 */
export function canReset(
  grid: Pick<DriverGridOut, "freq" | "forecast_periods" | "year_modes">,
  row: DriverRowOut,
): boolean {
  const byQuarter = byQuarterYears(grid);
  if (
    grid.freq === "quarterly" &&
    grid.forecast_periods.some((p) => byQuarter.has(p.fiscal_year))
  ) {
    return false;
  }
  return row.own.some(
    (value, i) =>
      value !== null &&
      !(grid.freq === "annual" && byQuarter.has(grid.forecast_periods[i]?.fiscal_year ?? -1)),
  );
}

/**
 * The quarterly row of a mode switch (Value ↔ vs Base): it drops the driver's own quarter values,
 * except in a year set by quarter, whose quarters must stay given: at an offset of 0 (following
 * Base) or at the value they resolve to now.
 */
export function quarterSwitchRow(
  grid: Pick<DriverGridOut, "forecast_periods" | "year_modes">,
  row: DriverRowOut,
  mode: DriverMode,
): DriverRowIn {
  const byQuarter = byQuarterYears(grid);
  const values = grid.forecast_periods.flatMap(({ fiscal_year, fiscal_period }, i) => {
    const value = byQuarter.has(fiscal_year) ? quarterFiller(row, i, mode) : null;
    return value === null ? [] : [{ fiscal_year, fiscal_period, value }];
  });
  return { ...driverClear(row.code, mode, "quarterly"), values };
}

/** The PUT row that drops every own value of `row` in `grid`'s frequency (back to inherited or default). */
export function driverReset(grid: Pick<DriverGridOut, "freq">, row: DriverRowOut): DriverRowIn {
  return driverClear(row.code, row.kind ?? "value", grid.freq);
}
