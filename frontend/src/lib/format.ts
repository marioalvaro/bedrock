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
