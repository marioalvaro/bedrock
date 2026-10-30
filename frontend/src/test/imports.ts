import type {
  CellChangeOut,
  ImportPreviewOut,
  StatementImportOut,
} from "@/api/generated/types.gen";

// Shapes of POST …/imports (dry run and real run) and GET …/imports.

export function cellChange(overrides: Partial<CellChangeOut> = {}): CellChangeOut {
  return {
    statement: "IS",
    code: "interest_expense",
    label: "Interest expense",
    period_key: "FY2008",
    value: "1500000000",
    previous: null,
    unit: "USD",
    ...overrides,
  };
}

export function preview(overrides: Partial<ImportPreviewOut> = {}): ImportPreviewOut {
  return {
    dry_run: true,
    format: "xlsx",
    scale: "millions",
    import_id: null,
    fills: [cellChange()],
    ignored: [],
    unchanged: 0,
    warnings: [],
    lines: [],
    built: [],
    ...overrides,
  };
}

export function statementImport(overrides: Partial<StatementImportOut> = {}): StatementImportOut {
  return {
    id: 3,
    filename: "AAPL-import-template.xlsx",
    format: "xlsx",
    scale: "millions",
    imported_at: "2026-10-26T10:30:00",
    cells: 12,
    ...overrides,
  };
}
