import type { NewFilingOut } from "@/api/generated/types.gen";
import { formatDay } from "@/lib/format";

/** A 10-K or 10-Q filed but not loaded yet (FR-DATA-23): the newest one ("10-Q filed Aug 1"),
 * "+n" for the others. `filings` is the payload's `new_filings`, newest first. */
export function NewFilingMark({ filings }: { filings: NewFilingOut[] }) {
  const newest = filings[0];
  if (!newest) return null;
  return (
    <span
      className="text-prov-derived text-xs whitespace-nowrap"
      title="Refresh to load it. The forecast is snapshotted first."
    >
      <span>
        {newest.form} filed {formatDay(newest.filed_at, { year: false })}
      </span>
      {filings.length > 1 && <span className="ml-1">+{filings.length - 1}</span>}
    </span>
  );
}
