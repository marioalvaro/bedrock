import type { SegmentImportIn } from "@/api/generated/types.gen";

export type Dimension = SegmentImportIn["dimension"];

// What the import accepts, as shown in the sheet. The parser is `parse_import` in
// backend/src/bedrock/statements/segments.py (grammar: erd/data.md "Segments and KPIs").
// Edit both together: the template fixtures under backend/tests/fixtures/segments are parsed by
// the backend test and compared with `templateCsv` here.

export const FORMAT_RULES: string[] = [
  "Header: name, metric, unit, then one column per period. Rows are one series each.",
  "Period headers read FY2024 or Q1 FY2024 (a four-digit year). The grid shows FY24, but the file always uses FY2024.",
  "Business and geographic segments: metric is revenue or operating_income, and the unit is USD.",
  "KPIs: metric is a code in lowercase letters, digits and underscores (starting with a letter, up to 40 characters); the unit is USD, pct, count or USD_per_unit.",
  "The scale multiplies USD and USD_per_unit values only; pct and count are stored as typed.",
  "A percent is typed as 5.2 or 5.2%. A blank cell is skipped and keeps the stored value.",
  "Numbers may have thousands separators (1,234). Parentheses or a leading minus make a negative: (5.2) or -5.2.",
  "Separate cells with commas or tabs (a tab in the header line selects tabs). Quote a cell that contains a comma.",
  "The import is all or nothing: any error cancels it and is listed by row and column.",
];

const TEMPLATE: Record<Dimension, string[][]> = {
  business: [
    ["name", "metric", "unit", "FY2023", "FY2024"],
    ["iPhone", "revenue", "USD", "200,583", "201,183"],
    ["Services", "revenue", "USD", "85,200", "96,169"],
    ["Services", "operating_income", "USD", "", "71,050"],
  ],
  geo: [
    ["name", "metric", "unit", "FY2023", "FY2024"],
    ["Americas", "revenue", "USD", "162,560", "167,045"],
    ["Europe", "revenue", "USD", "94,294", "101,328"],
    ["Greater China", "revenue", "USD", "72,559", "66,952"],
  ],
  kpi: [
    ["name", "metric", "unit", "FY2023", "FY2024"],
    ["Same-store sales (U.S.)", "same_store_sales_us", "pct", "4.1%", "5.2%"],
    ["Stores", "stores", "count", "1,000", "1,100"],
    ["Average ticket", "average_ticket", "USD_per_unit", "52.30", "54.10"],
  ],
};

/** The example table of a dimension: the header row, then the data rows. */
export function templateRows(dimension: Dimension): string[][] {
  return TEMPLATE[dimension];
}

function csvCell(cell: string): string {
  return /[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
}

/** The template as the CSV the import accepts. */
export function templateCsv(dimension: Dimension): string {
  return TEMPLATE[dimension].map((row) => row.map(csvCell).join(",")).join("\n") + "\n";
}

export function templateFileName(dimension: Dimension): string {
  return `segments_template_${dimension}.csv`;
}
