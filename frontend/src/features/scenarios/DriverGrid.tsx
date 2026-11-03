import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CellClassParams, CellValueChangedEvent, ColDef } from "ag-grid-community";
import { RotateCcw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { ApiError } from "@/api/errors";
import type {
  DriverGridOut,
  DriverRowIn,
  DriverRowOut,
  GridPeriodOut,
  ScenarioOut,
} from "@/api/generated/types.gen";
import {
  driversQueryOptions,
  usePutDrivers,
  type ForecastFreq,
  type ScenarioCase,
} from "@/api/scenarios";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { scaleLabel } from "@/lib/format";
import type { Scale } from "@/lib/scale";

import {
  driverClear,
  driverEdit,
  driverReset,
  forecastCell,
  formatDriverValue,
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

// Column ids: `h:2024` / `f:2026` for years, `h:2025Q3` / `f:2026Q1` for quarters.
const periodSuffix = ({ fiscal_year, fiscal_period }: GridPeriodOut) =>
  fiscal_period === "FY" ? `${fiscal_year}` : `${fiscal_year}${fiscal_period}`;
const historyColumn = (period: GridPeriodOut) => `h:${periodSuffix(period)}`;
const forecastColumn = (period: GridPeriodOut) => `f:${periodSuffix(period)}`;

// The API's 422 detail for a company with no quarters (ERD "Quarterly drivers" → API).
const NO_QUARTERS = "No quarterly history";

const FREQS: { value: ForecastFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
];

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
  editable: boolean,
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
          {driver.own.some((value) => value !== null) && (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground ml-auto shrink-0 cursor-pointer p-0.5 disabled:cursor-default disabled:opacity-50"
              aria-label={`Reset ${driver.label}`}
              disabled={!editable}
              title={`Drop this case's own ${grid.freq === "quarterly" ? "quarter " : ""}values`}
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
          disabled={!editable}
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

  const history = grid.history_periods.map((period, index): ColDef<Row> => ({
    colId: historyColumn(period),
    headerName: period.label,
    width: 84,
    headerClass: [...NUM_HEADER, "text-muted-foreground"],
    cellClass: [...NUM, "text-muted-foreground"],
    valueGetter: ({ data }) =>
      data?.type === "driver"
        ? formatDriverValue(data.driver.history[index] ?? null, data.driver.unit, scale)
        : "",
  }));

  const forecast = grid.forecast_periods.map((period, index): ColDef<Row> => {
    const column = forecastColumn(period);
    const cellOf = (data: Row) =>
      data.type === "driver"
        ? forecastCell(data.driver, index, modeOf(data.driver), scale, grid)
        : null;
    return {
      colId: column,
      headerName: period.label,
      width: 96,
      headerClass: [...NUM_HEADER, "cell-forecast"],
      cellClass: [...NUM, "cell-forecast"],
      editable: ({ data }) => editable && data?.type === "driver",
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
  scenarioCase: ScenarioCase; // the view keys this component by scenario and case
  freq: ForecastFreq; // kept by the view, so a case switch stays on Quarterly
  onFreq: (freq: ForecastFreq) => void;
  scale: Scale;
}

/**
 * One case's drivers, annual or quarterly: the last actual periods (read-only) beside the editable
 * forecast periods. Each edit sends that driver's whole row of the grid's frequency; Bull and Bear
 * edit a row as values or as offsets on their scenario's Base (vs Base), and switching a row's
 * mode clears its own values, annual and quarterly, after a confirm.
 */
export function DriverGrid({
  ticker,
  scenario,
  scenarioCase,
  freq,
  onFreq,
  scale,
}: DriverGridProps) {
  const queryClient = useQueryClient();
  const {
    data: grid,
    isPending,
    isPlaceholderData,
    error,
  } = useQuery({
    ...driversQueryOptions(ticker, scenario.id, scenarioCase, freq),
    placeholderData: keepPreviousData, // the other frequency's grid stays up while this one loads (G32)
  });
  const { mutate: putRows } = usePutDrivers(ticker);
  const [message, setMessage] = useState<string | null>(null);
  // The mode picked for a row with no own values (a row with own values has its stored kind).
  const [picked, setPicked] = useState<Record<string, DriverMode>>({});
  const [switching, setSwitching] = useState<{ driver: DriverRowOut; mode: DriverMode } | null>(
    null,
  );

  const isBase = scenarioCase === "base";

  const send = useCallback(
    (rows: DriverRowIn[]) => {
      setMessage(null);
      putRows(
        { id: scenario.id, case: scenarioCase, rows },
        { onError: (e) => setMessage(companyErrorMessage(e, "Could not save the driver.")) },
      );
    },
    [putRows, scenario.id, scenarioCase],
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
        if (!grid) return;
        // After a reset the row may have no stored kind: keep showing it in the mode it had.
        if (driver.kind !== null) {
          setPicked((current) => ({ ...current, [driver.code]: driver.kind as DriverMode }));
        }
        send([driverReset(grid, driver)]);
      },
    };
  }, [isBase, picked, send, grid]);

  const rows = useMemo<Row[]>(
    () => (grid ? toDriverRows(grid).map((row) => ({ ...row, edits: {} })) : []),
    [grid],
  );
  const columns = useMemo(
    () => (grid ? columnDefs(grid, scale, isBase, !isPlaceholderData, handlers) : []),
    [grid, scale, isBase, isPlaceholderData, handlers],
  );

  function commit(event: CellValueChangedEvent<Row>) {
    const row = event.data;
    const column = event.column.getColId();
    const index = grid?.forecast_periods.findIndex((p) => forecastColumn(p) === column) ?? -1;
    if (!grid || row.type !== "driver" || index < 0) return;
    const typed = String(event.newValue ?? "").trim();
    delete row.edits[column];
    const mode = handlers.modeOf(row.driver);
    const start = forecastCell(row.driver, index, mode, scale, grid).editText;
    if (typed === start.trim()) return;
    const value = typed === "" ? null : parseDriverText(typed, row.driver.unit, scale);
    if (typed !== "" && value === null) return setMessage("Enter a number");
    send([driverEdit(grid, row.driver, mode, index, value)]);
  }

  // One kind per driver across frequencies: the switch clears the annual rows and, when the
  // company has quarters and the driver has them, the quarterly rows too (a PUT row replaces only
  // its own frequency).
  async function confirmSwitch() {
    if (!switching) return;
    const { driver, mode } = switching;
    setPicked((current) => ({ ...current, [driver.code]: mode }));
    const rows = [driverClear(driver.code, mode, "annual")];
    try {
      const quarterly = await queryClient.ensureQueryData(
        driversQueryOptions(ticker, scenario.id, scenarioCase, "quarterly"),
      );
      if (quarterly.rows.some((row) => row.code === driver.code)) {
        rows.push(driverClear(driver.code, mode, "quarterly"));
      }
    } catch (e) {
      // No quarterly history means no quarterly rows to clear; any other failure stops the switch.
      const noQuarters = e instanceof ApiError && e.detail === NO_QUARTERS;
      if (!noQuarters) return setMessage(companyErrorMessage(e, "Could not save the driver."));
    }
    send(rows);
  }

  // Drivers the annual grid has and this quarterly one does not: set per year only. The annual
  // grid is the view's first load, so this reads the cache (fetching only if it is missing).
  const { data: annualGrid } = useQuery({
    ...driversQueryOptions(ticker, scenario.id, scenarioCase, "annual"),
    enabled: freq === "quarterly",
    staleTime: Infinity,
  });
  const annualOnly =
    grid?.freq === "quarterly"
      ? (annualGrid?.rows ?? []).filter(
          (row) => !grid.rows.some((quarterly) => quarterly.code === row.code),
        )
      : [];

  return (
    <section aria-label="Drivers">
      <div className="border-border flex items-center gap-2 border-b px-4 py-2">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Driver frequency"
          value={freq}
          onValueChange={(value) => value && onFreq(value as ForecastFreq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {isPlaceholderData && <span className="text-muted-foreground text-xs">Updating…</span>}
      </div>
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading drivers…</p>}
      {!grid && !isPending && (
        <p className="text-destructive p-4 text-sm">
          {companyErrorMessage(error, "Could not load the drivers.")}
        </p>
      )}
      {grid && (
        <>
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
          {annualOnly.length > 0 && (
            <p className="text-muted-foreground px-4 py-2 text-xs">
              Set per year only: {annualOnly.map((row) => row.label).join(", ")}.
            </p>
          )}
        </>
      )}
      <AlertDialog open={switching !== null} onOpenChange={(open) => !open && setSwitching(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Switch {switching?.driver.label} to {switching && MODE_LABELS[switching.mode]}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Its own values in this case, annual and quarterly, are cleared, and it follows{" "}
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
