import type { NoteOut } from "@/api/generated/types.gen";
import { formatFiscalPeriod } from "@/lib/format";

/** "Revenue · FY2024", "Return on equity", "FY2024", or null for a plain journal note. */
export function noteLinkText(note: NoteOut): string | null {
  const period =
    note.fiscal_year !== null && note.fiscal_period !== null
      ? formatFiscalPeriod(note.fiscal_year, note.fiscal_period)
      : null;
  const code = note.canonical_code ?? note.metric_code;
  const subject = code === null ? null : (note.label ?? code);
  return [subject, period].filter((part) => part !== null).join(" · ") || null;
}
