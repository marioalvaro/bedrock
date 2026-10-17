import { parseThreshold, toThresholdText, type ThresholdUnit } from "@/lib/format";

/**
 * The value to send for a level input. Blank (or whitespace) is `null` (no level); text that
 * `parseThreshold` accepts is that exact fraction string ("5" pct → "0.05"); any other text is
 * sent trimmed and as typed (a formula, or a malformed number such as "5%"), for the API to
 * validate.
 */
export function levelToSend(text: string, unit: ThresholdUnit): string | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  return parseThreshold(trimmed, unit) ?? trimmed;
}

/**
 * The input prefill for a stored level: a formula is its text, a number is
 * `toThresholdText(number, unit)`, no level is "". A formula wins if both are present.
 */
export function levelText(
  number: string | null,
  formula: string | null,
  unit: ThresholdUnit,
): string {
  if (formula !== null) return formula;
  if (number !== null) return toThresholdText(number, unit);
  return "";
}

/** True for non-blank text that `parseThreshold` rejects, i.e. what the UI marks with "ƒ". */
export function isFormulaLevel(text: string, unit: ThresholdUnit): boolean {
  const trimmed = text.trim();
  return trimmed !== "" && parseThreshold(trimmed, unit) === null;
}

/** Shown under a level input marked "ƒ": formula numbers are fractions, unlike a bare level. */
export const FORMULA_UNITS_NOTE = "Formulas use fractions: write 1% or 0.01";

/** The hint line under the custom-rule form. */
export const FORMULA_HINT =
  "In formulas write percentages with % (5% = 0.05); use the codes of lines and ratios; functions avg(), yoy(), prev()";
