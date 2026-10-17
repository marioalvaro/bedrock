import { useQuery } from "@tanstack/react-query";
import type { ColDef } from "ag-grid-community";
import { useMemo, useState } from "react";

import { flagsQueryOptions, type AnalysisFreq } from "@/api/analysis";
import type { FlagsOut } from "@/api/generated/types.gen";
import { DataGrid } from "@/components/DataGrid";
import { UnitToggle } from "@/components/UnitToggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { formatRatio, formatThreshold } from "@/lib/format";

import { OffBalanceItems } from "./OffBalanceItems";

type Rule = FlagsOut["rules"][number];

const FREQS: { value: AnalysisFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "ttm", label: "TTM" },
];

const EMPTY = "No quality flags for this company.";

function thresholdText(rule: Rule): string {
  const sign = rule.direction === "above" ? ">" : "<";
  const levels = [
    ["warn", rule.warn],
    ["alert", rule.alert],
  ] as const;
  const parts = levels.flatMap(([name, level]) =>
    level === null ? [] : [`${name} ${sign} ${formatThreshold(level, rule.unit)}`],
  );
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function columnDefs(payload: FlagsOut): ColDef<Rule>[] {
  const periodColumns = payload.periods.map((period, index): ColDef<Rule> => ({
    colId: period.key,
    headerName: period.label,
    width: 100,
    headerClass: ["num", "ag-right-aligned-header"],
    valueGetter: ({ data }) => data?.values[index] ?? null,
    valueFormatter: ({ data }) => (data ? formatRatio(data.values[index] ?? null, data.unit) : ""),
    cellClass: ({ data }) => {
      const severity = data?.severity[index];
      return [
        "num",
        "ag-right-aligned-cell",
        ...(severity === "warn" ? ["flag-warn"] : severity === "alert" ? ["flag-alert"] : []),
      ];
    },
  }));

  return [
    {
      colId: "label",
      headerName: "Rule",
      pinned: "left",
      width: Math.min(240, Math.round(window.innerWidth * 0.4)),
      cellRenderer: ({ data }: { data?: Rule }) =>
        data ? (
          <span className="truncate" title={data.code}>
            {data.label}
          </span>
        ) : null,
    },
    {
      colId: "rule",
      headerName: "Definition",
      width: 220,
      cellRenderer: ({ data }: { data?: Rule }) =>
        data ? (
          <span className="text-muted-foreground truncate" title={data.rule}>
            {data.rule}
          </span>
        ) : null,
    },
    {
      colId: "thresholds",
      headerName: "Thresholds",
      width: 170,
      valueGetter: ({ data }) => (data ? thresholdText(data) : ""),
    },
    ...periodColumns,
  ];
}

interface QualityViewProps {
  ticker: string;
}

/**
 * The Quality tab: toolbar Annual | TTM; a DataGrid of the flag rules (label, rule, thresholds,
 * each period's value colored by severity); then `OffBalanceItems`, which loads its own list and
 * is always rendered, whatever the flags query does.
 */
export function QualityView({ ticker }: QualityViewProps) {
  const [freq, setFreq] = useState<AnalysisFreq>("annual");
  const { data, isPending, isError } = useQuery(flagsQueryOptions(ticker, freq));
  const columns = useMemo(() => (data ? columnDefs(data) : []), [data]);
  const empty = data !== undefined && (data.rules.length === 0 || data.periods.length === 0);

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
          onValueChange={(value) => value && setFreq(value as AnalysisFreq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <UnitToggle />
      </div>
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && <p className="text-destructive p-4 text-sm">Could not load the quality flags.</p>}
      {empty && <p className="text-muted-foreground p-4 text-sm">{EMPTY}</p>}
      {data && !empty && (
        <DataGrid<Rule> rowData={data.rules} columnDefs={columns} getRowId={(r) => r.code} />
      )}
      <OffBalanceItems ticker={ticker} />
    </div>
  );
}
