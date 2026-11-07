import type { CellClassParams, ColDef, ColGroupDef } from "ag-grid-community";
import { ChartLine, RotateCcw } from "lucide-react";

import type { DriverGridOut, DriverRowOut, GridPeriodOut } from "@/api/generated/types.gen";
import { scaleLabel } from "@/lib/format";
import type { Scale } from "@/lib/scale";

import {
  canReset,
  engineOptions,
  forecastCell,
  formatDriverValue,
  type DriverGridRow,
  type DriverMode,
  type DriverUnit,
  type EngineCode,
} from "./driverCells";
import { YearGroupHeader, YearHeader } from "./YearModeSwitch";

export const MODE_LABELS: Record<DriverMode, string> = { value: "Value", offset: "vs Base" };
const NUM = ["num", "ag-right-aligned-cell"];
const NUM_HEADER = ["num", "ag-right-aligned-header"];

// A grid row with the text just typed into a cell, held until the commit handler reads it (G29).
export type Row = DriverGridRow & { edits: Record<string, string> };

// Column ids: `h:2024` / `f:2026` for years, `h:2025Q3` / `f:2026Q1` for quarters.
const periodSuffix = ({ fiscal_year, fiscal_period }: GridPeriodOut) =>
  fiscal_period === "FY" ? `${fiscal_year}` : `${fiscal_year}${fiscal_period}`;
const historyColumn = (period: GridPeriodOut) => `h:${periodSuffix(period)}`;
export const forecastColumn = (period: GridPeriodOut) => `f:${periodSuffix(period)}`;

// Every forecast column has this width, so a year with a switch lines up with the others.
const FORECAST_WIDTH = 144;

function unitHint(unit: DriverUnit, scale: Scale): string {
  if (unit === "pct") return "%";
  if (unit === "days") return "days";
  return scaleLabel("USD", scale);
}

export interface Handlers {
  modeOf: (driver: DriverRowOut) => DriverMode;
  onMode: (driver: DriverRowOut, mode: DriverMode) => void;
  onReset: (driver: DriverRowOut) => void;
  onEngine: (driver: DriverRowOut, engine: EngineCode) => void;
  onInspect: (driver: DriverRowOut) => void; // opens the driver's Engines sheet
  engineSaving: boolean; // an engine PUT is running
}

// A driver with a numeric default (`engine_used` set) can take an engine; one held flat, following
// another driver or with no history cannot.
const hasEngine = (driver: DriverRowOut) => driver.engine_used !== null;

/**
 * The grid's columns: label, unit, Engine (annual), Mode (Bull and Bear), history, then the
 * forecast periods.
 */
export function columnDefs(
  grid: DriverGridOut,
  scale: Scale,
  isBase: boolean,
  editable: boolean,
  { modeOf, onMode, onReset, onEngine, onInspect, engineSaving }: Handlers,
): (ColDef<Row> | ColGroupDef<Row>)[] {
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
          {grid.freq === "annual" && hasEngine(driver) && (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground ml-auto shrink-0 cursor-pointer p-0.5"
              aria-label={`${driver.label} engines`}
              title="Compare the engines' forecasts"
              onClick={() => onInspect(driver)}
            >
              <ChartLine className="size-3.5" />
            </button>
          )}
          {canReset(grid, driver) && (
            <button
              type="button"
              className={`text-muted-foreground hover:text-foreground shrink-0 cursor-pointer p-0.5 disabled:cursor-default disabled:opacity-50 ${grid.freq === "annual" && hasEngine(driver) ? "" : "ml-auto"}`}
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

  const engine: ColDef<Row> = {
    colId: "engine",
    headerName: "Engine",
    width: 128,
    cellRenderer: ({ data }: { data?: Row }) => {
      if (data?.type !== "driver") return null;
      const { driver } = data;
      if (!hasEngine(driver)) return <span className="text-muted-foreground">—</span>;
      return (
        <select
          aria-label={`${driver.label} engine`}
          title="Applies to Base, Bull and Bear"
          disabled={!editable || engineSaving}
          className="h-6 max-w-full bg-transparent text-xs"
          value={driver.engine}
          onChange={(e) => onEngine(driver, e.target.value as EngineCode)}
        >
          {engineOptions(driver).map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      );
    },
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

  const modeOfYear = (year: number) => grid.year_modes.find((m) => m.fiscal_year === year);
  const forecast = grid.forecast_periods.map((period, index): ColDef<Row> => {
    const column = forecastColumn(period);
    const cellOf = (data: Row) =>
      data.type === "driver"
        ? forecastCell(data.driver, index, modeOf(data.driver), scale, grid)
        : null;
    // A year of the span carries its switch: in its own header (annual), or over its quarters.
    const switchable = grid.freq === "annual" && modeOfYear(period.fiscal_year)?.in_span === true;
    return {
      colId: column,
      headerName: period.label,
      width: FORECAST_WIDTH,
      headerClass: [...NUM_HEADER, "cell-forecast"],
      cellClass: [...NUM, "cell-forecast"],
      ...(switchable && {
        headerComponent: YearHeader,
        headerComponentParams: { year: period.fiscal_year },
      }),
      editable: ({ data }) => editable && data?.type === "driver" && !cellOf(data)?.locked,
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
          <>
            <span className={cell.classes.join(" ")} title={cell.title}>
              {cell.text}
            </span>
            {cell.note && (
              <span className="text-muted-foreground ml-1 text-[10px]">{cell.note}</span>
            )}
          </>
        );
      },
    };
  });

  // The quarterly grid puts each year's quarters under a header group holding the year's switch.
  const byYear = (): ColGroupDef<Row>[] => {
    const groups: ColGroupDef<Row>[] = [];
    grid.forecast_periods.forEach(({ fiscal_year: year }, index) => {
      const column = forecast[index]!;
      const last = groups.at(-1);
      if (last?.groupId === `y:${year}`) return void last.children.push(column);
      groups.push({
        groupId: `y:${year}`,
        headerName: modeOfYear(year)?.label ?? `FY${year}`,
        headerClass: "cell-forecast",
        headerGroupComponent: YearGroupHeader,
        headerGroupComponentParams: { year },
        children: [column],
      });
    });
    return groups;
  };

  return [
    label,
    unit,
    ...(grid.freq === "annual" ? [engine] : []),
    ...(isBase ? [] : [mode]),
    ...history,
    ...(grid.freq === "quarterly" ? byYear() : forecast),
  ];
}
