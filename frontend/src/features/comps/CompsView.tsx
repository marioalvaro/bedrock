import { useQuery } from "@tanstack/react-query";
import type { CellClassParams, ColDef } from "ag-grid-community";
import { useMemo, useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { comparisonQueryOptions, compsSetsQueryOptions, useDeleteCompsSet } from "@/api/context";
import type { CompsOut, CompsRowOut } from "@/api/generated/types.gen";
import type { Basis } from "@/api/statements";
import { DataGrid } from "@/components/DataGrid";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { formatRange, formatRank, formatRatio, formatVsMedian } from "@/lib/format";

import { MemberEditor, SetNameForm, type SetNameMode } from "./CompsSetEditor";

const BASES: { value: Basis; label: string }[] = [
  { value: "reported", label: "Reported" },
  { value: "normalized", label: "Normalized" },
];

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

interface GridRow {
  id: string;
  heading: boolean;
  label: string;
  row: CompsRowOut | null;
}

// A heading row per category (in order of first appearance), then that category's rows.
function toGridRows(table: CompsOut): GridRow[] {
  const categories = [...new Set(table.rows.map((row) => row.category))];
  return categories.flatMap((category) => [
    { id: `category:${category}`, heading: true, label: category, row: null },
    ...table.rows
      .filter((row) => row.category === category)
      .map((row) => ({ id: row.code, heading: false, label: row.label, row })),
  ]);
}

// A company's value with "†" when that company carries a caveat for the row.
function companyCell(row: CompsRowOut, ticker: string, value: string | null): string {
  const text = formatRatio(value, row.unit);
  return row.caveats.some((caveat) => caveat.ticker === ticker) ? `${text} †` : text;
}

// One note per company and caveat text, listing the rows it covers.
function caveatNotes(table: CompsOut): string[] {
  const notes = new Map<string, { ticker: string; text: string; labels: string[] }>();
  for (const row of table.rows) {
    for (const { ticker, text } of row.caveats) {
      const key = `${ticker}\u0000${text}`;
      const note = notes.get(key) ?? { ticker, text, labels: [] };
      note.labels.push(row.label);
      notes.set(key, note);
    }
  }
  return [...notes.values()].map(
    ({ ticker, text, labels }) => `† ${ticker} (${labels.join(", ")}): ${text}`,
  );
}

function valueColumn(
  colId: string,
  headerName: string,
  format: (row: CompsRowOut) => string,
  extraClass: string[] = [],
  headerTooltip?: string,
): ColDef<GridRow> {
  return {
    colId,
    headerName,
    headerTooltip,
    width: 110,
    headerClass: ["num", "ag-right-aligned-header"],
    valueGetter: ({ data }) => (data?.row ? format(data.row) : ""),
    cellClass: ({ data }: CellClassParams<GridRow>) =>
      data?.heading ? ["num"] : ["num", "ag-right-aligned-cell", ...extraClass],
  };
}

function columnDefs(table: CompsOut): ColDef<GridRow>[] {
  const [target, ...peers] = table.companies;
  const tooltip = (company: (typeof table.companies)[number]) =>
    [company.name, company.ttm_period].filter(Boolean).join(" · ");
  return [
    {
      colId: "label",
      headerName: "Metric",
      pinned: "left",
      width: Math.min(220, Math.round(window.innerWidth * 0.4)),
      valueGetter: ({ data }) => data?.label ?? "",
      cellClass: ({ data }: CellClassParams<GridRow>) => (data?.heading ? ["font-medium"] : []),
    },
    valueColumn(
      "target",
      target?.ticker ?? table.ticker,
      (row) => companyCell(row, table.ticker, row.target),
      ["font-semibold"],
      target && tooltip(target),
    ),
    ...peers.map((peer, index) =>
      valueColumn(
        `peer:${peer.ticker}`,
        peer.ticker,
        (row) => companyCell(row, peer.ticker, row.peers[index] ?? null),
        [],
        tooltip(peer),
      ),
    ),
    valueColumn("median", "Peer median", (row) => formatRatio(row.peer_median, row.unit)),
    {
      ...valueColumn("range", "Peer range", (row) =>
        formatRange(row.peer_min, row.peer_max, row.unit),
      ),
      width: 150,
    },
    valueColumn("vs", "vs median", (row) => formatVsMedian(row.target_vs_median, row.unit)),
    { ...valueColumn("rank", "Rank", (row) => formatRank(row.target_rank, row.n)), width: 80 },
  ];
}

interface ComparisonProps {
  ticker: string;
  setId: number;
  basis: Basis;
}

function Comparison({ ticker, setId, basis }: ComparisonProps) {
  const { data, isPending, isError } = useQuery(comparisonQueryOptions(ticker, setId, basis));
  const rows = useMemo(() => (data ? toGridRows(data) : []), [data]);
  const columns = useMemo(() => (data ? columnDefs(data) : []), [data]);
  const notes = useMemo(() => (data ? caveatNotes(data) : []), [data]);

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (isError)
    return <p className="text-destructive p-4 text-sm">Could not load the comparison.</p>;
  return (
    <>
      <DataGrid<GridRow> rowData={rows} columnDefs={columns} getRowId={(row) => row.id} />
      {notes.length > 0 && (
        <div className="text-muted-foreground space-y-1 px-4 py-2 text-xs">
          {notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      )}
    </>
  );
}

interface CompsViewProps {
  ticker: string;
}

/**
 * The Comps tab: the company's peer sets (picker, New / Rename / Delete, member chips with the
 * suggested peers first) and the comparison of multiples and key ratios against the peer median,
 * range and rank. See erd/workspace.md "Frontend (M3)".
 */
export function CompsView({ ticker }: CompsViewProps) {
  const { data: sets, isPending, isError } = useQuery(compsSetsQueryOptions(ticker));
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [basis, setBasis] = useState<Basis>("reported");
  const [nameForm, setNameForm] = useState<SetNameMode | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const remove = useDeleteCompsSet(ticker);

  // The picked set, else the first one (also after the picked set is deleted).
  const set = sets?.find((candidate) => candidate.id === selectedId) ?? sets?.[0] ?? null;

  function closeNameForm(id: number | null) {
    if (id !== null) setSelectedId(id);
    setNameForm(null);
  }

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (isError)
    return <p className="text-destructive p-4 text-sm">Could not load the comps sets.</p>;

  const form = nameForm && <SetNameForm ticker={ticker} mode={nameForm} onDone={closeNameForm} />;

  if (set === null) {
    return (
      <div>
        {form ?? (
          <div className="space-y-2 p-4">
            <p className="text-muted-foreground text-sm">No comps sets yet.</p>
            <Button size="sm" onClick={() => setNameForm({ type: "new" })}>
              New comps set
            </Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <select
          aria-label="Comps set"
          value={String(set.id)}
          onChange={(e) => setSelectedId(Number(e.target.value))}
          className={SELECT}
        >
          {sets.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.name}
            </option>
          ))}
        </select>
        <Button variant="outline" size="sm" onClick={() => setNameForm({ type: "new" })}>
          New
        </Button>
        <Button variant="outline" size="sm" onClick={() => setNameForm({ type: "rename", set })}>
          Rename
        </Button>
        <Button variant="outline" size="sm" onClick={() => setConfirmDelete(true)}>
          Delete
        </Button>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Basis"
          className="ml-auto"
          value={basis}
          onValueChange={(value) => value && setBasis(value as Basis)}
        >
          {BASES.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      {deleteError && (
        <p role="alert" className="text-destructive px-4 pt-2 text-sm">
          {deleteError}
        </p>
      )}
      {form}
      <MemberEditor
        key={`${set.id}:${set.members.map((member) => member.ticker).join()}`}
        ticker={ticker}
        set={set}
      />
      <Comparison ticker={ticker} setId={set.id} basis={basis} />
      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this comps set?</AlertDialogTitle>
            <AlertDialogDescription>{`"${set.name}" and its peer list will be removed.`}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setDeleteError(null);
                remove.mutate(set.id, {
                  onError: (e) =>
                    setDeleteError(companyErrorMessage(e, "Could not delete the comps set.")),
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
