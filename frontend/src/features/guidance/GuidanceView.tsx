import { useQuery } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import {
  guidanceMetricsQueryOptions,
  guidanceQueryOptions,
  useDeleteGuidance,
} from "@/api/context";
import type { GuidanceEntryOut, GuidanceSummaryOut } from "@/api/generated/types.gen";
import { UnitToggle } from "@/components/UnitToggle";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  formatFiscalPeriod,
  formatGuidanceValue,
  formatHitRate,
  formatSignedPercent,
} from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

import { GuidanceForm } from "./GuidanceForm";

const VERDICTS: Record<GuidanceEntryOut["verdict"], { text: string; className?: string }> = {
  beat: { text: "Beat", className: "text-positive" },
  in_range: { text: "In range" },
  miss: { text: "Miss", className: "text-negative" },
  pending: { text: "Pending" },
};

const TABLE = "w-full text-sm";
const HEAD = "text-muted-foreground border-border border-b text-xs font-normal";
const CELL = "px-2 py-1 whitespace-nowrap";

const summaryText = (s: GuidanceSummaryOut) =>
  `${s.beat} beat · ${s.in_range} in range · ${s.miss} miss · ${s.pending} pending · hit rate ${formatHitRate(s.hit_rate)}`;

const entryName = (entry: GuidanceEntryOut) =>
  `${entry.label} · ${formatFiscalPeriod(entry.fiscal_year, entry.fiscal_period)} · given ${entry.given_on}`;

// A range by unit; a point estimate (low = high) as one value.
function rangeText(entry: GuidanceEntryOut, scale: Scale): string {
  const low = formatGuidanceValue(entry.low, entry.unit, scale);
  if (entry.low === entry.high) return low;
  return `${low} – ${formatGuidanceValue(entry.high, entry.unit, scale)}`;
}

interface GuidanceViewProps {
  ticker: string;
}

/**
 * The Guidance tab: the hit/miss summary of the latest entries, the counts per metric and every
 * entry with its actual, surprise and verdict (revisions muted); add, edit and delete. See
 * erd/workspace.md "Frontend (M3)".
 */
export function GuidanceView({ ticker }: GuidanceViewProps) {
  const scale = useScale();
  const { data, isPending, isError } = useQuery(guidanceQueryOptions(ticker));
  const metrics = useQuery(guidanceMetricsQueryOptions(ticker));
  // `null` closed, "new" adding, otherwise the entry being edited.
  const [form, setForm] = useState<GuidanceEntryOut | "new" | null>(null);
  const [toDelete, setToDelete] = useState<GuidanceEntryOut | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const remove = useDeleteGuidance(ticker);

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <UnitToggle />
        <Button size="sm" className="ml-auto" onClick={() => setForm("new")}>
          Add guidance
        </Button>
      </div>
      {form !== null && metrics.data && (
        <GuidanceForm
          key={form === "new" ? "new" : form.id}
          ticker={ticker}
          metrics={metrics.data}
          entry={form === "new" ? undefined : form}
          onDone={() => setForm(null)}
        />
      )}
      {form !== null && metrics.isError && (
        <p className="text-destructive px-4 pt-2 text-sm">Could not load the metrics.</p>
      )}
      {deleteError && (
        <p role="alert" className="text-destructive px-4 pt-2 text-sm">
          {deleteError}
        </p>
      )}
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && <p className="text-destructive p-4 text-sm">Could not load the guidance.</p>}
      {data && data.entries.length === 0 && (
        <p className="text-muted-foreground p-4 text-sm">No guidance yet.</p>
      )}
      {data && data.entries.length > 0 && (
        <div className="space-y-4 py-3">
          <p className="px-4 text-sm">{summaryText(data.summary)}</p>
          <div className="overflow-x-auto px-2">
            <table aria-label="By metric" className={TABLE}>
              <thead>
                <tr className={HEAD}>
                  <th className={`${CELL} text-left font-normal`}>Metric</th>
                  <th className={`${CELL} num text-right font-normal`}>Beat</th>
                  <th className={`${CELL} num text-right font-normal`}>In range</th>
                  <th className={`${CELL} num text-right font-normal`}>Miss</th>
                  <th className={`${CELL} num text-right font-normal`}>Pending</th>
                  <th className={`${CELL} num text-right font-normal`}>Hit rate</th>
                </tr>
              </thead>
              <tbody>
                {data.by_metric.map((m) => (
                  <tr key={m.metric}>
                    <td className={CELL}>{m.label}</td>
                    <td className={`${CELL} num text-right`}>{m.beat}</td>
                    <td className={`${CELL} num text-right`}>{m.in_range}</td>
                    <td className={`${CELL} num text-right`}>{m.miss}</td>
                    <td className={`${CELL} num text-right`}>{m.pending}</td>
                    <td className={`${CELL} num text-right`}>{formatHitRate(m.hit_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="overflow-x-auto px-2">
            <table aria-label="Entries" className={TABLE}>
              <thead>
                <tr className={HEAD}>
                  <th className={`${CELL} text-left font-normal`}>Metric</th>
                  <th className={`${CELL} text-left font-normal`}>Period</th>
                  <th className={`${CELL} num text-right font-normal`}>Range</th>
                  <th className={`${CELL} text-left font-normal`}>Basis</th>
                  <th className={`${CELL} text-left font-normal`}>Direction</th>
                  <th className={`${CELL} text-left font-normal`}>Given on</th>
                  <th className={`${CELL} num text-right font-normal`}>Actual</th>
                  <th className={`${CELL} num text-right font-normal`}>Surprise</th>
                  <th className={`${CELL} text-left font-normal`}>Verdict</th>
                  <th className={CELL}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => {
                  const verdict = VERDICTS[entry.verdict];
                  return (
                    <tr
                      key={entry.id}
                      data-entry-id={entry.id}
                      className={entry.latest ? undefined : "text-muted-foreground"}
                      title={entry.source_note ?? undefined}
                    >
                      <td className={CELL}>
                        {entry.label}
                        {!entry.latest && <span className="ml-1 text-xs">rev.</span>}
                      </td>
                      <td className={CELL}>
                        {formatFiscalPeriod(entry.fiscal_year, entry.fiscal_period)}
                      </td>
                      <td className={`${CELL} num text-right`}>{rangeText(entry, scale)}</td>
                      <td className={CELL}>
                        {entry.basis === "reported" ? "Reported" : "Normalized"}
                      </td>
                      <td className={CELL}>{entry.direction === "higher" ? "Higher" : "Lower"}</td>
                      <td className={`${CELL} num`}>{entry.given_on}</td>
                      <td className={`${CELL} num text-right`}>
                        {formatGuidanceValue(entry.actual, entry.unit, scale)}
                      </td>
                      <td className={`${CELL} num text-right`}>
                        {formatSignedPercent(entry.surprise)}
                      </td>
                      <td className={CELL}>
                        <span data-testid="verdict" className={verdict.className}>
                          {verdict.text}
                        </span>
                      </td>
                      <td className={`${CELL} text-right`}>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Edit ${entryName(entry)}`}
                          onClick={() => setForm(entry)}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete ${entryName(entry)}`}
                          onClick={() => setToDelete(entry)}
                        >
                          <Trash2 />
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this guidance?</AlertDialogTitle>
            <AlertDialogDescription>
              {toDelete ? `${entryName(toDelete)} will be removed.` : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!toDelete) return;
                setDeleteError(null);
                remove.mutate(toDelete.id, {
                  onError: (e) =>
                    setDeleteError(companyErrorMessage(e, "Could not delete the guidance.")),
                });
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
