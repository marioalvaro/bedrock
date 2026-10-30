import { useQuery } from "@tanstack/react-query";
import type { CellClickedEvent, ColDef, ICellRendererParams } from "ag-grid-community";
import { useMemo, useState } from "react";

import { flagsQueryOptions, type AnalysisFreq } from "@/api/analysis";
import type { FlagsOut, PeriodOut } from "@/api/generated/types.gen";
import { DataGrid } from "@/components/DataGrid";
import { UnitToggle } from "@/components/UnitToggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { NoteMarker } from "@/features/notes/NoteMarker";
import { SubjectNotesSheet } from "@/features/notes/SubjectNotesSheet";
import {
  cellNotes,
  cellTarget,
  subjectNotes,
  type NoteIndex,
  type SubjectTarget,
} from "@/features/notes/subjects";
import { useNoteIndex } from "@/features/notes/useNoteIndex";
import { formatRatio, formatThreshold } from "@/lib/format";

import { OffBalanceItems } from "./OffBalanceItems";

type Rule = FlagsOut["rules"][number];

const FREQS: { value: AnalysisFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "ttm", label: "TTM" },
];

const EMPTY = "No quality flags for this company.";

function levelText(rule: Rule, formula: string | null, level: string | null, name: string) {
  const sign = rule.direction === "above" ? ">" : "<";
  if (formula !== null) return [`${name} ${sign} ${formula}`];
  return level === null ? [] : [`${name} ${sign} ${formatThreshold(level, rule.unit)}`];
}

function thresholdText(rule: Rule): string {
  const parts = [
    ...levelText(rule, rule.warn_formula, rule.warn, "warn"),
    ...levelText(rule, rule.alert_formula, rule.alert, "alert"),
  ];
  return parts.length > 0 ? parts.join(" · ") : "—";
}

/** One period's levels for the cell title ("warn 4.1% · alert —"), formatted like the cell values. */
function levelsTitle(rule: Rule, index: number): string {
  const warn = formatRatio(rule.warn_levels[index] ?? null, rule.unit);
  const alert = formatRatio(rule.alert_levels[index] ?? null, rule.unit);
  return `warn ${warn} · alert ${alert}`;
}

// Notes sit on a rule's FY or quarter cell, not on TTM.
const notable = (period: PeriodOut) => !period.key.startsWith("TTM");

function columnDefs(
  payload: FlagsOut,
  markers: NoteIndex,
  onRuleNotes: (rule: Rule) => void,
): ColDef<Rule>[] {
  const periodColumns = payload.periods.map((period, index): ColDef<Rule> => ({
    colId: period.key,
    headerName: period.label,
    width: 100,
    headerClass: ["num", "ag-right-aligned-header"],
    valueGetter: ({ data }) => data?.values[index] ?? null,
    valueFormatter: ({ data }) =>
      data && data.error === null
        ? formatRatio(data.values[index] ?? null, data.unit)
        : data
          ? "—"
          : "",
    cellRenderer: ({ data, valueFormatted }: ICellRendererParams<Rule>) =>
      data ? <span title={levelsTitle(data, index)}>{valueFormatted}</span> : null,
    cellClass: ({ data }) => {
      const severity = data?.severity[index];
      return [
        "num",
        "ag-right-aligned-cell",
        ...(severity === "warn" ? ["flag-warn"] : severity === "alert" ? ["flag-alert"] : []),
        ...(data && notable(period) ? ["cursor-pointer", "hover:underline"] : []),
        ...(data &&
        notable(period) &&
        cellNotes(markers, "quality", data.code, period.fiscal_year, period.fiscal_period) > 0
          ? ["has-note"]
          : []),
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
          <span className="flex min-w-0 items-center gap-1">
            <span className="truncate" title={data.code}>
              {data.label}
              {data.custom && <span className="text-muted-foreground ml-1.5 text-xs">custom</span>}
            </span>
            {subjectNotes(markers, "quality", data.code) > 0 && (
              <NoteMarker label={data.label} onClick={() => onRuleNotes(data)} />
            )}
          </span>
        ) : null,
    },
    {
      colId: "rule",
      headerName: "Definition",
      width: 220,
      cellRenderer: ({ data }: { data?: Rule }) =>
        data?.error ? (
          <span className="text-destructive truncate" title={data.error}>
            {data.error}
          </span>
        ) : data ? (
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
  const markers = useNoteIndex(ticker);
  const [target, setTarget] = useState<SubjectTarget | null>(null);
  const { data, isPending, isError } = useQuery(flagsQueryOptions(ticker, freq));
  const columns = useMemo(
    () =>
      data
        ? columnDefs(data, markers, (rule) =>
            setTarget({ kind: "quality", code: rule.code, label: rule.label }),
          )
        : [],
    [data, markers],
  );
  const empty = data !== undefined && (data.rules.length === 0 || data.periods.length === 0);

  function openCell({ data: rule, column }: CellClickedEvent<Rule>) {
    const period = data?.periods.find((p) => p.key === column.getColId());
    if (!rule || !period || !notable(period)) return;
    setTarget(cellTarget("quality", rule.code, rule.label, period));
  }

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
        <DataGrid<Rule>
          rowData={data.rules}
          columnDefs={columns}
          getRowId={(r) => r.code}
          onCellClicked={openCell}
        />
      )}
      <SubjectNotesSheet ticker={ticker} target={target} onClose={() => setTarget(null)} />
      <OffBalanceItems ticker={ticker} />
    </div>
  );
}
