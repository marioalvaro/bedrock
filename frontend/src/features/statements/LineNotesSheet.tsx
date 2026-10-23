import { NotesPanel } from "@/features/notes/NotesPanel";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export interface LineTarget {
  code: string;
  label: string;
}

interface LineNotesSheetProps {
  ticker: string;
  target: LineTarget | null;
  onClose: () => void;
}

/** The notes on a line item (its own and those on its cells), opened from the line marker. */
export function LineNotesSheet({ ticker, target, onClose }: LineNotesSheetProps) {
  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{target?.label}</SheetTitle>
          <SheetDescription>{ticker} · notes</SheetDescription>
        </SheetHeader>
        {target && (
          <div className="px-4 pb-4 text-sm">
            <NotesPanel
              ticker={ticker}
              filter={{ code: target.code }}
              addLink={{
                canonical_code: target.code,
                fiscal_year: null,
                fiscal_period: null,
                description: target.label,
              }}
            />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
