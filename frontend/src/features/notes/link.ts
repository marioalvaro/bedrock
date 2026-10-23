import type { NoteOut } from "@/api/generated/types.gen";
import { formatFiscalPeriod } from "@/lib/format";

/** "Revenue · FY2024", "FY2024", "Revenue", or null for a plain journal note. */
export function noteLinkText(note: NoteOut): string | null {
  const period =
    note.fiscal_year !== null && note.fiscal_period !== null
      ? formatFiscalPeriod(note.fiscal_year, note.fiscal_period)
      : null;
  const line = note.canonical_code === null ? null : (note.label ?? note.canonical_code);
  return [line, period].filter((part) => part !== null).join(" · ") || null;
}
