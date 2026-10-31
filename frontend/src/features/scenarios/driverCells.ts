import type { DriverGridOut, DriverRowIn, DriverRowOut } from "@/api/generated/types.gen";
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

/** An actual year's column header: 2024 → "FY24A". */
export const historyLabel = (year: number) => `FY${shortYear(year)}A`;

/** A forecast year's column header: 2027 → "FY27E". */
export const forecastLabel = (year: number) => `FY${shortYear(year)}E`;

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
}

function defaultTitle(row: DriverRowOut, historyYears: number[]): string {
  const window = historyYears.slice(-3);
  const averaged = row.history.slice(-3).some((value) => value !== null);
  if (!averaged || window.length === 0) return "Default: no history, the driver's fallback";
  const first = `FY${shortYear(window[0]!)}`;
  const last = `FY${shortYear(window.at(-1)!)}`;
  return `Default: mean of ${first}–${last}`;
}

/**
 * A forecast cell of `row` at forecast index `index`. In vs Base mode a year with an offset
 * shows the offset; every other cell shows the resolved value, styled by its source: `own` plain,
 * `base` muted italic, `default` muted, a required driver with no value "Set" in red.
 */
export function forecastCell(
  row: DriverRowOut,
  index: number,
  mode: DriverMode,
  scale: Scale,
  historyYears: number[],
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
    return { text, classes: [MUTED], title: defaultTitle(row, historyYears), editText };
  }
  return { text, classes: [], title: "Set in this scenario", editText };
}

/**
 * The PUT row for an edit of `year` to `value` (null: the cell was emptied): the row's own values
 * of `mode` in the forecast years, with that year replaced or dropped. Stored values of another
 * kind are not kept (one driver stores one kind).
 */
export function driverEdit(
  row: DriverRowOut,
  mode: DriverMode,
  forecastYears: number[],
  year: number,
  value: string | null,
): DriverRowIn {
  const values = forecastYears.flatMap((fiscalYear, index) => {
    const own = fiscalYear === year ? value : row.kind === mode ? (row.own[index] ?? null) : null;
    return own === null ? [] : [{ fiscal_year: fiscalYear, value: own }];
  });
  return { driver_code: row.code, kind: mode, values };
}

/** The PUT row that drops every own value of `row` (back to inherited or default). */
export function driverReset(row: DriverRowOut): DriverRowIn {
  return { driver_code: row.code, kind: row.kind ?? "value", values: [] };
}
