import { useQuery } from "@tanstack/react-query";
import type {
  CellClassParams,
  CellClickedEvent,
  ColDef,
  ProcessCellForExportParams,
} from "ag-grid-community";
import { Download } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { ratiosQueryOptions, type AnalysisFreq } from "@/api/analysis";
import type { PeriodOut, RatiosOut } from "@/api/generated/types.gen";
import type { Basis } from "@/api/statements";
import { DataGrid, type DataGridHandle } from "@/components/DataGrid";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { downloadText } from "@/lib/download";
import { NoteMarker } from "@/features/notes/NoteMarker";
import { SubjectNotesSheet } from "@/features/notes/SubjectNotesSheet";
import {
  cellNotes,
  subjectNotes,
  type NoteIndex,
  type SubjectTarget,
} from "@/features/notes/subjects";
import { useNoteIndex } from "@/features/notes/useNoteIndex";
import { MultiplesTable } from "@/features/ratios/MultiplesTable";
import { RatioCellSheet, type RatioCellTarget } from "@/features/ratios/RatioCellSheet";
import { formatCsvRatio, formatRatio, type RatioUnit } from "@/lib/format";

const FREQS: { value: AnalysisFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "ttm", label: "TTM" },
];

const BASES: { value: Basis; label: string }[] = [
  { value: "reported", label: "Reported" },
  { value: "normalized", label: "Normalized" },
];

const LABEL_COLUMN = "label";

interface GridRow {
  id: string;
  label: string;
  heading: boolean;
  definition: string | null;
  caveat: boolean;
  unit: RatioUnit | null;
  values: (string | null)[];
}

// A heading row per category (in order of first appearance), then that category's ratios.
function toGridRows(payload: RatiosOut): GridRow[] {
  const categories = [...new Set(payload.rows.map((row) => row.category))];
  return categories.flatMap((category) => [
    {
      id: `category:${category}`,
      label: category,
      heading: true,
      definition: null,
      caveat: false,
      unit: null,
      values: [],
    },
    ...payload.rows
      .filter((row) => row.category === category)
      .map((row) => ({
        id: row.code,
        label: row.label,
        heading: false,
        definition: row.definition,
        caveat: row.caveat !== null,
        unit: row.unit as RatioUnit,
        values: row.values,
      })),
  ]);
}

// One note per distinct caveat text, in first-appearance order.
function caveatNotes(payload: RatiosOut): { text: string; labels: string[] }[] {
  const notes = new Map<string, string[]>();
  for (const row of payload.rows) {
    if (row.caveat === null) continue;
    notes.set(row.caveat, [...(notes.get(row.caveat) ?? []), row.label]);
  }
  return [...notes].map(([text, labels]) => ({ text, labels }));
}

// Notes sit on a ratio's FY or quarter cell: not on a category heading, not on TTM. Every other
// value cell opens its details.
function notable(row: GridRow, period: PeriodOut): boolean {
  return !row.heading && !period.key.startsWith("TTM");
}

function columnDefs(
  payload: RatiosOut,
  markers: NoteIndex,
  onRatioNotes: (row: GridRow) => void,
): ColDef<GridRow>[] {
  const labelColumn: ColDef<GridRow> = {
    colId: LABEL_COLUMN,
    headerName: "Ratio",
    pinned: "left",
    width: Math.min(240, Math.round(window.innerWidth * 0.4)),
    cellRenderer: ({ data }: { data?: GridRow }) => {
      if (!data) return null;
      const text = data.caveat ? `${data.label} †` : data.label;
      return (
        <span className="flex min-w-0 items-center gap-1">
          <span
            className={data.heading ? "font-medium" : undefined}
            title={data.definition ?? undefined}
          >
            {text}
          </span>
          {!data.heading && subjectNotes(markers, "ratio", data.id) > 0 && (
            <NoteMarker label={data.label} onClick={() => onRatioNotes(data)} />
          )}
        </span>
      );
    },
  };

  const periodColumns = payload.periods.map((period): ColDef<GridRow> => ({
    colId: period.key,
    headerName: period.label,
    width: 100,
    headerClass: ["num", "ag-right-aligned-header"],
    valueGetter: ({ data }) => data?.values[payload.periods.indexOf(period)] ?? null,
    valueFormatter: ({ data }) => {
      if (!data || data.heading || !data.unit) return "";
      return formatRatio(data.values[payload.periods.indexOf(period)] ?? null, data.unit);
    },
    cellClass: ({ data }: CellClassParams<GridRow>) => {
      const classes = ["num", "ag-right-aligned-cell"];
      if (!data || data.heading) return classes;
      classes.push("cursor-pointer", "hover:underline");
      if (
        notable(data, period) &&
        cellNotes(markers, "ratio", data.id, period.fiscal_year, period.fiscal_period) > 0
      ) {
        classes.push("has-note");
      }
      return classes;
    },
  }));

  return [labelColumn, ...periodColumns];
}

interface RatiosViewProps {
  ticker: string;
}

/**
 * The Ratios tab: toolbar Annual | TTM, Reported | Normalized and CSV; a DataGrid with a heading
 * row per category, then its ratios; a "†" note for caveats. See erd/workspace.md "Frontend (M2)".
 */
export function RatiosView({ ticker }: RatiosViewProps) {
  const [freq, setFreq] = useState<AnalysisFreq>("annual");
  const [basis, setBasis] = useState<Basis>("reported");
  const grid = useRef<DataGridHandle>(null);
  const markers = useNoteIndex(ticker);
  const [target, setTarget] = useState<SubjectTarget | null>(null);
  const [cellTarget, setCellTarget] = useState<RatioCellTarget | null>(null);

  const { data, isPending, isError } = useQuery(ratiosQueryOptions(ticker, freq, basis));

  const rows = useMemo(() => (data ? toGridRows(data) : []), [data]);
  const columns = useMemo(
    () =>
      data
        ? columnDefs(data, markers, (row) =>
            setTarget({ kind: "ratio", code: row.id, label: row.label }),
          )
        : [],
    [data, markers],
  );
  const notes = useMemo(() => (data ? caveatNotes(data) : []), [data]);
  const empty = data !== undefined && (data.rows.length === 0 || data.periods.length === 0);

  function openCell({ data: row, column }: CellClickedEvent<GridRow>) {
    const period = data?.periods.find((p) => p.key === column.getColId());
    if (!row || row.heading || !period) return;
    setCellTarget({
      code: row.id,
      label: row.label,
      periodLabel: period.label,
      fiscalYear: period.fiscal_year,
      fiscalPeriod: period.fiscal_period,
      ttm: period.key.startsWith("TTM"),
    });
  }

  function exportCsv() {
    const csv = grid.current?.getCsv({
      processCellCallback: ({ column, node }: ProcessCellForExportParams<GridRow>) => {
        const row = node?.data;
        if (!row) return "";
        const colId = column.getColId();
        if (colId === LABEL_COLUMN) return row.label;
        if (row.heading || !row.unit) return "";
        const index = data?.periods.findIndex((p) => p.key === colId) ?? -1;
        return formatCsvRatio(row.values[index] ?? null, row.unit);
      },
    });
    if (csv) downloadText(`${ticker}_ratios_${freq}.csv`, csv, "text/csv");
  }

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Frequency"
          value={freq}
          onValueChange={(value) => value && setFreq(value as AnalysisFreq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Basis"
          value={basis}
          onValueChange={(value) => value && setBasis(value as Basis)}
        >
          {BASES.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          aria-label="Download CSV"
          disabled={!data || empty}
          onClick={exportCsv}
        >
          <Download /> CSV
        </Button>
      </div>
      <MultiplesTable ticker={ticker} basis={basis} />
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && <p className="text-destructive p-4 text-sm">Could not load the ratios.</p>}
      {empty && <p className="text-muted-foreground p-4 text-sm">No ratios for this company.</p>}
      {data && !empty && (
        <>
          <DataGrid<GridRow>
            ref={grid}
            rowData={rows}
            columnDefs={columns}
            getRowId={(row) => row.id}
            onCellClicked={openCell}
          />
          {notes.length > 0 && (
            <div className="text-muted-foreground space-y-1 px-4 py-2 text-xs">
              {notes.map(({ text, labels }) => (
                <p key={text}>
                  † {labels.join(", ")}: {text}
                </p>
              ))}
            </div>
          )}
        </>
      )}
      <SubjectNotesSheet ticker={ticker} target={target} onClose={() => setTarget(null)} />
      <RatioCellSheet
        ticker={ticker}
        freq={freq}
        basis={basis}
        target={cellTarget}
        onClose={() => setCellTarget(null)}
      />
    </div>
  );
}
