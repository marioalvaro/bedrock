import type { Scale } from "./scale";

const DASH = "—";

const DIVISORS: Record<Scale, number> = { K: 1e3, M: 1e6, B: 1e9 };
const SCALE_WORDS: Record<Scale, string> = { K: "thousands", M: "millions", B: "billions" };

// Formats |number| with fixed decimals; negatives go in parentheses, and a value
// that rounds to zero never shows a sign.
function formatNumber(number: number, decimals: number, suffix = ""): string {
  const text = Math.abs(number).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  const isZero = Number(text.replaceAll(",", "")) === 0;
  return number < 0 && !isZero ? `(${text}${suffix})` : `${text}${suffix}`;
}

export function formatValue(value: string | null, unit: string, scale: Scale): string {
  if (value === null) return DASH;
  const number = Number(value);
  if (unit === "USD/shares") return formatNumber(number, 2);
  return formatNumber(number / DIVISORS[scale], scale === "B" ? 1 : 0);
}

/**
 * A chart value (already in the page scale, see `scaledNumber`) for its tooltip and axis: 1
 * decimal, 2 for per-share units (EPS), grouped, negatives in parentheses; null "—".
 */
export function formatChartNumber(value: number | null, unit: string): string {
  if (value === null) return DASH;
  return formatNumber(value, unit === "USD/shares" ? 2 : 1);
}

/**
 * A value as a plain number for a chart axis: USD and share counts divided into the page scale
 * (as `formatValue` shows them), every other unit unchanged; null stays null.
 */
export function scaledNumber(value: string | null, unit: string, scale: Scale): number | null {
  if (value === null) return null;
  const number = Number(value);
  return unit === "USD" || unit === "shares" ? number / DIVISORS[scale] : number;
}

/**
 * The inverse of `formatValue` for a USD amount typed in the page scale: "-25" in M →
 * "-25000000". Accepts an optional leading "-" or surrounding parentheses for a negative,
 * "," thousands separators, a decimal point and surrounding blanks. Returns the amount in
 * USD units as a plain decimal string, scaled exactly (no float arithmetic), with no
 * exponent, no leading zeros, no trailing fractional zeros and no "-0"; null for blank or
 * malformed text.
 */
export function parseScaled(text: string, scale: Scale): string | null {
  let body = text.trim();
  let negative = false;
  if (body.startsWith("(") && body.endsWith(")")) {
    negative = true;
    body = body.slice(1, -1);
  } else if (body.startsWith("-")) {
    negative = true;
    body = body.slice(1);
  }
  // Grouping commas must be well formed ("1,234"), so "1,23" is rejected.
  const match = /^(\d{1,3}(?:,\d{3})+|\d+)?(?:\.(\d+))?$/.exec(body);
  if (!match || (match[1] === undefined && match[2] === undefined)) return null;
  const whole = (match[1] ?? "").replaceAll(",", "");
  const shift = Math.log10(DIVISORS[scale]);
  const fraction = (match[2] ?? "").padEnd(shift, "0");
  const integer = (whole + fraction.slice(0, shift)).replace(/^0+/, "");
  const rest = fraction.slice(shift).replace(/0+$/, "");
  if (integer === "" && rest === "") return "0";
  const digits = `${integer || "0"}${rest ? `.${rest}` : ""}`;
  return negative ? `-${digits}` : digits;
}

/**
 * The exact inverse of `parseScaled`, for prefilling the edit form: a USD-units decimal string
 * as plain text in the page scale ("-25500000" in M → "-25.5"). No float arithmetic, no
 * separators, no trailing fractional zeros. A string in exponent form is returned unchanged.
 */
export function toScaledText(units: string, scale: Scale): string {
  // Exponent form ("1E-7", from the backend's Decimal.normalize) is left as is, not garbled.
  if (/e/i.test(units)) return units;
  const negative = units.startsWith("-");
  const [whole = "", fraction = ""] = units.replace(/^[-+]/, "").split(".");
  const shift = Math.log10(DIVISORS[scale]);
  const padded = whole.padStart(shift + 1, "0");
  const head = padded.slice(0, padded.length - shift).replace(/^0+(?=\d)/, "");
  const tail = (padded.slice(padded.length - shift) + fraction).replace(/0+$/, "");
  const text = tail ? `${head}.${tail}` : head;
  return negative && text !== "0" ? `-${text}` : text;
}

/** "FY" → "FY2024", "Q1" → "Q1 FY2024". */
export function formatFiscalPeriod(fiscalYear: number, fiscalPeriod: string): string {
  return fiscalPeriod === "FY" ? `FY${fiscalYear}` : `${fiscalPeriod} FY${fiscalYear}`;
}

/**
 * A split ratio (new shares per old share, a plain decimal string) as the Overview shows it:
 * "4" → "4-for-1", "0.1" → "1-for-10", "1.5" → "3-for-2" (the smallest whole-number pair).
 */
export function formatSplitRatio(ratio: string): string {
  const value = Number(ratio);
  if (!Number.isFinite(value) || value <= 0) return ratio;
  // Smallest denominator whose numerator is a whole number within 1e-6 (covers 0.3333333333).
  for (let old = 1; old <= 1000; old++) {
    const nextShares = Math.round(value * old);
    if (nextShares >= 1 && Math.abs(value * old - nextShares) <= 1e-6) {
      return `${nextShares}-for-${old}`;
    }
  }
  return `${value}-for-1`;
}

// Ratios arrive as fractions (0.05 = 5 %).
export function formatPercent(value: string | null): string {
  if (value === null) return DASH;
  return formatNumber(Number(value) * 100, 1, "%");
}

interface DecimalParts {
  negative: boolean;
  whole: string;
  fraction: string;
}

// Splits typed decimal text (parseScaled's grammar) into sign, whole and fraction digits; null
// when blank or malformed. `lenient` also accepts a leading "+" and no grouping, for API levels.
function splitDecimal(text: string, lenient = false): DecimalParts | null {
  let body = text.trim();
  let negative = false;
  if (body.startsWith("(") && body.endsWith(")")) {
    negative = true;
    body = body.slice(1, -1);
  } else if (body.startsWith("-") || (lenient && body.startsWith("+"))) {
    negative = body.startsWith("-");
    body = body.slice(1);
  }
  const match = /^(\d{1,3}(?:,\d{3})+|\d+)?(?:\.(\d+))?$/.exec(body);
  if (!match || (match[1] === undefined && match[2] === undefined)) return null;
  return { negative, whole: (match[1] ?? "").replaceAll(",", ""), fraction: match[2] ?? "" };
}

// Moves the decimal point `places` to the right (negative: left) by digit shuffling, then
// canonicalises: no leading zeros, no trailing fractional zeros, no "-0".
function shiftDecimal({ negative, whole, fraction }: DecimalParts, places: number): string {
  let digits = whole + fraction;
  let point = whole.length + places;
  if (point < 0) {
    digits = "0".repeat(-point) + digits;
    point = 0;
  } else if (point > digits.length) {
    digits = digits.padEnd(point, "0");
  }
  const integer = digits.slice(0, point).replace(/^0+/, "");
  const rest = digits.slice(point).replace(/0+$/, "");
  if (integer === "" && rest === "") return "0";
  const text = `${integer || "0"}${rest ? `.${rest}` : ""}`;
  return negative ? `-${text}` : text;
}

export type RatioUnit = "pct" | "x" | "days" | "USD/shares" | "USD";
export type ThresholdUnit = "pct" | "x";

/**
 * A ratio by its unit: `pct` (a fraction) as a percent with 1 decimal ("12.3%"), `x` like
 * `formatMultiple` ("12.3x"), `days` with 0 decimals ("45"), `USD/shares` with 2 decimals
 * ("6.11"), `USD` compact ("118.9B"). Negatives in parentheses, null "—".
 */
export function formatRatio(value: string | null, unit: RatioUnit): string {
  if (value === null) return DASH;
  const number = Number(value);
  if (unit === "pct") return formatNumber(number * 100, 1, "%");
  if (unit === "x") return formatNumber(number, 1, "x");
  if (unit === "USD") return formatCompact(value);
  return formatNumber(number, unit === "days" ? 0 : 2);
}

/**
 * An input of a ratio in its cell details: amounts and share counts compact ("600.0M"), the
 * rest by their unit as `formatRatio`, and `points` (earnings growth) with one decimal ("100.0
 * pts"). Null "—".
 */
export function formatInput(value: string | null, unit: string): string {
  if (value === null) return DASH;
  if (unit === "USD" || unit === "shares") return formatCompact(value);
  if (unit === "points") return formatNumber(Number(value), 1, " pts");
  return formatRatio(value, unit as RatioUnit);
}

/**
 * A ratio as a CSV cell: like `formatRatio` but with a plain minus sign, no thousands separators
 * and no "x" suffix (`pct` "-2.8%", `x` "12.3", `days` "45", `USD/shares` "6.11", `USD` whole
 * dollars "118923000000"); null "".
 */
export function formatCsvRatio(value: string | null, unit: RatioUnit): string {
  if (value === null) return "";
  const number = Number(value);
  if (unit === "pct") return csvNumber(number * 100, 1, "%");
  if (unit === "x") return csvNumber(number, 1);
  return csvNumber(number, unit === "days" || unit === "USD" ? 0 : 2);
}

/**
 * A QoE threshold as typed in Settings, to the API's level: a `pct` level is typed as a percent
 * and returned as an exact fraction ("5" → "0.05", "12.5" → "0.125", "-3" → "-0.03"); an `x`
 * level is returned as typed ("0.80" → "0.8"). The grammar is `parseScaled`'s (a leading "-" or
 * parentheses, well-formed "," groups, a decimal point, surrounding blanks; no "+" or exponent),
 * the result a plain decimal string with no exponent, leading zeros, trailing fractional zeros
 * or "-0". Null for blank or malformed text (the caller treats blank as "no level").
 */
export function parseThreshold(text: string, unit: ThresholdUnit): string | null {
  const parts = splitDecimal(text);
  if (parts === null) return null;
  return shiftDecimal(parts, unit === "pct" ? -2 : 0);
}

/**
 * The exact inverse of `parseThreshold`, for prefilling a Settings input: "0.05" pct → "5",
 * "0.125" pct → "12.5", "0.8" x → "0.8", "0" → "0". No float arithmetic, no separators, no
 * trailing fractional zeros; an exponent-form level ("1E-7") is expanded exactly.
 */
export function toThresholdText(level: string, unit: ThresholdUnit): string {
  const exponent = /^([^eE]*)[eE]([-+]?\d+)$/.exec(level);
  const parts = splitDecimal(exponent ? exponent[1]! : level, true);
  if (parts === null) return level;
  return shiftDecimal(parts, (exponent ? Number(exponent[2]) : 0) + (unit === "pct" ? 2 : 0));
}

/** A QoE level for display: `toThresholdText` plus "%" or "x" ("0.05" pct → "5%", "0.8" x → "0.8x"). */
export function formatThreshold(level: string, unit: ThresholdUnit): string {
  return `${toThresholdText(level, unit)}${unit === "pct" ? "%" : "x"}`;
}

export type SegmentUnit = "USD" | "pct" | "count" | "USD_per_unit";

/**
 * A segment or KPI value typed in a grid cell, to the stored decimal string: USD in the page
 * scale (`parseScaled`), `pct` as a percent with an optional "%" ("5.2" → "0.052"), `count` and
 * `USD_per_unit` as plain numbers (a per-unit amount is never scaled, like EPS). Null for
 * malformed text; blank is the caller's "delete".
 */
export function parseSegmentValue(text: string, unit: SegmentUnit, scale: Scale): string | null {
  if (unit === "USD") return parseScaled(text, scale);
  if (unit === "pct") return parseThreshold(text.trim().replace(/\s*%$/, ""), "pct");
  return parseThreshold(text, "x");
}

/** The exact inverse of `parseSegmentValue`, for the cell editor's starting text. */
export function toSegmentText(value: string, unit: SegmentUnit, scale: Scale): string {
  if (unit === "USD") return toScaledText(value, scale);
  return toThresholdText(value, unit === "pct" ? "pct" : "x");
}

/** A segment or KPI value for display: null "—", negatives in parentheses. */
export function formatSegmentValue(value: string | null, unit: SegmentUnit, scale: Scale): string {
  if (value === null) return DASH;
  if (unit === "USD") return formatValue(value, "USD", scale);
  if (unit === "pct") return formatRatio(value, "pct");
  if (unit === "USD_per_unit") return formatRatio(value, "USD/shares");
  return formatNumber(Number(value), Number.isInteger(Number(value)) ? 0 : 2).replace(
    /(\.\d)0$/,
    "$1",
  );
}

// A fraction as a signed percent with 1 decimal ("+12.3%", "-5.1%"); a value that rounds to
// zero has no sign.
function signed(number: number, suffix: string): string {
  const text = Math.abs(number).toFixed(1);
  if (Number(text) === 0) return `${text}${suffix}`;
  return `${number < 0 ? "-" : "+"}${text}${suffix}`;
}

/** A relative difference (a fraction) as a signed percent: "0.123" → "+12.3%"; null "—". */
export function formatSignedPercent(value: string | null): string {
  return value === null ? DASH : signed(Number(value) * 100, "%");
}

/** A guidance hit rate (a fraction) as a whole percent: "0.846154" → "85%"; null "—". */
export function formatHitRate(value: string | null): string {
  return value === null ? DASH : `${Math.round(Number(value) * 100)}%`;
}

/**
 * The comps "vs median": a `pct` row is a difference of fractions, shown in percentage points
 * ("+2.1 pts"); every other unit a relative difference ("+12.3%"). Null "—".
 */
export function formatVsMedian(value: string | null, unit: RatioUnit): string {
  if (value === null) return DASH;
  return unit === "pct" ? signed(Number(value) * 100, " pts") : formatSignedPercent(value);
}

/** The peer range by unit: "12.1x – 30.4x"; "—" when either end is missing. */
export function formatRange(min: string | null, max: string | null, unit: RatioUnit): string {
  if (min === null || max === null) return DASH;
  return `${formatRatio(min, unit)} – ${formatRatio(max, unit)}`;
}

/** The target's rank among itself and the `n` peer values used ("2 / 4"); "—" when n = 0. */
export function formatRank(rank: number | null, n: number): string {
  return rank === null || n === 0 ? DASH : `${rank} / ${n + 1}`;
}

const RATIO_UNITS: readonly string[] = ["pct", "x", "days", "USD/shares"];
const SEGMENT_UNITS: readonly string[] = ["count", "USD_per_unit"];

/**
 * A guidance range end or actual by the metric's unit: USD and shares in the page scale, ratios
 * by `formatRatio`, KPI counts and per-unit amounts by `formatSegmentValue`. A null unit (a
 * deleted KPI) shows the plain number. Null "—".
 */
export function formatGuidanceValue(
  value: string | null,
  unit: string | null,
  scale: Scale,
): string {
  if (value === null) return DASH;
  if (unit === "USD" || unit === "shares") return formatValue(value, unit, scale);
  if (unit !== null && RATIO_UNITS.includes(unit)) return formatRatio(value, unit as RatioUnit);
  if (unit !== null && SEGMENT_UNITS.includes(unit)) {
    return formatSegmentValue(value, unit as SegmentUnit, scale);
  }
  return toThresholdText(value, "x");
}

/**
 * A guidance value typed in the form, to the API's decimal string: USD and shares in the page
 * scale (`parseScaled`), `pct` as a percent with an optional "%" ("46" → "0.46"), anything else
 * as a plain number. Null for blank or malformed text.
 */
export function parseGuidanceValue(text: string, unit: string, scale: Scale): string | null {
  if (unit === "USD" || unit === "shares") return parseScaled(text, scale);
  return parseSegmentValue(text, unit === "pct" ? "pct" : "count", scale);
}

/** The exact inverse of `parseGuidanceValue`, for prefilling the edit form. */
export function toGuidanceText(value: string, unit: string, scale: Scale): string {
  if (unit === "USD" || unit === "shares") return toScaledText(value, scale);
  return toThresholdText(value, unit === "pct" ? "pct" : "x");
}

export function scaleLabel(unit: string, scale: Scale): string {
  if (unit === "USD/shares") return "USD/share";
  return `${unit} ${SCALE_WORDS[scale]}`;
}

// Company list stats: compact market cap, plain price, multiples.
export function formatCompact(value: string | null): string {
  if (value === null) return DASH;
  const number = Number(value);
  const magnitude = Math.abs(number);
  if (magnitude >= 1e12) return formatNumber(number / 1e12, 1, "T");
  if (magnitude >= 1e9) return formatNumber(number / 1e9, 1, "B");
  return formatNumber(number / 1e6, 1, "M");
}

export function formatPrice(value: string | null): string {
  return value === null ? DASH : formatNumber(Number(value), 2);
}

export function formatMultiple(value: string | null): string {
  return value === null ? DASH : formatNumber(Number(value), 1, "x");
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function formatRelative(iso: string | null, now: Date): string {
  if (iso === null) return "never";
  const elapsed = now.getTime() - new Date(iso).getTime();
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)}m ago`;
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)}h ago`;
  return `${Math.floor(elapsed / DAY)}d ago`;
}

// CSV cells: the number in the current scale with a plain minus sign and no thousands
// separators, so a spreadsheet reads them as numbers.
function csvNumber(number: number, decimals: number, suffix = ""): string {
  const text = number.toFixed(decimals);
  return Number(text) === 0 ? `0${suffix}` : `${text}${suffix}`;
}

export function formatCsvValue(value: string | null, unit: string, scale: Scale): string {
  if (value === null) return "";
  const number = Number(value);
  if (unit === "USD/shares") return csvNumber(number, 2);
  return csvNumber(number / DIVISORS[scale], scale === "B" ? 1 : 0);
}

export function formatCsvPercent(value: string | null): string {
  if (value === null) return "";
  return csvNumber(Number(value) * 100, 1, "%");
}
