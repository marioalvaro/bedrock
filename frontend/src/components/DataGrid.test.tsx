import { render } from "@testing-library/react";
import type { AgGridReactProps } from "ag-grid-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DataGrid } from "./DataGrid";

// The grid's own rendering is covered by the view tests. What matters here is what the wrapper
// hands to AG Grid: a prop whose identity changes on every render makes AG Grid rebuild its
// columns or rows, which is what made the numbers jump.
const seen: AgGridReactProps[] = [];

vi.mock("ag-grid-react", () => ({
  AgGridReact: (props: AgGridReactProps) => {
    seen.push(props);
    return null;
  },
}));

interface Row {
  id: string;
}

const original = window.matchMedia;
const columns = [{ colId: "a" }];

function setReducedMotion(reduced: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)" && reduced,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
}

const latest = () => seen.at(-1) as AgGridReactProps;

describe("DataGrid", () => {
  beforeEach(() => {
    seen.length = 0;
  });

  afterEach(() => {
    window.matchMedia = original;
  });

  it("animates inserted and removed rows", () => {
    setReducedMotion(false);
    render(<DataGrid<Row> rowData={[]} columnDefs={columns} getRowId={(row) => row.id} />);

    expect(latest().animateRows).toBe(true);
  });

  it("shows rows instantly when the OS asks to reduce motion", () => {
    setReducedMotion(true);
    render(<DataGrid<Row> rowData={[]} columnDefs={columns} getRowId={(row) => row.id} />);

    expect(latest().animateRows).toBe(false);
  });

  it("keeps the same defaultColDef and getRowId across renders", () => {
    setReducedMotion(false);
    const { rerender } = render(
      <DataGrid<Row> rowData={[]} columnDefs={columns} getRowId={(row) => row.id} />,
    );
    const first = latest();

    // A new rowData and a new getRowId closure, as a parent re-render makes.
    rerender(
      <DataGrid<Row> rowData={[{ id: "x" }]} columnDefs={columns} getRowId={(row) => row.id} />,
    );

    expect(latest().defaultColDef).toBe(first.defaultColDef);
    expect(latest().getRowId).toBe(first.getRowId);
  });
});
