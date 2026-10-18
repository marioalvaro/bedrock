import type { PeriodOut, RowOut, StatementOut } from "@/api/generated/types.gen";
import { scaleLabel } from "@/lib/format";
import type { Scale } from "@/lib/scale";

export type Provenance = "reported" | "derived" | "normalized";
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

// The line items a statement shows. The payload is a flat list in display order with a depth,
// each subtotal above its breakdown, so a line has a breakdown when the next shown line is deeper.
// A line with no value in any period shows only when `showEmpty` is on and it is adjustable; each
// otherwise hidden ancestor of such a line shows too, so the line keeps its real parent.
function shownLines(payload: StatementOut, showEmpty: boolean): RowOut[] {
  const lines = payload.rows;
  const shown = lines.map((line) => hasValue(line.values));
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
    depth: line.depth + 1,
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
  };
}

// Reshapes a statement payload into grid rows. Line items with no value in any period are
// dropped (the Data gaps report lists them) unless `showEmpty` keeps them (see `shownLines`); a
// line under a collapsed ancestor is hidden; YoY and common-size sub-rows follow their line when
// toggled on, and only where the API sent a value.
export function toGridRows(payload: StatementOut, options: GridOptions): GridRow[] {
  const keys = payload.periods.map((period) => period.key);
  const rows: GridRow[] = [];

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
    });
  }

  return rows;
}

// A line item's value has details, and an empty cell of an adjustable line opens them too so an
// adjustment can be added there; the cell endpoint covers FY and Q1..Q4, not TTM.
export function canExplain(row: GridRow, period: PeriodOut): boolean {
  if (row.kind !== "line" || period.key.startsWith("TTM")) return false;
  return row.values[period.key] !== null || row.adjustable;
}

// The statement header names the USD scale; rows in another unit say so themselves.
export function rowUnitHint(unit: string, scale: Scale): string | null {
  return unit === "USD/shares" || unit === "shares" ? scaleLabel(unit, scale) : null;
}

// The first CSV column: a sub-row is named after its line item.
export function csvLabel(row: GridRow): string {
  return row.parentLabel ? `${row.parentLabel} ${row.label}` : row.label;
}
