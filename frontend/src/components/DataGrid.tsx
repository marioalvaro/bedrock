import {
  colorSchemeDark,
  colorSchemeLight,
  themeQuartz,
  type ColDef,
  type CsvExportParams,
  type GridApi,
  type FirstDataRenderedEvent,
  type GridReadyEvent,
  type CellClickedEvent,
  type CellValueChangedEvent,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useImperativeHandle, useMemo, useRef, type Ref } from "react";

import { useTheme } from "@/lib/theme";

export interface DataGridHandle {
  // The grid's own CSV export of exactly the visible rows and columns, as text.
  getCsv: (params: CsvExportParams) => string;
}

interface DataGridProps<T> {
  rowData: T[];
  columnDefs: ColDef<T>[];
  getRowId: (row: T) => string;
  onCellClicked?: (event: CellClickedEvent<T>) => void;
  // Fires when an editable column's edit is committed with a changed value.
  onCellValueChanged?: (event: CellValueChangedEvent<T>) => void;
  ref?: Ref<DataGridHandle>;
}

// The colour scheme part goes first: params set after it win over its defaults.
const gridTheme = (scheme: "light" | "dark") =>
  themeQuartz.withPart(scheme === "dark" ? colorSchemeDark : colorSchemeLight).withParams({
    backgroundColor: "var(--background)",
    foregroundColor: "var(--foreground)",
    borderColor: "var(--border)",
    headerBackgroundColor: "var(--background)",
    headerTextColor: "var(--muted-foreground)",
    oddRowBackgroundColor: "var(--background)",
    rowHoverColor: "var(--muted)",
    wrapperBorder: false,
    wrapperBorderRadius: 0,
    fontSize: 13,
    headerFontSize: 12,
    rowHeight: 28,
    headerHeight: 30,
    spacing: 4,
  });

// AG Grid Community wrapper: pinned first column, every column rendered (statements are
// small, and it lets jsdom see every cell), theme following the app's, CSV handle.
export function DataGrid<T>({
  rowData,
  columnDefs,
  getRowId,
  onCellClicked,
  onCellValueChanged,
  ref,
}: DataGridProps<T>) {
  const theme = useTheme();
  const api = useRef<GridApi<T> | null>(null);

  const agTheme = useMemo(() => gridTheme(theme), [theme]);

  useImperativeHandle(
    ref,
    () => ({ getCsv: (params) => api.current?.getDataAsCsv(params) ?? "" }),
    [],
  );

  // Statements run oldest to newest: open on the most recent periods, like a price chart.
  const onFirstDataRendered = useCallback((event: FirstDataRenderedEvent<T>) => {
    const last = event.api.getAllDisplayedColumns().at(-1);
    if (last) event.api.ensureColumnVisible(last, "end");
  }, []);

  const onGridReady = useCallback((event: GridReadyEvent<T>) => {
    api.current = event.api;
  }, []);

  return (
    <AgGridReact<T>
      theme={agTheme}
      rowData={rowData}
      columnDefs={columnDefs}
      getRowId={(params) => getRowId(params.data)}
      domLayout="autoHeight"
      suppressColumnVirtualisation
      suppressMovableColumns
      suppressCellFocus
      defaultColDef={{ sortable: false, resizable: false, suppressHeaderMenuButton: true }}
      onGridReady={onGridReady}
      onFirstDataRendered={onFirstDataRendered}
      stopEditingWhenCellsLoseFocus
      onCellClicked={onCellClicked}
      onCellValueChanged={onCellValueChanged}
    />
  );
}
