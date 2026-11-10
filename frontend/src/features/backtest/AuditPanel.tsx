import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { auditInfiniteOptions, useSetRationale, type AuditFilter } from "@/api/accountability";
import { companyErrorMessage } from "@/api/companies";
import type { AuditRowOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { formatAuditValue, formatLocalTime } from "./backtestFormat";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const HEAD = "px-2 py-1 text-left font-medium whitespace-nowrap";
const CELL = "px-2 py-1 align-top tabular-nums";
const RATIONALE_LIMIT = 500;

const FILTERS: { value: AuditFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "driver", label: "Drivers" },
  { value: "engine_choice", label: "Engines" },
  { value: "year_mode", label: "Year modes" },
  { value: "valuation_input", label: "Valuation inputs" },
  { value: "scenario", label: "Scenarios" },
  { value: "adjustment", label: "Adjustments" },
];

interface RationaleCellProps {
  ticker: string;
  row: AuditRowOut;
}

/** Saves on blur or Enter when the text changed; a failure shows the detail and keeps the text. */
function RationaleCell({ ticker, row }: RationaleCellProps) {
  const save = useSetRationale(ticker);
  const stored = row.rationale ?? "";
  const [text, setText] = useState(stored);

  function commit() {
    const next = text.trim();
    if (save.isPending || next === stored) return;
    save.mutate({ id: row.id, rationale: next === "" ? null : next });
  }

  return (
    <>
      <Input
        aria-label={`Rationale for ${row.label}`}
        className="h-7 min-w-48"
        maxLength={RATIONALE_LIMIT}
        readOnly={save.isPending}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />
      {save.isError && (
        <p role="alert" className="text-destructive mt-1 text-xs">
          {companyErrorMessage(save.error, "Could not save the rationale.")}
        </p>
      )}
    </>
  );
}

interface AuditPanelProps {
  ticker: string;
}

/** Every logged change to a driver, adjustment or override, newest first, with its rationale. */
export function AuditPanel({ ticker }: AuditPanelProps) {
  const [entity, setEntity] = useState<AuditFilter>("all");
  const { data, isPending, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } =
    useInfiniteQuery(auditInfiniteOptions(ticker, entity));
  const rows = useMemo(() => data?.pages.flatMap((page) => page.rows), [data]);

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <select
          aria-label="Change type"
          className={SELECT}
          value={entity}
          onChange={(e) => setEntity(e.target.value as AuditFilter)}
        >
          {FILTERS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-2 p-4">
        {!rows && isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
        {!rows && !isPending && (
          <p className="text-destructive text-sm">Could not load the audit log.</p>
        )}
        {rows?.length === 0 && <p className="text-muted-foreground text-sm">No changes yet.</p>}
        {rows && rows.length > 0 && (
          <div className="overflow-x-auto">
            <table aria-label="Audit log" className="text-sm">
              <thead className="text-muted-foreground">
                <tr>
                  <th className={HEAD}>When</th>
                  <th className={HEAD}>Change</th>
                  <th className={HEAD}>Where</th>
                  <th className={HEAD}>From</th>
                  <th className={HEAD}>To</th>
                  <th className={HEAD}>Rationale</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-border border-t">
                    <td className={`${CELL} whitespace-nowrap`}>
                      {formatLocalTime(row.changed_at)}
                    </td>
                    <td className={CELL}>{row.label}</td>
                    <td className={CELL}>{row.scope ?? "—"}</td>
                    <td className={CELL}>{formatAuditValue(row.old_value, row.unit)}</td>
                    <td className={CELL}>{formatAuditValue(row.new_value, row.unit)}</td>
                    <td className={CELL}>
                      {/* Keyed by the stored text, so a reloaded value replaces the input's. */}
                      <RationaleCell key={`${row.id}-${row.rationale}`} ticker={ticker} row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {hasNextPage && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isFetchingNextPage}
            onClick={() => fetchNextPage()}
          >
            Load more
          </Button>
        )}
        {isFetchNextPageError && <p className="text-destructive text-sm">Could not load more.</p>}
      </div>
    </div>
  );
}
