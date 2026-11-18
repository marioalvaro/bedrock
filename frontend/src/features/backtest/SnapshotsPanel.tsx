import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import { snapshotsQueryOptions } from "@/api/accountability";

import { ScoreControls, ScoreTable } from "./ScoreTable";
import { SnapshotSheet } from "./SnapshotSheet";
import { askedSelection, formatLocalTime, formatStat, resolveSelection } from "./backtestFormat";

const HEAD = "px-2 py-1 text-left font-medium whitespace-nowrap";
const NUM_HEAD = "px-2 py-1 text-right font-medium whitespace-nowrap";
const CELL = "px-2 py-1";
const NUM_CELL = "num px-2 py-1 text-right";

interface SnapshotsPanelProps {
  ticker: string;
}

/** The snapshots of a company, newest first, scored against the latest actuals by the backend. */
export function SnapshotsPanel({ ticker }: SnapshotsPanelProps) {
  const { data: view, isPending } = useQuery(snapshotsQueryOptions(ticker));
  const [params] = useSearchParams();
  const [openId, setOpenId] = useState<number | null>(null);

  const summary = view?.summary;
  const { metric, freq, stat } = askedSelection(params);
  const selection = useMemo(
    () => (summary ? resolveSelection(summary, { metric, freq, stat }) : null),
    [summary, metric, freq, stat],
  );

  if (!view) {
    return isPending ? (
      <p className="text-muted-foreground p-4 text-sm">Loading…</p>
    ) : (
      <p className="text-destructive p-4 text-sm">Could not load the snapshots.</p>
    );
  }
  if (view.snapshots.length === 0) {
    return (
      <p className="text-muted-foreground p-4 text-sm">
        No snapshots yet. Take one from the Scenarios tab.
      </p>
    );
  }

  const open = view.snapshots.find((snapshot) => snapshot.id === openId);

  return (
    <div>
      {selection && (
        <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <ScoreControls summary={view.summary} selection={selection} />
        </div>
      )}
      <div className="space-y-4 p-4">
        {selection ? (
          <ScoreTable summary={view.summary} selection={selection} />
        ) : (
          <p className="text-muted-foreground text-sm">
            Nothing scored yet: no actuals have landed.
          </p>
        )}
        <div className="overflow-x-auto">
          <table aria-label="Snapshots" className="text-sm">
            <thead className="text-muted-foreground">
              <tr>
                <th className={HEAD}>Taken</th>
                <th className={HEAD}>Scenario</th>
                <th className={HEAD}>Note</th>
                <th className={HEAD}>Data as of</th>
                <th className={NUM_HEAD}>Scored periods</th>
                <th className={NUM_HEAD}>Revenue MAPE</th>
              </tr>
            </thead>
            <tbody>
              {view.snapshots.map((snapshot) => (
                <tr
                  key={snapshot.id}
                  className="border-border hover:bg-muted cursor-pointer border-t"
                  onClick={() => setOpenId(snapshot.id)}
                >
                  <td className={`${CELL} whitespace-nowrap`}>
                    {/* The row's click reaches this button's too: it is the keyboard's way in. */}
                    <button type="button" className="hover:underline">
                      {formatLocalTime(snapshot.created_at)}
                    </button>
                  </td>
                  <td className={`${CELL} whitespace-nowrap`}>
                    {snapshot.scenario_name}
                    {snapshot.origin === "auto" && (
                      <span
                        className="text-prov-derived border-border ml-2 rounded border px-1 text-xs"
                        title="Taken before a new filing was loaded"
                      >
                        Auto
                      </span>
                    )}
                  </td>
                  <td className={CELL}>{snapshot.note ?? "—"}</td>
                  <td className={CELL}>{snapshot.data_as_of ?? "—"}</td>
                  <td className={NUM_CELL}>{snapshot.scored_periods}</td>
                  <td className={NUM_CELL}>{formatStat("mape", snapshot.revenue_mape)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {open && (
        <SnapshotSheet
          key={open.id}
          ticker={ticker}
          snapshot={open}
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  );
}
