import { useQuery } from "@tanstack/react-query";
import type { CellClassParams, ColDef, ProcessCellForExportParams } from "ag-grid-community";
import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown, Download } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";

import {
  statementQueryOptions,
  type Basis,
  type CommonSizeBase,
  type Freq,
  type StatementType,
} from "@/api/statements";
import { noteLinksQueryOptions } from "@/api/context";
import type { StatementOut } from "@/api/generated/types.gen";
import { DataGrid, type DataGridHandle } from "@/components/DataGrid";
import { ProvenanceLegend } from "@/components/ProvenanceLegend";
import { UnitToggle } from "@/components/UnitToggle";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  formatCsvPercent,
  formatCsvValue,
  formatPercent,
  formatValue,
  scaleLabel,
} from "@/lib/format";
import { downloadText } from "@/lib/download";
import { useScale, type Scale } from "@/lib/scale";

import { CellDetailSheet, type CellTarget } from "./CellDetailSheet";
import {
  canExplain,
  cellNoteCount,
  csvLabel,
  expandableCodes,
  lineNoteCount,
  noteIndex,
  rowUnitHint,
  toGridRows,
  type GridRow,
  type NoteIndex,
} from "./grid";
import { LineNotesSheet, type LineTarget } from "./LineNotesSheet";

const FREQS: { value: Freq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
  { value: "ttm", label: "TTM" },
];

const BASES: { value: Basis; label: string }[] = [
  { value: "reported", label: "Reported" },
  { value: "normalized", label: "Normalized" },
];

const FILE_TYPES: Record<StatementType, string> = { IS: "IS", BS: "BS", CF: "CF" };
const LABEL_COLUMN = "label";

const CHEVRON = "size-4 shrink-0";

// A sub-row is secondary; growth is also italic, and coloured by the direction of its sign.
function labelClass(row: GridRow | undefined): string {
  if (!row || row.kind === "line") return "";
  return row.kind === "yoy" ? "text-muted-foreground italic" : "text-muted-foreground";
}

function growthClass(row: GridRow, key: string): string[] {
  if (row.kind !== "yoy") return [];
  const value = row.values[key];
  if (value === null || value === undefined) return ["italic"];
  const sign = Number(value);
  return ["italic", ...(sign > 0 ? ["text-positive"] : sign < 0 ? ["text-negative"] : [])];
}

function formatCell(row: GridRow, key: string, scale: Scale): string {
  const value = row.values[key] ?? null;
  if (row.kind === "balance_check") {
    return row.ok?.[key] ? "✓" : formatValue(value, row.unit, scale);
  }
  if (row.kind === "yoy" || row.kind === "common_size") return formatPercent(value);
  return formatValue(value, row.unit, scale);
}

function csvCell(row: GridRow, key: string, scale: Scale): string {
  const value = row.values[key] ?? null;
  if (row.kind === "yoy" || row.kind === "common_size") return formatCsvPercent(value);
  return formatCsvValue(value, row.unit, scale);
}

function columnDefs(
  payload: StatementOut,
  scale: Scale,
  notes: NoteIndex,
  onToggle: (code: string) => void,
  onLineNotes: (row: GridRow) => void,
): ColDef<GridRow>[] {
  const labelColumn: ColDef<GridRow> = {
    colId: LABEL_COLUMN,
    headerName: scaleLabel("USD", scale),
    pinned: "left",
    // Pinned, so on a phone it must leave room for the periods.
    width: Math.min(240, Math.round(window.innerWidth * 0.4)),
    cellClass: (params: CellClassParams<GridRow>) => labelClass(params.data),
    cellRenderer: ({ data }: { data?: GridRow }) => {
      if (!data) return null;
      const hint = rowUnitHint(data.unit, scale);
      return (
        <span
          className="flex min-w-0 items-center gap-1"
          style={{ paddingLeft: `${data.depth * 12}px` }}
          title={data.label}
        >
          {data.hasChildren ? (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground cursor-pointer"
              aria-label={`${data.expanded ? "Collapse" : "Expand"} ${data.label}`}
              aria-expanded={data.expanded}
              onClick={() => onToggle(data.code)}
            >
              {data.expanded ? (
                <ChevronDown className={CHEVRON} />
              ) : (
                <ChevronRight className={CHEVRON} />
              )}
            </button>
          ) : (
            <span className={CHEVRON} aria-hidden />
          )}
          <span className="truncate">{data.label}</span>
          {lineNoteCount(notes, data) > 0 && (
            <button
              type="button"
              className="text-note-marker cursor-pointer leading-none"
              aria-label={`Notes on ${data.label}`}
              onClick={() => onLineNotes(data)}
            >
              •
            </button>
          )}
          {hint && <span className="text-muted-foreground shrink-0">· {hint}</span>}
        </span>
      );
    },
  };

  const periodColumns = payload.periods.map((period): ColDef<GridRow> => ({
    colId: period.key,
    headerName: period.label,
    width: 100,
    // The heading sits over the numbers: AG Grid's right-aligned classes move the header
    // label as well as the cell text.
    headerClass: ["num", "ag-right-aligned-header"],
    valueGetter: ({ data }) => data?.values[period.key] ?? null,
    valueFormatter: ({ data }) => (data ? formatCell(data, period.key, scale) : ""),
    cellClass: ({ data }: CellClassParams<GridRow>) => {
      if (!data) return "num";
      const classes = ["num", "ag-right-aligned-cell", ...growthClass(data, period.key)];
      const provenance = data.provenance[period.key];
      if (provenance === "derived") classes.push("prov-derived");
      if (provenance === "normalized") classes.push("prov-normalized");
      if (canExplain(data, period)) classes.push("cursor-pointer", "hover:underline");
      if (cellNoteCount(notes, data, period) > 0) classes.push("has-note");
      if (data.kind === "balance_check" && data.ok?.[period.key] === false) {
        classes.push("text-destructive");
      }
      return classes;
    },
  }));

  return [labelColumn, ...periodColumns];
}

interface StatementViewProps {
  ticker: string;
  cik: string;
  type: StatementType;
}

export function StatementView({ ticker, cik, type }: StatementViewProps) {
  const [freq, setFreq] = useState<Freq>("annual");
  const [basis, setBasis] = useState<Basis>("reported");
  const [yoy, setYoy] = useState(false);
  const [commonSize, setCommonSize] = useState(false);
  const [showEmpty, setShowEmpty] = useState(false);
  const [base, setBase] = useState<CommonSizeBase>("total");
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [selected, setSelected] = useState<CellTarget | null>(null);
  const [lineTarget, setLineTarget] = useState<LineTarget | null>(null);
  const scale = useScale();
  const grid = useRef<DataGridHandle>(null);

  const { data, isPending, isError, isPlaceholderData } = useQuery(
    statementQueryOptions(ticker, type, freq, base, basis),
  );

  // The markers are optional: a failed links request leaves the statement without them.
  const { data: links } = useQuery(noteLinksQueryOptions(ticker));
  const notes = useMemo(() => noteIndex(links ?? []), [links]);
  const openLineNotes = useCallback(
    (row: GridRow) => setLineTarget({ code: row.code, label: row.label }),
    [],
  );

  const toggle = useCallback((code: string) => {
    setExpanded((open) => {
      const next = new Set(open);
      if (!next.delete(code)) next.add(code);
      return next;
    });
  }, []);
  const expandable = useMemo(
    () => (data ? expandableCodes(data, showEmpty) : []),
    [data, showEmpty],
  );
  const allOpen = expandable.length > 0 && expandable.every((code) => expanded.has(code));

  const rows = useMemo(
    () => (data ? toGridRows(data, { yoy, commonSize, expanded, showEmpty }) : []),
    [data, yoy, commonSize, expanded, showEmpty],
  );
  const columns = useMemo(
    () => (data ? columnDefs(data, scale, notes, toggle, openLineNotes) : []),
    [data, scale, notes, toggle, openLineNotes],
  );

  function exportCsv() {
    if (!data) return;
    const csv = grid.current?.getCsv({
      processCellCallback: ({ column, node }: ProcessCellForExportParams<GridRow>) => {
        const row = node?.data;
        if (!row) return "";
        const colId = column.getColId();
        return colId === LABEL_COLUMN ? csvLabel(row) : csvCell(row, colId, scale);
      },
    });
    if (csv) downloadText(`${ticker}_${FILE_TYPES[type]}_${freq}.csv`, csv, "text/csv");
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
          onValueChange={(value) => value && setFreq(value as Freq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value} disabled={value === "ttm" && type === "BS"}>
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
        <Toggle size="sm" variant="outline" pressed={yoy} onPressedChange={setYoy}>
          YoY
        </Toggle>
        <Toggle size="sm" variant="outline" pressed={commonSize} onPressedChange={setCommonSize}>
          Common size
        </Toggle>
        {commonSize && (
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            spacing={0}
            aria-label="Common size base"
            value={base}
            onValueChange={(value) => value && setBase(value as CommonSizeBase)}
          >
            <ToggleGroupItem value="total">
              {type === "BS" ? "Total assets" : "Revenue"}
            </ToggleGroupItem>
            <ToggleGroupItem value="parent">Parent row</ToggleGroupItem>
          </ToggleGroup>
        )}
        <Toggle size="sm" variant="outline" pressed={showEmpty} onPressedChange={setShowEmpty}>
          Show empty lines
        </Toggle>
        <Button
          variant="outline"
          size="sm"
          disabled={expandable.length === 0}
          onClick={() => setExpanded(allOpen ? new Set() : new Set(expandable))}
        >
          {allOpen ? <ChevronsDownUp /> : <ChevronsUpDown />}
          {allOpen ? "Collapse all" : "Expand all"}
        </Button>
        <UnitToggle />
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          aria-label="Download CSV"
          disabled={!data || isPlaceholderData}
          onClick={exportCsv}
        >
          <Download /> CSV
        </Button>
      </div>
      <div className="px-4 py-1">
        <ProvenanceLegend />
      </div>
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && <p className="text-destructive p-4 text-sm">Could not load the statement.</p>}
      {data && (
        <DataGrid<GridRow>
          ref={grid}
          rowData={rows}
          columnDefs={columns}
          getRowId={(row) => row.id}
          onCellClicked={({ data: row, column }) => {
            const period = data.periods.find((p) => p.key === column.getColId());
            if (!row || !period || !canExplain(row, period)) return;
            setSelected({
              code: row.code,
              label: row.label,
              unit: row.unit,
              adjustable: row.adjustable,
              fiscalYear: period.fiscal_year,
              fiscalPeriod: period.fiscal_period,
            });
          }}
        />
      )}
      <CellDetailSheet
        ticker={ticker}
        cik={cik}
        target={selected}
        scale={scale}
        onClose={() => setSelected(null)}
      />
      <LineNotesSheet ticker={ticker} target={lineTarget} onClose={() => setLineTarget(null)} />
    </div>
  );
}
