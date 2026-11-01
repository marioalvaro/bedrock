import { useQuery } from "@tanstack/react-query";
import type { CellClassParams, ColDef } from "ag-grid-community";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { companyErrorMessage } from "@/api/companies";
import type { ForecastOut } from "@/api/generated/types.gen";
import {
  CASES,
  ForecastUnavailable,
  forecastQueryOptions,
  scenariosQueryOptions,
  type ForecastFreq,
  type ScenarioCase,
} from "@/api/scenarios";
import type { StatementType } from "@/api/statements";
import { DataGrid } from "@/components/DataGrid";
import { ProvenanceLegend } from "@/components/ProvenanceLegend";
import { UnitToggle } from "@/components/UnitToggle";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  CASE_PARAM,
  SCENARIO_PARAM,
  useScenarioParam,
} from "@/features/scenarios/useScenarioParam";
import {
  cellText,
  expandableCodes,
  forecastColumnClass,
  provenanceClasses,
  rowUnitHint,
  toGridRows,
  type GridRow,
} from "@/features/statements/grid";
import { scaleLabel } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

import { IntegrityPanel } from "./IntegrityPanel";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

const STATEMENTS: { value: StatementType; label: string }[] = [
  { value: "IS", label: "Income" },
  { value: "BS", label: "Balance" },
  { value: "CF", label: "Cash flow" },
];

const FREQS: { value: ForecastFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
];

// A forecast the user can unblock by setting drivers in the Scenarios tab.
const MISSING_DRIVERS = "Set these drivers";

function columnDefs(payload: ForecastOut, scale: Scale): ColDef<GridRow>[] {
  const labelColumn: ColDef<GridRow> = {
    colId: "label",
    headerName: scaleLabel("USD", scale),
    pinned: "left",
    // Pinned, so on a phone it must leave room for the periods.
    width: Math.min(240, Math.round(window.innerWidth * 0.4)),
    cellRenderer: ({ data }: { data?: GridRow }) => {
      if (!data) return null;
      const hint = rowUnitHint(data.unit, scale);
      return (
        <span
          className="flex min-w-0 items-center gap-1"
          style={{ paddingLeft: `${data.depth * 12}px` }}
          title={data.label}
        >
          <span className="truncate">{data.label}</span>
          {hint && <span className="text-muted-foreground shrink-0">· {hint}</span>}
        </span>
      );
    },
  };

  const periodColumns = payload.periods.map((period): ColDef<GridRow> => ({
    colId: period.key,
    headerName: period.label,
    width: 100,
    headerClass: ["num", "ag-right-aligned-header", ...forecastColumnClass(period)],
    valueGetter: ({ data }) => data?.values[period.key] ?? null,
    valueFormatter: ({ data }) => (data ? cellText(data, period.key, scale) : ""),
    cellClass: ({ data }: CellClassParams<GridRow>) => {
      const classes = ["num", "ag-right-aligned-cell", ...forecastColumnClass(period)];
      if (!data) return classes;
      classes.push(...provenanceClasses(data.provenance[period.key]));
      if (data.kind === "balance_check" && data.ok?.[period.key] === false) {
        classes.push("text-destructive");
      }
      return classes;
    },
  }));

  return [labelColumn, ...periodColumns];
}

interface ForecastBodyProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase;
  type: StatementType;
  freq: ForecastFreq;
}

function ForecastBody({ ticker, scenarioId, scenarioCase, type, freq }: ForecastBodyProps) {
  const scale = useScale();
  const { data, isPending, isPlaceholderData, error } = useQuery({
    ...forecastQueryOptions(ticker, scenarioId, scenarioCase, type, freq),
    // While the other frequency loads, keep the same case's statement on screen, so the grid is
    // not unmounted and rebuilt (Gotcha G32). Another case's numbers are never shown in its place.
    placeholderData: (previous) =>
      previous?.statement === type &&
      previous.scenario_id === scenarioId &&
      previous.case === scenarioCase
        ? previous
        : undefined,
  });

  // Every line is shown with its breakdown: the forecast is read whole, nothing is adjusted here.
  const rows = useMemo(
    () =>
      data
        ? toGridRows(data, {
            yoy: false,
            commonSize: false,
            expanded: new Set(expandableCodes(data)),
          })
        : [],
    [data],
  );
  const columns = useMemo(() => (data ? columnDefs(data, scale) : []), [data, scale]);

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (!data) {
    if (error instanceof ForecastUnavailable) {
      return (
        <div className="space-y-2 p-4 text-sm">
          <p>{error.detail}</p>
          {error.detail?.startsWith(MISSING_DRIVERS) && (
            <Button asChild size="sm" variant="outline">
              <Link
                to={`/c/${ticker}/scenarios?${new URLSearchParams({ [SCENARIO_PARAM]: String(scenarioId), [CASE_PARAM]: scenarioCase })}`}
              >
                Open Scenarios
              </Link>
            </Button>
          )}
        </div>
      );
    }
    return <p className="text-destructive p-4 text-sm">Could not load the forecast.</p>;
  }

  return (
    <>
      {isPlaceholderData && <p className="text-muted-foreground px-4 py-1 text-xs">Updating…</p>}
      {rows.length === 0 ? (
        <p className="text-muted-foreground p-4 text-sm">No forecast lines to show.</p>
      ) : (
        <DataGrid<GridRow> rowData={rows} columnDefs={columns} getRowId={(row) => row.id} />
      )}
      <IntegrityPanel
        integrity={data.integrity}
        periods={data.periods}
        warnings={data.warnings}
        scale={scale}
      />
    </>
  );
}

interface ForecastViewProps {
  ticker: string;
}

/**
 * The Forecast tab: a scenario case's IS/BS/CF forecast after the recent actuals, annual or
 * quarterly, with the forecast's integrity checks. Read only: drivers are set in the Scenarios tab.
 */
export function ForecastView({ ticker }: ForecastViewProps) {
  const { data: list, isPending, error } = useQuery(scenariosQueryOptions(ticker));
  const { selected, select, scenarioCase, selectCase } = useScenarioParam(list);
  const [type, setType] = useState<StatementType>("IS");
  const [freq, setFreq] = useState<ForecastFreq>("annual");

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (list?.length === 0) return <p className="text-muted-foreground p-4 text-sm">No scenarios.</p>;
  // Only a failed first load replaces the tab; a failed background refetch keeps the data shown.
  if (!list || !selected) {
    return (
      <p className="text-destructive p-4 text-sm">
        {companyErrorMessage(error, "Could not load the scenarios.")}
      </p>
    );
  }

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <select
          aria-label="Scenario"
          className={SELECT}
          value={selected.id}
          onChange={(e) => select(Number(e.target.value))}
        >
          {list.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.name}
            </option>
          ))}
        </select>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Case"
          value={scenarioCase}
          onValueChange={(value) => value && selectCase(value as ScenarioCase)}
        >
          {CASES.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Statement"
          value={type}
          onValueChange={(value) => value && setType(value as StatementType)}
        >
          {STATEMENTS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="Frequency"
          value={freq}
          onValueChange={(value) => value && setFreq(value as ForecastFreq)}
        >
          {FREQS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <UnitToggle />
      </div>
      <div className="px-4 py-1">
        <ProvenanceLegend forecast />
      </div>
      <ForecastBody
        ticker={ticker}
        scenarioId={selected.id}
        scenarioCase={scenarioCase}
        type={type}
        freq={freq}
      />
    </div>
  );
}
