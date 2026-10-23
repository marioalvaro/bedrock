import { SubjectNotesSheet } from "@/features/notes/SubjectNotesSheet";

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
    <SubjectNotesSheet
      ticker={ticker}
      target={target && { kind: "line", code: target.code, label: target.label }}
      onClose={onClose}
    />
  );
}
