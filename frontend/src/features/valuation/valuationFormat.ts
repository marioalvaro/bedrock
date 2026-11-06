// Texts of the Valuation tab. The frontend computes nothing: every number comes from the API and is
// only formatted here; the input texts are parsed back to the API's plain decimal strings.
import type {
  BedrockSchemasValuationMultipleOut,
  DcfOut,
  DcfPeriodOut,
  DiscountOut,
  ValuationInputIn,
  ValuationInputRowOut,
} from "@/api/generated/types.gen";
import type { ScenarioCase } from "@/api/scenarios";
import {
  formatPercent,
  formatPrice,
  formatSignedPercent,
  parseThreshold,
  toThresholdText,
} from "@/lib/format";

const DASH = "—";

/** A value per share: "$187.40", a negative "($12.00)", null "—". */
export function formatPerShare(value: string | null): string {
  if (value === null) return DASH;
  const text = formatPrice(value);
  return text.startsWith("(") ? `($${text.slice(1)}` : `$${text}`;
}

/** An upside (a fraction) as a signed percent: "+12.3%"; null "—". */
export const formatUpside = formatSignedPercent;

/** The color of an upside by its sign; none for zero or null. */
export function upsideClass(value: string | null): string {
  if (value === null) return "";
  const number = Number(value);
  return number > 0 ? "text-positive" : number < 0 ? "text-negative" : "";
}

/** A multiple with 1 decimal and "×": "25.1×"; null "—". */
export function formatTimes(value: string | null): string {
  return value === null ? DASH : `${Number(value).toFixed(1)}×`;
}

function ordinal(text: string): string {
  if (text.includes(".")) return `${text}th`;
  const n = Number(text);
  if (n % 100 >= 11 && n % 100 <= 13) return `${text}th`;
  const suffix = ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${text}${suffix}`;
}

/** A percentile (a fraction) as an ordinal: "0.5" → "50th", "0.375" → "37.5th". */
export function percentileText(fraction: string): string {
  return ordinal(toThresholdText(fraction, "pct"));
}

/** Where a target's multiple comes from: "Manual", "Own history, 50th percentile of 9 years", … */
export function sourceText(multiple: BedrockSchemasValuationMultipleOut): string {
  if (multiple.source === "own_history") {
    const p =
      multiple.percentile === null ? "" : `, ${percentileText(multiple.percentile)} percentile`;
    return `Own history${p} of ${multiple.n ?? 0} years`;
  }
  if (multiple.source === "peer_median") {
    const n = multiple.n ?? 0;
    return `Peer median of ${multiple.comps_set?.name ?? "the comps set"} (${n} ${n === 1 ? "peer" : "peers"})`;
  }
  return "Manual";
}

/** The DCF's discount line: the WACC with its components, or a direct rate. */
export function discountText(discount: DiscountOut): string {
  if (discount.method !== "wacc") {
    return `Discount rate ${formatPercent(discount.rate)} (set directly)`;
  }
  const beta = discount.beta === null ? DASH : Number(discount.beta).toFixed(2);
  return [
    `WACC ${formatPercent(discount.rate)}`,
    `cost of equity ${formatPercent(discount.cost_of_equity)} (${formatPercent(discount.risk_free_rate)} + ${beta} × ${formatPercent(discount.equity_risk_premium)})`,
    `after-tax cost of debt ${formatPercent(discount.after_tax_cost_of_debt)}`,
    `debt ${formatPercent(discount.debt_weight)} / equity ${formatPercent(discount.equity_weight)}`,
  ].join(" · ");
}

export function midYearText(midYear: boolean): string {
  return midYear ? "Mid-year discounting" : "End-of-year discounting";
}

export interface TerminalTexts {
  method: string;
  implied: string | null;
  share: string | null;
}

/** The terminal value's method, its implied counterpart and its share of EV. */
export function terminalTexts({ terminal, terminal_share: share }: DcfOut): TerminalTexts {
  const gordon = terminal.method === "gordon";
  const implied = gordon
    ? terminal.implied_exit_multiple &&
      `Implied exit multiple ${formatTimes(terminal.implied_exit_multiple)} EV/EBITDA`
    : terminal.implied_growth &&
      `Implied perpetual growth ${formatPercent(terminal.implied_growth)}`;
  return {
    method: gordon
      ? `Gordon growth ${formatPercent(terminal.growth)}`
      : `Exit multiple ${formatTimes(terminal.exit_multiple)} EV/EBITDA`,
    implied: implied || null,
    share: share === null ? null : `Terminal value is ${Math.round(Number(share) * 100)}% of EV`,
  };
}

/** A cash-flow period's header: the API's label, a stub suffixed " (rest of year)". */
export function periodLabel(period: DcfPeriodOut): string {
  return period.stub ? `${period.label} (rest of year)` : period.label;
}

/** "Price $172.00 · close of 2026-11-04", or why there is no upside. */
export function priceText(price: string | null, date: string | null): string {
  if (price === null) return "No price stored. Refresh the company to load prices.";
  return `Price ${formatPerShare(price)}${date ? ` · close of ${date}` : ""}`;
}

// ---- Inputs ---------------------------------------------------------------------------------

// 2 decimals, a trailing zero dropped down to 1 decimal ("4.00" → "4.0", "2.25" stays).
const oneOrTwo = (number: number) => number.toFixed(2).replace(/(\.\d)0$/, "$1");

/**
 * A number input's text: `pct` as a percent with 1–2 decimals ("4.0%", "2.25%"), beta with 2
 * decimals ("1.00"), another multiple with 1–2 decimals and "×" ("12.0×"); null "".
 */
export function inputText(row: ValuationInputRowOut): string {
  if (row.value === null) return "";
  if (row.unit === "pct") return `${oneOrTwo(Number(toThresholdText(row.value, "pct")))}%`;
  if (row.code === "beta") return Number(row.value).toFixed(2);
  return `${oneOrTwo(Number(row.value))}×`;
}

/**
 * Typed text to the API's value: `pct` typed as a percent (an optional "%"), `x` a plain number
 * (an optional "×" or "x"). `{ value: null }` for blank text; null when it is not a number.
 */
export function parseInputText(text: string, unit: string | null): { value: string | null } | null {
  const trimmed = text.trim();
  if (trimmed === "") return { value: null };
  const pct = unit === "pct";
  const body = trimmed.replace(pct ? /\s*%$/ : /\s*[×x]$/, "");
  const value = parseThreshold(body, pct ? "pct" : "x");
  return value === null ? null : { value };
}

/**
 * The PUT row of a number input left with `text`: its value, `null` when an own value is emptied,
 * null (nothing to send) when the text or the number is unchanged or an inherited field stays
 * empty, "invalid" when the text is not a number.
 */
export function inputEdit(
  row: ValuationInputRowOut,
  text: string,
): ValuationInputIn | null | "invalid" {
  if (text.trim() === inputText(row)) return null;
  const parsed = parseInputText(text, row.unit);
  if (parsed === null) return "invalid";
  if (parsed.value === null) return row.own === null ? null : { code: row.code, value: null };
  if (row.value !== null && Number(parsed.value) === Number(row.value)) return null;
  return { code: row.code, value: parsed.value };
}

const CHOICES: Record<string, string> = {
  wacc: "WACC",
  direct: "Direct rate",
  gordon: "Gordon growth",
  exit_multiple: "Exit multiple",
  off: "Off",
  manual: "Manual",
  own_history: "Own history",
  peer_median: "Peer median",
};

export const choiceLabel = (value: string): string => CHOICES[value] ?? value;

type Source = ValuationInputRowOut["source"];

/** A value's style by its source, as the driver grid: own plain, inherited muted italic. */
export function sourceClass(source: Source): string {
  if (source === "own") return "";
  return source === "base" ? "text-muted-foreground italic" : "text-muted-foreground";
}

export function sourceTitle(row: ValuationInputRowOut): string {
  if (row.source === "own") return "Set in this case";
  if (row.source === "base") return "Inherited from Base";
  if (row.source === "derived") return row.note ?? "Derived";
  return "Default";
}

/** The clear button of an own value. */
export const clearText = (scenarioCase: ScenarioCase) =>
  scenarioCase === "base" ? "Back to the default" : "Use Base's value";

/** The reset dialog's text. */
export const resetText = (scenarioCase: ScenarioCase) =>
  scenarioCase === "base"
    ? "Every valuation input of Base goes back to its default."
    : "Its own inputs are removed; it follows Base again.";

const WACC_INPUTS = [
  "risk_free_rate",
  "equity_risk_premium",
  "beta",
  "cost_of_debt",
  "tax_rate",
  "debt_weight",
];

/**
 * The codes of the inputs the form shows (no calculation): a direct rate hides the WACC inputs,
 * WACC hides the direct rate; Gordon hides the exit multiple, an exit multiple hides the growth.
 */
export function shownCodes(rows: ValuationInputRowOut[]): Set<string> {
  const value = (code: string) => rows.find((row) => row.code === code)?.value;
  const hidden = new Set<string>(
    value("discount_method") === "direct" ? WACC_INPUTS : ["discount_rate"],
  );
  hidden.add(value("terminal_method") === "exit_multiple" ? "terminal_growth" : "exit_multiple");
  return new Set(rows.map((row) => row.code).filter((code) => !hidden.has(code)));
}

const SOURCE_SUFFIX = "_source";

/** The multiple targets, from their `<m>_source` rows in catalog order. */
export function targets(rows: ValuationInputRowOut[]): { code: string; label: string }[] {
  return rows
    .filter((row) => row.code.endsWith(SOURCE_SUFFIX))
    .map((row) => ({
      code: row.code.slice(0, -SOURCE_SUFFIX.length),
      label: row.label.replace(/ source$/, ""),
    }));
}

/** The fields of a target row its source uses. */
export function targetFields(source: string | null) {
  return {
    multiple: source === "manual",
    percentile: source === "own_history",
    year: source !== null && source !== "off",
  };
}
