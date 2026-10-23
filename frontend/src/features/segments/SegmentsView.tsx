import { useQuery } from "@tanstack/react-query";
import type { CellClassParams, CellValueChangedEvent, ColDef } from "ag-grid-community";
import { Pencil, Sigma, Trash2, Upload } from "lucide-react";
import { useMemo, useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import {
  segmentsQueryOptions,
  useDeleteSeries,
  useFillAnnualSegments,
  useSetSegmentValues,
  type SegmentFreq,
} from "@/api/context";
import type {
  SegmentBlockOut,
  SegmentPeriodOut,
  SegmentSeriesRowOut,
  SegmentValueIn,
} from "@/api/generated/types.gen";
import { DataGrid } from "@/components/DataGrid";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  formatSegmentValue,
  parseSegmentValue,
  scaleLabel,
  toSegmentText,
  type SegmentUnit,
} from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

import { ImportSheet } from "./ImportSheet";
import { SeriesForm, type SeriesFormMode } from "./SeriesForm";

const FREQS: { value: SegmentFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
];

const DIMENSION_TITLES: Record<string, string> = {
  business: "Business segments",
  geo: "Geographic segments",
};
const METRIC_TITLES: Record<string, string> = {
  revenue: "Revenue",
  operating_income: "Operating income",
};

const LABEL_COLUMN = "label";

const annualValues = (count: number) => `${count} annual value${count === 1 ? "" : "s"}`;

function blockTitle(block: SegmentBlockOut): string {
  if (block.dimension === "kpi") return "KPIs";
  const dimension = DIMENSION_TITLES[block.dimension] ?? block.dimension;
  return `${dimension} · ${METRIC_TITLES[block.metric ?? ""] ?? block.metric}`;
}

// One grid row: a series (editable) or the block's Unallocated reconciliation row.
interface SegmentRow {
  id: string;
  kind: "series" | "unallocated";
  seriesId: number | null;
  name: string;
  displayOrder: number;
  unit: SegmentUnit;
  values: Record<string, string | null>;
  // The text just typed into a cell, held until the commit handler has read it.
  edits: Record<string, string>;
}

function unitHint(unit: SegmentUnit, scale: Scale): string {
  if (unit === "pct") return "%";
  if (unit === "count") return "count";
  if (unit === "USD_per_unit") return "USD/unit";
  return scaleLabel("USD", scale);
}

function toRows(block: SegmentBlockOut, periods: SegmentPeriodOut[]): SegmentRow[] {
  const byPeriod = (values: (string | null)[]) =>
    Object.fromEntries(periods.map((period, index) => [period.key, values[index] ?? null]));
  const rows = block.series.map((series: SegmentSeriesRowOut): SegmentRow => ({
    id: `series:${series.id}`,
    kind: "series",
    seriesId: series.id,
    name: series.name,
    displayOrder: series.display_order,
    unit: series.unit as SegmentUnit,
    values: byPeriod(series.values),
    edits: {},
  }));
  if (block.unallocated) {
    rows.push({
      id: `unallocated:${block.dimension}:${block.metric}`,
      kind: "unallocated",
      seriesId: null,
      name: "Unallocated",
      displayOrder: 0,
      unit: "USD",
      values: byPeriod(block.unallocated),
      edits: {},
    });
  }
  return rows;
}

interface Handlers {
  onRename: (row: SegmentRow) => void;
  onDelete: (row: SegmentRow) => void;
}

function columnDefs(
  periods: SegmentPeriodOut[],
  scale: Scale,
  showUnit: boolean,
  { onRename, onDelete }: Handlers,
): ColDef<SegmentRow>[] {
  const labelColumn: ColDef<SegmentRow> = {
    colId: LABEL_COLUMN,
    headerName: showUnit ? "" : scaleLabel("USD", scale),
    pinned: "left",
    width: Math.min(260, Math.round(window.innerWidth * 0.5)),
    cellRenderer: ({ data }: { data?: SegmentRow }) => {
      if (!data) return null;
      if (data.kind === "unallocated") {
        return <span className="text-muted-foreground italic">{data.name}</span>;
      }
      return (
        <span className="flex min-w-0 items-center gap-1" title={data.name}>
          <span className="truncate">{data.name}</span>
          {showUnit && (
            <span className="text-muted-foreground shrink-0">· {unitHint(data.unit, scale)}</span>
          )}
          <span className="ml-auto flex shrink-0 gap-0.5">
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground cursor-pointer p-0.5"
              aria-label={`Rename ${data.name}`}
              onClick={() => onRename(data)}
            >
              <Pencil className="size-3.5" />
            </button>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground cursor-pointer p-0.5"
              aria-label={`Delete ${data.name}`}
              onClick={() => onDelete(data)}
            >
              <Trash2 className="size-3.5" />
            </button>
          </span>
        </span>
      );
    },
  };

  const periodColumns = periods.map((period): ColDef<SegmentRow> => ({
    colId: period.key,
    headerName: period.label,
    width: 100,
    headerClass: ["num", "ag-right-aligned-header"],
    editable: ({ data }) => data?.kind === "series",
    // The editor starts from the value in the page scale; the cell shows the formatted one.
    valueGetter: ({ data }) => {
      const typed = data?.edits[period.key];
      if (typed !== undefined) return typed;
      const value = data?.values[period.key] ?? null;
      return data && value !== null ? toSegmentText(value, data.unit, scale) : "";
    },
    // The grid refetches after a save, so an edit never changes the stored values; the typed
    // text is kept only until `saveCell` reads it.
    valueSetter: ({ data, newValue }) => {
      data.edits[period.key] = String(newValue ?? "");
      return true;
    },
    valueFormatter: ({ data }) =>
      data ? formatSegmentValue(data.values[period.key] ?? null, data.unit, scale) : "",
    cellClass: ({ data }: CellClassParams<SegmentRow>) => [
      "num",
      "ag-right-aligned-cell",
      ...(data?.kind === "unallocated" ? ["text-muted-foreground", "italic"] : []),
    ],
  }));
  return [labelColumn, ...periodColumns];
}

function Block({
  block,
  periods,
  scale,
  handlers,
  onAdd,
  onEdit,
}: {
  block: SegmentBlockOut;
  periods: SegmentPeriodOut[];
  scale: Scale;
  handlers: Handlers;
  onAdd: () => void;
  onEdit: (event: CellValueChangedEvent<SegmentRow>) => void;
}) {
  const title = blockTitle(block);
  const rows = useMemo(() => toRows(block, periods), [block, periods]);
  const columns = useMemo(
    () => columnDefs(periods, scale, block.dimension === "kpi", handlers),
    [periods, scale, block.dimension, handlers],
  );
  return (
    <section>
      <div className="flex items-center justify-between px-4 py-2">
        <h2 className="text-sm font-medium">{title}</h2>
        <Button
          type="button"
          size="xs"
          variant="outline"
          aria-label={`Add series to ${title}`}
          onClick={onAdd}
        >
          Add series
        </Button>
      </div>
      <DataGrid<SegmentRow>
        rowData={rows}
        columnDefs={columns}
        getRowId={(row) => row.id}
        onCellValueChanged={onEdit}
      />
    </section>
  );
}

interface SegmentsViewProps {
  ticker: string;
}

/**
 * The Segments tab: one editable grid per block (business, geographic, KPIs), with the
 * Unallocated reconciliation row, series add/rename/delete and the CSV/TSV import sheet.
 */
export function SegmentsView({ ticker }: SegmentsViewProps) {
  const [freq, setFreq] = useState<SegmentFreq>("annual");
  const scale = useScale();
  const { data, isPending, isError } = useQuery(segmentsQueryOptions(ticker, freq));
  const setValues = useSetSegmentValues(ticker);
  const remove = useDeleteSeries(ticker);
  const fill = useFillAnnualSegments(ticker);
  const [form, setForm] = useState<SeriesFormMode | null>(null);
  const [importing, setImporting] = useState(false);
  const [toDelete, setToDelete] = useState<SegmentRow | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // How many stored annual values a fill would replace, while the user is asked to confirm.
  const [replacing, setReplacing] = useState<number | null>(null);

  const handlers = useMemo<Handlers>(
    () => ({
      onRename: (row) =>
        setForm({
          type: "rename",
          id: row.seriesId as number,
          name: row.name,
          displayOrder: row.displayOrder,
        }),
      onDelete: (row) => {
        setMessage(null);
        setToDelete(row);
      },
    }),
    [],
  );

  // A commit sends that one value (an emptied cell sends null, which deletes it).
  function saveCell(
    period: SegmentPeriodOut | undefined,
    event: CellValueChangedEvent<SegmentRow>,
  ) {
    const row = event.data;
    if (!period || row.seriesId === null) return;
    const text = String(event.newValue ?? "").trim();
    delete row.edits[period.key];
    const value = text === "" ? null : parseSegmentValue(text, row.unit, scale);
    if (text !== "" && value === null) return setMessage("Enter a number");
    setMessage(null);
    const entry: SegmentValueIn = {
      fiscal_year: period.fiscal_year,
      fiscal_period: period.fiscal_period as SegmentValueIn["fiscal_period"],
      value,
    };
    setValues.mutate(
      { id: row.seriesId, values: [entry] },
      { onError: (e) => setMessage(companyErrorMessage(e, "Could not save the value.")) },
    );
  }

  // Counts first (a dry run); the fill itself runs at once, or after the user confirms a replace.
  async function startFill() {
    setMessage(null);
    setNotice(null);
    try {
      const check = await fill.mutateAsync({ dry_run: true });
      if (check.values_created + check.values_overwritten === 0) {
        return setNotice(
          check.values_unchanged > 0
            ? "Annual values already equal the sum of their quarters."
            : "Nothing to fill: a USD series needs all four quarters of a year.",
        );
      }
      if (check.values_overwritten > 0) return setReplacing(check.values_overwritten);
      await runFill();
    } catch (e) {
      setMessage(companyErrorMessage(e, "Could not fill the annual values."));
    }
  }

  async function runFill() {
    const done = await fill.mutateAsync({ dry_run: false });
    setNotice(
      `Filled ${annualValues(done.values_created + done.values_overwritten)} from the quarters.`,
    );
  }

  function confirmFill() {
    runFill().catch((e) => setMessage(companyErrorMessage(e, "Could not fill the annual values.")));
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
          onValueChange={(value) => value && setFreq(value as SegmentFreq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <UnitToggle />
        <div className="ml-auto flex flex-wrap gap-2">
          {freq === "annual" && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={fill.isPending}
              onClick={startFill}
            >
              <Sigma /> Fill from quarterly
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setForm({ type: "new", dimension: "business", metric: "revenue" })}
          >
            Add series
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setImporting(true)}>
            <Upload /> Import
          </Button>
        </div>
      </div>
      {message && (
        <p role="alert" className="text-destructive px-4 py-2 text-sm">
          {message}
        </p>
      )}
      {notice && (
        <p role="status" className="text-muted-foreground px-4 py-2 text-sm">
          {notice}
        </p>
      )}
      {form && (
        <SeriesForm
          key={
            form.type === "rename" ? `rename-${form.id}` : `new-${form.dimension}-${form.metric}`
          }
          ticker={ticker}
          mode={form}
          onDone={() => setForm(null)}
        />
      )}
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && <p className="text-destructive p-4 text-sm">Could not load the segments.</p>}
      {data && data.blocks.length === 0 && (
        <p className="text-muted-foreground p-4 text-sm">
          No segments or KPIs yet. Add a series, or import a CSV or TSV.
        </p>
      )}
      {data?.blocks.map((block) => (
        <Block
          key={`${block.dimension}-${block.metric}`}
          block={block}
          periods={data.periods}
          scale={scale}
          handlers={handlers}
          onAdd={() =>
            setForm({
              type: "new",
              dimension: block.dimension as "business" | "geo" | "kpi",
              metric: block.metric ?? "revenue",
            })
          }
          onEdit={(event) =>
            saveCell(
              data.periods.find((period) => period.key === event.column.getColId()),
              event,
            )
          }
        />
      ))}
      <ImportSheet
        key={importing ? "open" : "closed"}
        ticker={ticker}
        open={importing}
        scale={scale}
        onClose={() => setImporting(false)}
      />
      <AlertDialog open={replacing !== null} onOpenChange={(open) => !open && setReplacing(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Replace annual values?</AlertDialogTitle>
            <AlertDialogDescription>
              {replacing !== null &&
                `${annualValues(replacing)} already entered will be replaced by the sum of their quarters.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmFill}>Replace</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this series?</AlertDialogTitle>
            <AlertDialogDescription>
              {toDelete?.name} and all its values will be removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete?.seriesId != null) {
                  remove.mutate(toDelete.seriesId, {
                    onError: (e) =>
                      setMessage(companyErrorMessage(e, "Could not delete the series.")),
                  });
                }
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
