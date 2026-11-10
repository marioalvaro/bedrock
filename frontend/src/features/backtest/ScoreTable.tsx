import { useMemo } from "react";
import { useSearchParams } from "react-router";

import type { ScoreRowOut } from "@/api/generated/types.gen";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import {
  FREQ_PARAM,
  METRIC_PARAM,
  STATS,
  STAT_PARAM,
  metricOptions,
  scoreTableRows,
  type Selection,
} from "./backtestFormat";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const CELL = "px-2 py-1 text-right";
const NO_RANGE_TITLE = "Ranges exist for drivers now, and for lines from M8";

interface ScoreProps {
  summary: ScoreRowOut[];
  selection: Selection;
}

/** Metric, Annual | Quarterly and MAPE | Bias | Hit rate, kept in the URL. */
export function ScoreControls({ summary, selection }: ScoreProps) {
  const [, setParams] = useSearchParams();
  const { lines, drivers } = useMemo(() => metricOptions(summary), [summary]);

  const write = (name: string, value: string) =>
    setParams(
      (current) => {
        const updated = new URLSearchParams(current);
        updated.set(name, value);
        return updated;
      },
      { replace: true },
    );

  return (
    <>
      <select
        aria-label="Metric"
        className={SELECT}
        value={selection.code}
        onChange={(e) => write(METRIC_PARAM, e.target.value)}
      >
        {(
          [
            ["Lines", lines],
            ["Drivers", drivers],
          ] as const
        ).map(
          ([group, options]) =>
            options.length > 0 && (
              <optgroup key={group} label={group}>
                {options.map(({ code, label }) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </optgroup>
            ),
        )}
      </select>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={0}
        aria-label="Frequency"
        value={selection.freq}
        onValueChange={(value) => value && write(FREQ_PARAM, value)}
      >
        <ToggleGroupItem value="annual">Annual</ToggleGroupItem>
        <ToggleGroupItem value="quarterly" disabled={selection.kind === "driver"}>
          Quarterly
        </ToggleGroupItem>
      </ToggleGroup>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={0}
        aria-label="Statistic"
        value={selection.stat}
        onValueChange={(value) => value && write(STAT_PARAM, value)}
      >
        {STATS.map(({ value, label }) => {
          const unavailable = value === "hit_rate" && !selection.hitRateAvailable;
          return (
            <ToggleGroupItem
              key={value}
              value={value}
              disabled={unavailable}
              // A disabled toggle ignores the pointer, which would hide its title.
              className="disabled:pointer-events-auto"
              title={unavailable ? NO_RANGE_TITLE : undefined}
            >
              {label}
            </ToggleGroupItem>
          );
        })}
      </ToggleGroup>
    </>
  );
}

/** Methods × horizons of the selection, with each cell's `n` in its title. */
export function ScoreTable({ summary, selection }: ScoreProps) {
  const { horizons, rows } = useMemo(
    () => scoreTableRows(summary, selection),
    [summary, selection],
  );
  if (rows.length === 0) {
    return <p className="text-muted-foreground text-sm">No scores for this selection.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table aria-label="Scores" className="num text-sm">
        <thead className="text-muted-foreground">
          <tr>
            <th className="px-2 py-1 text-left font-medium">Horizon</th>
            {horizons.map((horizon) => (
              <th key={horizon} className={`${CELL} font-medium`}>
                {horizon}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.method} className="border-border border-t">
              <th scope="row" className="px-2 py-1 text-left font-medium whitespace-nowrap">
                {row.label}
              </th>
              {row.cells.map((cell) => (
                <td key={cell.horizon} className={CELL} title={cell.title}>
                  {cell.text}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
