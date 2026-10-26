import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { formatFiscalPeriod } from "@/lib/format";

import { NotesPanel } from "./NotesPanel";
import type { SubjectTarget } from "./subjects";

interface SubjectNotesSheetProps {
  ticker: string;
  target: SubjectTarget | null;
  onClose: () => void;
}

/**
 * The notes on a subject (a line or a ratio / capital / quality metric), or on one of its cells
 * when the target has a period: the subject's own notes and the cell's, with "Add note" linked
 * to exactly that. Opened from a marker or a cell of the statement and analysis grids.
 */
export function SubjectNotesSheet({ ticker, target, onClose }: SubjectNotesSheetProps) {
  const period = target?.period;
  const periodText = period && formatFiscalPeriod(period.fiscalYear, period.fiscalPeriod);
  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{target?.label}</SheetTitle>
          <SheetDescription>
            {ticker} · {periodText ? `${periodText} notes` : "notes"}
          </SheetDescription>
        </SheetHeader>
        {target && (
          <div className="px-4 pb-4 text-sm">
            <SubjectNotes ticker={ticker} target={target} />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

/** The notes of a subject (or one of its cells) with "Add note" linked to exactly that. */
export function SubjectNotes({ ticker, target }: { ticker: string; target: SubjectTarget }) {
  const period = target.period;
  const periodText = period && formatFiscalPeriod(period.fiscalYear, period.fiscalPeriod);
  return (
    <NotesPanel
      ticker={ticker}
      filter={{
        ...(target.kind === "line"
          ? { code: target.code }
          : { metricKind: target.kind, metricCode: target.code }),
        ...(period && {
          fiscalYear: period.fiscalYear,
          fiscalPeriod: period.fiscalPeriod,
        }),
      }}
      addLink={{
        canonical_code: target.kind === "line" ? target.code : null,
        ...(target.kind !== "line" && {
          metric_kind: target.kind,
          metric_code: target.code,
        }),
        fiscal_year: period?.fiscalYear ?? null,
        fiscal_period: period?.fiscalPeriod ?? null,
        description: periodText ? `${target.label} · ${periodText}` : target.label,
      }}
    />
  );
}
