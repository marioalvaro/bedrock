import { useQuery } from "@tanstack/react-query";
import type { ColDef } from "ag-grid-community";
import { useMemo, useState } from "react";

import { asReportedQueryOptions, type StatementType } from "@/api/statements";
import type { AsReportedPeriodOut } from "@/api/generated/types.gen";
import { DataGrid } from "@/components/DataGrid";
import { formatValue, scaleLabel } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

import {
  filingOptionText,
  NOT_FOOTING_TITLE,
  periodHeader,
  periodKeys,
  toAsReportedRows,
  type AsReportedRow,
} from "./asReported";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

function columnDefs(periods: AsReportedPeriodOut[], scale: Scale): ColDef<AsReportedRow>[] {
  const label: ColDef<AsReportedRow> = {
    colId: "label",
    headerName: scaleLabel("USD", scale),
    pinned: "left",
    width: Math.min(280, Math.round(window.innerWidth * 0.45)),
    cellRenderer: ({ data }: { data?: AsReportedRow }) =>
      data ? (
        <span
          className={`block truncate ${data.isTotal ? "font-medium" : ""}`}
          style={{ paddingLeft: `${data.depth * 12}px` }}
          title={data.label}
        >
          {data.label}
        </span>
      ) : null,
  };
  const keys = periodKeys(periods);
  const values = periods.map((period, index): ColDef<AsReportedRow> => ({
    colId: keys[index] as string,
    headerName: periodHeader(period),
    width: period.start === null ? 100 : 180,
    headerClass: ["num", "ag-right-aligned-header"],
    cellClass: ["num", "ag-right-aligned-cell"],
    cellRenderer: ({ data }: { data?: AsReportedRow }) => {
      if (!data) return null;
      const key = keys[index] as string;
      const text = formatValue(data.values[key] ?? null, data.unit, scale);
      if (!data.notFooting[key]) return text;
      return (
        <span title={NOT_FOOTING_TITLE}>
          <span className="not-foot-mark" aria-hidden />
          {text}
        </span>
      );
    },
  }));
  const bedrock: ColDef<AsReportedRow> = {
    colId: "bedrock",
    headerName: "Bedrock row",
    width: 220,
    cellRenderer: ({ data }: { data?: AsReportedRow }) =>
      data ? (
        <span
          className={`block truncate ${data.bedrock.muted ? "text-muted-foreground" : ""}`}
          title={data.bedrock.text}
        >
          {data.bedrock.text}
        </span>
      ) : null,
  };
  return [label, ...values, bedrock];
}

interface AsReportedViewProps {
  ticker: string;
  type: StatementType;
}

/** One filing's statement in the company's own lines, labels and order (FR-STMT-07). Read only:
 * no cell detail, notes or export. */
export function AsReportedView({ ticker, type }: AsReportedViewProps) {
  const scale = useScale();
  const [accession, setAccession] = useState<string | null>(null);
  const { data, isPending, isError } = useQuery(asReportedQueryOptions(ticker, type, accession));
  const rows = useMemo(() => (data ? toAsReportedRows(data) : []), [data]);
  const columns = useMemo(() => (data ? columnDefs(data.periods, scale) : []), [data, scale]);

  return (
    <div>
      <p className="text-muted-foreground px-4 py-1 text-xs">
        Read only. The filing as filed; Bedrock&apos;s own statements are under Bedrock rows.
      </p>
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && <p className="text-destructive p-4 text-sm">Could not load the filing.</p>}
      {data && data.filing === null && (
        <p className="text-muted-foreground p-4 text-sm">
          No filing has been read for this statement yet.
        </p>
      )}
      {data && data.filing !== null && (
        <>
          <div className="px-4 py-1">
            <select
              aria-label="Filing"
              className={SELECT}
              value={data.filing.accession_no}
              onChange={(event) => setAccession(event.target.value)}
            >
              {data.filings.map((filing) => (
                <option key={filing.accession_no} value={filing.accession_no}>
                  {filingOptionText(filing)}
                </option>
              ))}
            </select>
          </div>
          <DataGrid<AsReportedRow> rowData={rows} columnDefs={columns} getRowId={(row) => row.id} />
        </>
      )}
    </div>
  );
}
