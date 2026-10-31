import { useQuery } from "@tanstack/react-query";
import type { CellClassParams, CellValueChangedEvent, ColDef } from "ag-grid-community";
import { RotateCcw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import type {
  DriverGridOut,
  DriverRowIn,
  DriverRowOut,
  ScenarioOut,
} from "@/api/generated/types.gen";
import { driversQueryOptions, usePutDrivers } from "@/api/scenarios";
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
import { scaleLabel } from "@/lib/format";
import type { Scale } from "@/lib/scale";

import {
  driverEdit,
  driverReset,
  forecastCell,
  forecastLabel,
  formatDriverValue,
  historyLabel,
  parseDriverText,
  toDriverRows,
  type DriverGridRow,
  type DriverMode,
  type DriverUnit,
} from "./driverCells";

const MODE_LABELS: Record<DriverMode, string> = { value: "Value", offset: "vs Base" };
const NUM = ["num", "ag-right-aligned-cell"];
const NUM_HEADER = ["num", "ag-right-aligned-header"];

// A grid row with the text just typed into a cell, held until the commit handler reads it (G29).
type Row = DriverGridRow & { edits: Record<string, string> };

const historyColumn = (year: number) => `h:${year}`;
const forecastColumn = (year: number) => `f:${year}`;

function unitHint(unit: DriverUnit, scale: Scale): string {
  if (unit === "pct") return "%";
  if (unit === "days") return "days";
  return scaleLabel("USD", scale);
}

interface Handlers {
  modeOf: (driver: DriverRowOut) => DriverMode;
  onMode: (driver: DriverRowOut, mode: DriverMode) => void;
  onReset: (driver: DriverRowOut) => void;
}

function columnDefs(
  grid: DriverGridOut,
  scale: Scale,
  isBase: boolean,
  { modeOf, onMode, onReset }: Handlers,
): ColDef<Row>[] {
  const label: ColDef<Row> = {
    colId: "label",
    headerName: "Driver",
    pinned: "left",
    width: Math.min(220, Math.round(window.innerWidth * 0.4)),
    cellRenderer: ({ data }: { data?: Row }) => {
      if (!data) return null;
      if (data.type === "group") return <span className="font-medium">{data.label}</span>;
      const { driver } = data;
      return (
        <span className="flex min-w-0 items-center gap-1 pl-3" title={driver.label}>
          <span className="truncate">{driver.label}</span>
          {driver.kind !== null && (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground ml-auto shrink-0 cursor-pointer p-0.5"
              aria-label={`Reset ${driver.label}`}
              title="Drop this scenario's own values"
              onClick={() => onReset(driver)}
            >
              <RotateCcw className="size-3.5" />
            </button>
          )}
        </span>
      );
    },
  };

  const unit: ColDef<Row> = {
    colId: "unit",
    headerName: "Unit",
    width: 110,
    cellClass: ["text-muted-foreground"],
    valueGetter: ({ data }) => (data?.type === "driver" ? unitHint(data.driver.unit, scale) : ""),
  };

  const mode: ColDef<Row> = {
    colId: "mode",
    headerName: "Mode",
    width: 104,
    cellRenderer: ({ data }: { data?: Row }) => {
      if (data?.type !== "driver") return null;
      const { driver } = data;
      return (
        <select
          aria-label={`Mode of ${driver.label}`}
          className="h-6 bg-transparent text-xs"
          value={modeOf(driver)}
          onChange={(e) => onMode(driver, e.target.value as DriverMode)}
        >
          {(Object.keys(MODE_LABELS) as DriverMode[]).map((value) => (
            <option key={value} value={value}>
              {MODE_LABELS[value]}
            </option>
          ))}
        </select>
      );
    },
  };

  const history = grid.history_years.map((year, index): ColDef<Row> => ({
    colId: historyColumn(year),
    headerName: historyLabel(year),
    width: 84,
    headerClass: [...NUM_HEADER, "text-muted-foreground"],
    cellClass: [...NUM, "text-muted-foreground"],
    valueGetter: ({ data }) =>
      data?.type === "driver"
        ? formatDriverValue(data.driver.history[index] ?? null, data.driver.unit, scale)
        : "",
  }));

  const forecast = grid.forecast_years.map((year, index): ColDef<Row> => {
    const column = forecastColumn(year);
    const cellOf = (data: Row) =>
      data.type === "driver"
        ? forecastCell(data.driver, index, modeOf(data.driver), scale, grid.history_years)
        : null;
    return {
      colId: column,
      headerName: forecastLabel(year),
      width: 96,
      headerClass: [...NUM_HEADER, "cell-forecast"],
      cellClass: [...NUM, "cell-forecast"],
      editable: ({ data }) => data?.type === "driver",
      // The editor starts from the cell's edit text; the renderer shows the formatted one.
      valueGetter: ({ data }) => {
        if (!data) return "";
        return data.edits[column] ?? cellOf(data)?.editText ?? "";
      },
      valueSetter: ({ data, newValue }) => {
        data.edits[column] = String(newValue ?? "");
        return true;
      },
      cellRenderer: ({ data }: CellClassParams<Row>) => {
        const cell = data ? cellOf(data) : null;
        if (!cell) return null;
        return (
          <span className={cell.classes.join(" ")} title={cell.title}>
            {cell.text}
          </span>
        );
      },
    };
  });

  return [label, unit, ...(isBase ? [] : [mode]), ...history, ...forecast];
}

interface DriverGridProps {
  ticker: string;
  scenario: ScenarioOut;
  scale: Scale;
}

/**
 * The scenario's drivers: the last actual years (read-only) beside the editable forecast years.
 * Each edit sends that driver's whole row; a non-base scenario edits a row as values or as
 * offsets on Base (vs Base), and switching a row's mode clears its own values after a confirm.
 */
export function DriverGrid({ ticker, scenario, scale }: DriverGridProps) {
  const { data: grid, isPending, error } = useQuery(driversQueryOptions(ticker, scenario.id));
  const { mutate: putRows } = usePutDrivers(ticker);
  const [message, setMessage] = useState<string | null>(null);
  // The mode picked for a row with no own values (a row with own values has its stored kind).
  const [picked, setPicked] = useState<Record<string, DriverMode>>({});
  const [switching, setSwitching] = useState<{ driver: DriverRowOut; mode: DriverMode } | null>(
    null,
  );

  const isBase = scenario.is_default;

  const send = useCallback(
    (row: DriverRowIn) => {
      setMessage(null);
      putRows(
        { id: scenario.id, rows: [row] },
        { onError: (e) => setMessage(companyErrorMessage(e, "Could not save the driver.")) },
      );
    },
    [putRows, scenario.id],
  );

  const handlers = useMemo<Handlers>(() => {
    const modeOf = (driver: DriverRowOut): DriverMode =>
      isBase ? "value" : (driver.kind ?? picked[driver.code] ?? "value");
    return {
      modeOf,
      onMode: (driver, mode) => {
        if (driver.kind !== null && driver.kind !== mode) return setSwitching({ driver, mode });
        setPicked((current) => ({ ...current, [driver.code]: mode }));
      },
      onReset: (driver) => {
        // After a reset the row has no stored kind: keep showing it in the mode it had.
        if (driver.kind !== null) {
          setPicked((current) => ({ ...current, [driver.code]: driver.kind as DriverMode }));
        }
        send(driverReset(driver));
      },
    };
  }, [isBase, picked, send]);

  const rows = useMemo<Row[]>(
    () => (grid ? toDriverRows(grid).map((row) => ({ ...row, edits: {} })) : []),
    [grid],
  );
  const columns = useMemo(
    () => (grid ? columnDefs(grid, scale, isBase, handlers) : []),
    [grid, scale, isBase, handlers],
  );

  function commit(event: CellValueChangedEvent<Row>) {
    const row = event.data;
    const column = event.column.getColId();
    const index = grid?.forecast_years.findIndex((year) => forecastColumn(year) === column) ?? -1;
    if (!grid || row.type !== "driver" || index < 0) return;
    const typed = String(event.newValue ?? "").trim();
    delete row.edits[column];
    const mode = handlers.modeOf(row.driver);
    const start = forecastCell(row.driver, index, mode, scale, grid.history_years).editText;
    if (typed === start.trim()) return;
    const value = typed === "" ? null : parseDriverText(typed, row.driver.unit, scale);
    if (typed !== "" && value === null) return setMessage("Enter a number");
    send(driverEdit(row.driver, mode, grid.forecast_years, grid.forecast_years[index]!, value));
  }

  function confirmSwitch() {
    if (!switching) return;
    const { driver, mode } = switching;
    setPicked((current) => ({ ...current, [driver.code]: mode }));
    send({ driver_code: driver.code, kind: mode, values: [] });
  }

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading drivers…</p>;
  if (!grid) {
    return (
      <p className="text-destructive p-4 text-sm">
        {companyErrorMessage(error, "Could not load the drivers.")}
      </p>
    );
  }

  return (
    <section aria-label="Drivers">
      {grid.warnings.length > 0 && (
        <ul className="text-muted-foreground space-y-0.5 px-4 py-2 text-xs">
          {grid.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {message && (
        <p role="alert" className="text-destructive px-4 py-2 text-sm">
          {message}
        </p>
      )}
      <DataGrid<Row>
        rowData={rows}
        columnDefs={columns}
        getRowId={(row) => row.id}
        onCellValueChanged={commit}
      />
      <AlertDialog open={switching !== null} onOpenChange={(open) => !open && setSwitching(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Switch {switching?.driver.label} to {switching && MODE_LABELS[switching.mode]}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Its own values in this scenario are cleared, and it follows{" "}
              {switching?.mode === "offset" ? "Base" : "Base or its default"} until you set new
              ones.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmSwitch}>Switch</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
