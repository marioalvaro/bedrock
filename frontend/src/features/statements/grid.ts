import type { PeriodOut, RowOut, StatementOut } from "@/api/generated/types.gen";
import { cellNotes, subjectNotes, type NoteIndex } from "@/features/notes/subjects";
import { formatPercent, formatValue, scaleLabel } from "@/lib/format";
import type { Scale } from "@/lib/scale";

export type EmptyCause = NonNullable<RowOut["empty_cause"][number]>;

export type Provenance =
  | "reported"
  | "derived"
  | "normalized"
  | "zero_inferred"
  | "approximated"
  | "imported"
  | "forecast";
export type GridRowKind = "line" | "yoy" | "common_size" | "balance_check";

// One AG Grid row. Values stay the API's decimal strings: the grid formats them at
// render time (display) and at export time (CSV), and no figure is computed here.
export interface GridRow {
  id: string;
  code: string;
  label: string;
  depth: number;
  unit: string;
  kind: GridRowKind;
  values: Record<string, string | null>;
  provenance: Record<string, Provenance | null>;
  ok?: Record<string, boolean>;
  adjustable: boolean; // a line item that takes adjustments; sub-rows and the check never do
  parentLabel?: string;
  hasChildren: boolean; // a line item with a breakdown under it
  expanded: boolean; // whether that breakdown is shown
  custom: boolean; // a line the user added in an import (S10c)
  // M7b S8, per period: the labels of the lines inside a combined value (an empty list when it
  // covers no row; null when not combined), the label of the line an empty cell's amount is
  // inside (null when not covered), and why an empty cell is empty (null when filled or unknown)
  combinedWith: Record<string, string[] | null>;
  includedIn: Record<string, string | null>;
  emptyCause: Record<string, EmptyCause | null>;
  // M7d S5, per period: the face lines (`taxonomy:Concept`) R8 summed into the cell only because a
  // classification placed them there; null when none.
  classifiedBy: Record<string, string[] | null>;
}

export interface GridOptions {
  yoy: boolean;
  commonSize: boolean;
  expanded: ReadonlySet<string>; // codes whose breakdown is open
  // Also show adjustable line items with no value in any period, so they can be adjusted
  // (non-adjustable empty lines stay hidden). Off by default.
  showEmpty?: boolean;
}

function byPeriod<T>(keys: string[], items: T[]): Record<string, T> {
  return Object.fromEntries(keys.map((key, index) => [key, items[index] as T]));
}

function hasValue(values: (string | null)[]): boolean {
  return values.some((value) => value !== null);
}

// A line with a value, or with a cell whose amount is inside another line: "incl. in" is worth
// seeing, an empty line is not.
function hasContent(line: RowOut): boolean {
  return hasValue(line.values) || line.included_in.some((code) => code !== null);
}

const NO_MARKS = { combinedWith: {}, includedIn: {}, emptyCause: {}, classifiedBy: {} };

// The line items a statement shows. The payload is a flat list in display order with a depth,
// each subtotal above its breakdown, so a line has a breakdown when the next shown line is deeper.
// A line with no value in any period shows only when `showEmpty` is on and it is adjustable; each
// otherwise hidden ancestor of such a line shows too, so the line keeps its real parent.
function shownLines(payload: StatementOut, showEmpty: boolean): RowOut[] {
  const lines = payload.rows;
  const shown = lines.map(hasContent);
  if (showEmpty) {
    lines.forEach((line, index) => {
      if (shown[index] || !line.adjustable) return;
      shown[index] = true;
      let depth = line.depth;
      for (let up = index - 1; up >= 0 && depth > 0; up -= 1) {
        const ancestor = lines[up] as RowOut;
        if (ancestor.depth >= depth) continue;
        shown[up] = true;
        depth = ancestor.depth;
      }
    });
  }
  return lines.filter((_, index) => shown[index]);
}

function hasBreakdown(lines: RowOut[], index: number): boolean {
  const next = lines[index + 1];
  return next !== undefined && next.depth > (lines[index] as RowOut).depth;
}

// The codes whose breakdown can be opened, for "expand all"; `showEmpty` as in GridOptions.
export function expandableCodes(payload: StatementOut, showEmpty = false): string[] {
  const lines = shownLines(payload, showEmpty);
  return lines.filter((_, index) => hasBreakdown(lines, index)).map((line) => line.code);
}

function subRow(
  line: RowOut,
  keys: string[],
  kind: "yoy" | "common_size",
  label: string,
  values: (string | null)[],
): GridRow | null {
  if (!hasValue(values)) return null;
  return {
    id: `${line.code}:${kind}`,
    code: line.code,
    label,
    parentLabel: line.label,
    // At the line's own depth: one level in, it would line up with the line's breakdown.
    depth: line.depth,
    unit: "%",
    kind,
    values: byPeriod(keys, values),
    provenance: byPeriod(
      keys,
      keys.map(() => null),
    ),
    adjustable: false,
    hasChildren: false,
    expanded: false,
    custom: false,
    ...NO_MARKS,
  };
}

// Reshapes a statement payload into grid rows. Line items with no value in any period are
// dropped (the Data gaps report lists them) unless `showEmpty` keeps them (see `shownLines`); a
// line under a collapsed ancestor is hidden; YoY and common-size sub-rows follow their line when
// toggled on, and only where the API sent a value.
export function toGridRows(payload: StatementOut, options: GridOptions): GridRow[] {
  const keys = payload.periods.map((period) => period.key);
  const rows: GridRow[] = [];
  const labels = new Map(payload.rows.map((line) => [line.code, line.label]));
  const labelOf = (code: string) => labels.get(code) ?? code;

  const lines = shownLines(payload, options.showEmpty ?? false);
  const open: { depth: number; expanded: boolean }[] = []; // the ancestors of the current line

  lines.forEach((line, index) => {
    while (open.length > 0 && (open.at(-1) as { depth: number }).depth >= line.depth) open.pop();
    const visible = open.every((ancestor) => ancestor.expanded);
    const hasChildren = hasBreakdown(lines, index);
    const expanded = hasChildren && options.expanded.has(line.code);
    if (hasChildren) open.push({ depth: line.depth, expanded });
    if (!visible) return;

    rows.push({
      id: line.code,
      code: line.code,
      label: line.label,
      depth: line.depth,
      unit: line.unit,
      kind: "line",
      values: byPeriod(keys, line.values),
      provenance: byPeriod(keys, line.provenance),
      adjustable: line.adjustable,
      hasChildren,
      expanded,
      custom: line.custom,
      combinedWith: byPeriod(
        keys,
        line.combined_with.map((codes) => codes?.map(labelOf) ?? null),
      ),
      includedIn: byPeriod(
        keys,
        line.included_in.map((code) => (code === null ? null : labelOf(code))),
      ),
      emptyCause: byPeriod(keys, line.empty_cause),
      classifiedBy: byPeriod(keys, line.classified_by),
    });
    if (options.yoy) {
      const yoy = subRow(line, keys, "yoy", "YoY", line.yoy);
      if (yoy) rows.push(yoy);
    }
    if (options.commonSize) {
      const label = line.common_size_base ? `% of ${line.common_size_base}` : "Common size";
      const common = subRow(line, keys, "common_size", label, line.common_size);
      if (common) rows.push(common);
    }
  });

  if (payload.balance_check) {
    const checks = new Map(payload.balance_check.map((check) => [check.period_key, check]));
    rows.push({
      id: "balance_check",
      code: "balance_check",
      label: "Balance check",
      depth: 0,
      unit: "USD",
      kind: "balance_check",
      values: Object.fromEntries(keys.map((key) => [key, checks.get(key)?.difference ?? null])),
      provenance: byPeriod(
        keys,
        keys.map(() => null),
      ),
      ok: Object.fromEntries(keys.map((key) => [key, checks.get(key)?.ok ?? false])),
      adjustable: false,
      hasChildren: false,
      expanded: false,
      custom: false,
      ...NO_MARKS,
    });
  }

  return rows;
}

// The "Other <line>" row of a custom breakdown: parent less its lines, computed by the table.
const OTHER_PREFIX = "other:";

// A line item's value has details, and an empty cell of an adjustable line opens them too so an
// adjustment can be added there; the cell endpoint covers FY and Q1..Q4, not TTM, not a forecast
// period (no filing behind it), and not the "Other" row of a custom breakdown (it has no cell of
// its own).
export function canExplain(row: GridRow, period: PeriodOut): boolean {
  if (row.kind !== "line" || period.key.startsWith("TTM") || period.is_forecast) return false;
  if (row.code.startsWith(OTHER_PREFIX)) return false;
  return row.values[period.key] !== null || row.adjustable || isIncluded(row, period.key);
}

function isIncluded(row: GridRow, key: string): boolean {
  return row.values[key] === null && (row.includedIn[key] ?? null) !== null;
}

function isInapplicable(row: GridRow, key: string): boolean {
  return row.values[key] === null && row.emptyCause[key] === "not_applicable";
}

// A value that holds other lines too (a combined line, M7b S4): the grid marks it.
export function isCombined(row: GridRow, key: string): boolean {
  return row.values[key] !== null && (row.combinedWith[key] ?? null) !== null;
}

// A value R8 summed from a line a classifier placed (M7d S5): the grid marks it.
export function isClassified(row: GridRow, key: string): boolean {
  return (
    row.kind === "line" && row.values[key] !== null && (row.classifiedBy[key] ?? null) !== null
  );
}

export function classifiedText(lines: readonly string[]): string {
  return `AI classified: ${lines.join(", ")}`;
}

// The tooltip of a carrier, a covered or a classified cell; undefined for any other cell.
export function cellTitle(row: GridRow, key: string): string | undefined {
  const texts: string[] = [];
  if (isCombined(row, key)) texts.push(includesText(row.combinedWith[key] as string[]));
  else if (isIncluded(row, key)) texts.push(includedInText(row.includedIn[key] as string));
  if (isClassified(row, key)) texts.push(classifiedText(row.classifiedBy[key] as string[]));
  return texts.length > 0 ? texts.join(". ") : undefined;
}

// What a combined value holds, by label; the grid's tooltip and the cell sheet say the same.
export function includesText(labels: readonly string[]): string {
  return labels.length > 0
    ? `Includes ${labels.join(", ")}`
    : "Includes other lines with no row of their own";
}

export function includedInText(label: string): string {
  return `Included in ${label}`;
}

// A covered or inapplicable cell reads as a note, not as a figure.
export function cellStateClasses(row: GridRow, key: string): string[] {
  return isIncluded(row, key) || isInapplicable(row, key) ? ["cell-muted"] : [];
}

// The statement header names the USD scale; rows in another unit say so themselves.
export function rowUnitHint(unit: string, scale: Scale): string | null {
  return unit === "USD/shares" || unit === "shares" ? scaleLabel(unit, scale) : null;
}

// A cell's display text: the check row shows ✓ or the difference, sub-rows a percent, a line its
// value in the page scale behind its provenance mark.
export function cellText(row: GridRow, key: string, scale: Scale): string {
  const value = row.values[key] ?? null;
  if (row.kind === "balance_check") {
    return row.ok?.[key] ? "✓" : formatValue(value, row.unit, scale);
  }
  if (row.kind === "yoy" || row.kind === "common_size") return formatPercent(value);
  if (isIncluded(row, key)) return `incl. in ${row.includedIn[key]}`;
  if (isInapplicable(row, key)) return "n/a";
  const text = formatValue(value, row.unit, scale);
  return value === null ? text : provenanceMark(row.provenance[key]) + text;
}

// The first CSV column: a sub-row is named after its line item.
export function csvLabel(row: GridRow): string {
  return row.parentLabel ? `${row.parentLabel} ${row.label}` : row.label;
}

// The classes a cell's provenance gives its value. Derived and approximated values are not hard
// facts and share one style, an inferred zero is muted, a normalized value is amber, an imported
// one (your file, not SEC) is teal, a forecast one is plain text in a tinted column; reported is
// plain.
export function provenanceClasses(provenance: Provenance | null | undefined): string[] {
  switch (provenance) {
    case "derived":
    case "approximated":
      return ["prov-derived"];
    case "zero_inferred":
      return ["prov-zero"];
    case "normalized":
      return ["prov-normalized"];
    case "imported":
      return ["prov-imported"];
    case "forecast":
      return ["prov-forecast"];
    default:
      return [];
  }
}

// A forecast ("E") column is tinted, header and cells, so estimates never read as actuals.
export function forecastColumnClass(period: PeriodOut): string[] {
  return period.is_forecast ? ["cell-forecast"] : [];
}

// A forecast year the scenario sets by quarter: its figures are the sum of its quarters (FR-FCST-13).
// Only annual columns qualify; the quarters themselves are not built from anything.
export function isBuiltFromQuarters(period: PeriodOut, years: readonly number[]): boolean {
  return period.is_forecast && period.fiscal_period === "FY" && years.includes(period.fiscal_year);
}

// An approximated value carries a tilde in front of its number; the CSV export does not.
export function provenanceMark(provenance: Provenance | null | undefined): string {
  return provenance === "approximated" ? "~" : "";
}

// The statement markers read the shared note-links index (`features/notes/subjects.ts`) as the
// "line" subject kind.
export { noteIndex, type NoteIndex } from "@/features/notes/subjects";

// Notes on a line item's FY or quarter cell; sub-rows and TTM columns carry no notes.
export function cellNoteCount(index: NoteIndex, row: GridRow, period: PeriodOut): number {
  if (row.kind !== "line" || period.key.startsWith("TTM")) return 0;
  return cellNotes(index, "line", row.code, period.fiscal_year, period.fiscal_period);
}

// Notes linked to a line item as a whole.
export function lineNoteCount(index: NoteIndex, row: GridRow): number {
  return row.kind === "line" ? subjectNotes(index, "line", row.code) : 0;
}
