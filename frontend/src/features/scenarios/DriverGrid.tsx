import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { CellValueChangedEvent } from "ag-grid-community";
import { useCallback, useMemo, useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { usePutEngines } from "@/api/engines";
import type {
  DriverRowIn,
  DriverRowOut,
  ScenarioOut,
  YearModeOut,
} from "@/api/generated/types.gen";
import {
  driversQueryOptions,
  usePutDrivers,
  useSetYearMode,
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
import type { Scale } from "@/lib/scale";

import {
  driverClear,
  driverEdit,
  driverReset,
  forecastCell,
  parseDriverText,
  periodName,
  toDriverRows,
  type DriverMode,
  type EngineCode,
} from "./driverCells";
import { DriverEnginesSheet } from "./DriverEnginesSheet";
import { columnDefs, forecastColumn, MODE_LABELS, type Handlers, type Row } from "./driverColumns";
import { YearModesContext, type YearModes, type YearModeValue } from "./yearModes";

const FREQS: { value: ForecastFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
];

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
  const { mutate: putYearMode, isPending: modeSaving } = useSetYearMode(ticker, scenario.id);
  const { mutate: putEngines, isPending: engineSaving } = usePutEngines(ticker, scenario.id);
  // The driver whose Engines sheet is open.
  const [inspecting, setInspecting] = useState<DriverRowOut | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // The mode picked for a row with no own values (a row with own values has its stored kind).
  const [picked, setPicked] = useState<Record<string, DriverMode>>({});
  const [switching, setSwitching] = useState<{ driver: DriverRowOut; mode: DriverMode } | null>(
    null,
  );
  // The year being returned to annual, awaiting the confirm.
  const [returning, setReturning] = useState<YearModeOut | null>(null);

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

  const switchYear = useCallback(
    (year: number, mode: YearModeValue) => {
      setMessage(null);
      putYearMode(
        { fiscalYear: year, mode },
        { onError: (e) => setMessage(companyErrorMessage(e, "Could not switch the year.")) },
      );
    },
    [putYearMode],
  );
  const yearModes = useMemo<YearModes>(
    () => ({
      modes: new Map((grid?.year_modes ?? []).map((m) => [m.fiscal_year, m])),
      disabled: modeSaving || isPlaceholderData,
      // Going back to annual deletes the quarter values: ask first. By quarter changes no number.
      onMode: (year, mode) => {
        const entry = grid?.year_modes.find((m) => m.fiscal_year === year);
        if (mode === "annual" && entry) setReturning(entry);
        else switchYear(year, mode);
      },
    }),
    [grid, modeSaving, isPlaceholderData, switchYear],
  );
  const hasSwitches = grid?.year_modes.some((m) => m.in_span) ?? false;

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
      onEngine: (driver, engine: EngineCode) => {
        setMessage(null);
        putEngines([{ driver_code: driver.code, engine }], {
          onError: (e) => setMessage(companyErrorMessage(e, "Could not change the engine.")),
        });
      },
      onInspect: setInspecting,
      engineSaving,
    };
  }, [isBase, picked, send, grid, putEngines, engineSaving]);

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
  // company has quarters and the driver can be set per quarter, the quarterly rows too (a PUT row
  // replaces only its own frequency).
  function confirmSwitch() {
    if (!switching || !grid) return;
    const { driver, mode } = switching;
    setPicked((current) => ({ ...current, [driver.code]: mode }));
    const rows = [driverClear(driver.code, mode, "annual")];
    if (grid.has_quarters && driver.quarterly)
      rows.push(driverClear(driver.code, mode, "quarterly"));
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
        {hasSwitches && (
          <p className="text-muted-foreground ml-auto text-xs">
            Each year is set either as one annual value or quarter by quarter.
          </p>
        )}
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
          <YearModesContext.Provider value={yearModes}>
            <DataGrid<Row>
              rowData={rows}
              columnDefs={columns}
              getRowId={(row) => row.id}
              onCellValueChanged={commit}
            />
          </YearModesContext.Provider>
          {annualOnly.length > 0 && (
            <p className="text-muted-foreground px-4 py-2 text-xs">
              Set per year only: {annualOnly.map((row) => row.label).join(", ")}.
            </p>
          )}
        </>
      )}
      {inspecting && (
        <DriverEnginesSheet
          key={`${scenario.id}:${scenarioCase}:${inspecting.code}`}
          ticker={ticker}
          scenarioId={scenario.id}
          scenarioCase={scenarioCase}
          driver={inspecting}
          scale={scale}
          onClose={() => setInspecting(null)}
        />
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
      <AlertDialog open={returning !== null} onOpenChange={(open) => !open && setReturning(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Return {returning && periodName(returning.fiscal_year, "FY")} to annual?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {returning && periodName(returning.fiscal_year, "FY")} returns to its annual values.
              The quarter values of Base, Bull and Bear are deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => returning && switchYear(returning.fiscal_year, "annual")}
            >
              Return to annual
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
