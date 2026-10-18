import { useQuery } from "@tanstack/react-query";
import type { CellClassParams, ColDef, ProcessCellForExportParams } from "ag-grid-community";
import { Download } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { capitalAllocationQueryOptions, type AnalysisFreq } from "@/api/analysis";
import type { CapitalAllocationOut } from "@/api/generated/types.gen";
import { DataGrid, type DataGridHandle } from "@/components/DataGrid";
import { UnitToggle } from "@/components/UnitToggle";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { downloadText } from "@/lib/download";
import {
  formatCsvPercent,
  formatCsvRatio,
  formatCsvValue,
  formatPercent,
  formatRatio,
  formatValue,
  scaleLabel,
} from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

const FREQS: { value: AnalysisFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "ttm", label: "TTM" },
];

const LABEL_COLUMN = "label";
const UNIT_HINTS: Record<string, string> = { x: "x", pct: "%" };

interface GridRow {
  id: string;
  label: string;
  /** The line's label when this is a "% of …" sub-row. */
  parentLabel: string | null;
  unit: string;
  isSub: boolean;
  values: (string | null)[];
}

// Each line, then (when `showPercents`) a "% of CFO" / "% of FCF" sub-row for each share that
// has at least one value.
function toGridRows(data: CapitalAllocationOut, showPercents: boolean): GridRow[] {
  return data.rows.flatMap((row): GridRow[] => {
    const line: GridRow = {
      id: row.code,
      label: row.label,
      parentLabel: null,
      unit: row.unit,
      isSub: false,
      values: row.values,
    };
    if (!showPercents) return [line];
    const sub = (key: "pct_of_cfo" | "pct_of_fcf", label: string): GridRow[] => {
      const values = row[key];
      if (!values?.some((value) => value !== null)) return [];
      return [
        {
          id: `${row.code}:${key}`,
          label,
          parentLabel: row.label,
          unit: "pct",
          isSub: true,
          values,
        },
      ];
    };
    return [line, ...sub("pct_of_cfo", "% of CFO"), ...sub("pct_of_fcf", "% of FCF")];
  });
}

function periodValue(row: GridRow, index: number): string | null {
  return row.values[index] ?? null;
}

function formatCell(row: GridRow, index: number, scale: Scale): string {
  const value = periodValue(row, index);
  if (row.isSub) return formatPercent(value);
  if (row.unit === "x" || row.unit === "pct") return formatRatio(value, row.unit);
  return formatValue(value, row.unit, scale);
}

function csvCell(row: GridRow, index: number, scale: Scale): string {
  const value = periodValue(row, index);
  if (row.isSub) return formatCsvPercent(value);
  if (row.unit === "x" || row.unit === "pct") return formatCsvRatio(value, row.unit);
  return formatCsvValue(value, row.unit, scale);
}

function columnDefs(data: CapitalAllocationOut, scale: Scale): ColDef<GridRow>[] {
  const labelColumn: ColDef<GridRow> = {
    colId: LABEL_COLUMN,
    headerName: scaleLabel("USD", scale),
    pinned: "left",
    // Pinned, so on a phone it must leave room for the periods.
    width: Math.min(240, Math.round(window.innerWidth * 0.4)),
    cellClass: ({ data: row }: CellClassParams<GridRow>) =>
      row?.isSub ? "text-muted-foreground" : "",
    cellRenderer: ({ data: row }: { data?: GridRow }) => {
      if (!row) return null;
      const hint = row.isSub ? undefined : UNIT_HINTS[row.unit];
      return (
        <span
          className="flex min-w-0 items-center gap-1"
          style={{ paddingLeft: row.isSub ? "20px" : undefined }}
          title={row.label}
        >
          <span className="truncate">{row.label}</span>
          {hint && <span className="text-muted-foreground shrink-0">· {hint}</span>}
        </span>
      );
    },
  };

  const periodColumns = data.periods.map((period, index): ColDef<GridRow> => ({
    colId: period.key,
    headerName: period.label,
    width: 100,
    // The heading sits over the numbers: AG Grid's right-aligned classes move the header too.
    headerClass: ["num", "ag-right-aligned-header"],
    valueGetter: ({ data: row }) => (row ? periodValue(row, index) : null),
    valueFormatter: ({ data: row }) => (row ? formatCell(row, index, scale) : ""),
    cellClass: ["num", "ag-right-aligned-cell"],
  }));

  return [labelColumn, ...periodColumns];
}

interface CapitalViewProps {
  ticker: string;
}

/**
 * The Capital tab: toolbar Annual | TTM, a "% of CFO / FCF" toggle, the scale and CSV; a
 * DataGrid of the capital-allocation rows with the two % sub-rows under the rows that have them.
 */
export function CapitalView({ ticker }: CapitalViewProps) {
  const [freq, setFreq] = useState<AnalysisFreq>("annual");
  const [showPercents, setShowPercents] = useState(false);
  const scale = useScale();
  const grid = useRef<DataGridHandle>(null);

  const { data, isPending, isError } = useQuery(capitalAllocationQueryOptions(ticker, freq));

  const rows = useMemo(() => (data ? toGridRows(data, showPercents) : []), [data, showPercents]);
  const columns = useMemo(() => (data ? columnDefs(data, scale) : []), [data, scale]);
  const empty = data !== undefined && (data.rows.length === 0 || data.periods.length === 0);

  function exportCsv() {
    if (!data) return;
    const csv = grid.current?.getCsv({
      processCellCallback: ({ column, node }: ProcessCellForExportParams<GridRow>) => {
        const row = node?.data;
        if (!row) return "";
        const colId = column.getColId();
        if (colId === LABEL_COLUMN) {
          return row.parentLabel ? `${row.parentLabel} ${row.label}` : row.label;
        }
        const index = data.periods.findIndex((period) => period.key === colId);
        return csvCell(row, index, scale);
      },
    });
    if (csv) downloadText(`${ticker}_capital_${freq}.csv`, csv, "text/csv");
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
        <Toggle
          size="sm"
          variant="outline"
          pressed={showPercents}
          onPressedChange={setShowPercents}
        >
          % of CFO / FCF
        </Toggle>
        <UnitToggle />
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
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && (
        <p className="text-destructive p-4 text-sm">Could not load the capital allocation.</p>
      )}
      {empty && (
        <p className="text-muted-foreground p-4 text-sm">No capital allocation for this company.</p>
      )}
      {data && !empty && (
        <DataGrid<GridRow>
          ref={grid}
          rowData={rows}
          columnDefs={columns}
          getRowId={(row) => row.id}
        />
      )}
    </div>
  );
}
