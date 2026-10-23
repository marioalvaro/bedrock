import type { FiscalPeriod } from "@/api/context";
import type { NoteLinkOut } from "@/api/generated/types.gen";

// What a note can be about: a statement line, or a ratio / capital / quality metric.
export type SubjectKind = "line" | "ratio" | "capital" | "quality";

/** "line:revenue", "ratio:roe": a code is unique only within its kind (`capex` is both). */
export const subjectKey = (kind: SubjectKind, code: string) => `${kind}:${code}`;

const KINDS: readonly string[] = ["line", "ratio", "capital", "quality"];

/** The inverse of `subjectKey`; null for "" (no subject) or a key of an unknown kind. */
export function parseSubjectKey(key: string): { kind: SubjectKind; code: string } | null {
  const colon = key.indexOf(":");
  const kind = key.slice(0, colon);
  if (colon < 0 || !KINDS.includes(kind)) return null;
  return { kind: kind as SubjectKind, code: key.slice(colon + 1) };
}

const cellKey = (kind: SubjectKind, code: string, fiscalYear: number, fiscalPeriod: string) =>
  `${subjectKey(kind, code)}|${fiscalYear}|${fiscalPeriod}`;

// The note-links index of a company: how many notes sit on each cell (subject, year, period)
// and on each subject alone. Period-only links belong to no subject.
export interface NoteIndex {
  cells: ReadonlyMap<string, number>;
  subjects: ReadonlyMap<string, number>;
}

export function noteIndex(links: NoteLinkOut[]): NoteIndex {
  const cells = new Map<string, number>();
  const subjects = new Map<string, number>();
  for (const link of links) {
    const kind: SubjectKind | null = link.canonical_code !== null ? "line" : link.metric_kind;
    const code = link.canonical_code ?? link.metric_code;
    if (kind === null || code === null) continue;
    if (link.fiscal_year === null || link.fiscal_period === null) {
      const key = subjectKey(kind, code);
      subjects.set(key, (subjects.get(key) ?? 0) + link.count);
    } else {
      const key = cellKey(kind, code, link.fiscal_year, link.fiscal_period);
      cells.set(key, (cells.get(key) ?? 0) + link.count);
    }
  }
  return { cells, subjects };
}

export function cellNotes(
  index: NoteIndex,
  kind: SubjectKind,
  code: string,
  fiscalYear: number,
  fiscalPeriod: string,
): number {
  return index.cells.get(cellKey(kind, code, fiscalYear, fiscalPeriod)) ?? 0;
}

export function subjectNotes(index: NoteIndex, kind: SubjectKind, code: string): number {
  return index.subjects.get(subjectKey(kind, code)) ?? 0;
}

// What a notes sheet is opened on: a subject, and one of its cells when `period` is set.
export interface SubjectTarget {
  kind: SubjectKind;
  code: string;
  label: string;
  period?: { fiscalYear: number; fiscalPeriod: FiscalPeriod };
}

interface PeriodLike {
  key: string;
  fiscal_year: number;
  fiscal_period: string;
}

/** The target of a subject's cell in a period column; null for a TTM column (no notes there). */
export function cellTarget(
  kind: SubjectKind,
  code: string,
  label: string,
  period: PeriodLike,
): SubjectTarget | null {
  if (period.key.startsWith("TTM")) return null;
  return {
    kind,
    code,
    label,
    period: { fiscalYear: period.fiscal_year, fiscalPeriod: period.fiscal_period as FiscalPeriod },
  };
}
