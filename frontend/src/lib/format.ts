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
