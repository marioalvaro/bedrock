import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import type { SensitivityGridOut, TornadoBarOut } from "@/api/generated/types.gen";
import { CASES, type ScenarioCase } from "@/api/scenarios";
import { ValuationUnavailable, sensitivityGridQueryOptions } from "@/api/valuation";
import { Label } from "@/components/ui/label";
import { useScale } from "@/lib/scale";
import { cn } from "@/lib/utils";

import { formatPerShare, gridPointText, gridPointTitle, upsideClass } from "./valuationFormat";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const CENTER = 2;
const POINTS = [0, 1, 2, 3, 4];

type Input = Pick<TornadoBarOut, "code" | "label" | "kind">;

// Columns: the discount rate; rows: terminal growth, or the exit multiple when the case values
// its terminal value by an exit multiple (the tornado then has no terminal growth). Without them,
// the first listed inputs, two different ones when there are two.
function defaultAxes(inputs: Input[]) {
  const codes = inputs.map((input) => input.code);
  const x = codes.includes("discount_rate") ? "discount_rate" : (codes[0] ?? "");
  const y =
    ["terminal_growth", "exit_multiple"].find((code) => codes.includes(code)) ??
    codes.find((code) => code !== x) ??
    x;
  return { x, y };
}

interface GridTableProps {
  grid: SensitivityGridOut;
  inputs: Input[];
  scenarioCase: ScenarioCase;
}

function GridTable({ grid, inputs, scenarioCase }: GridTableProps) {
  const scale = useScale();
  const kindOf = (code: string) => inputs.find((input) => input.code === code)?.kind ?? "valuation";
  const xKind = kindOf(grid.x.code);
  const yKind = kindOf(grid.y.code);
  const caseLabel = CASES.find((item) => item.value === scenarioCase)?.label ?? scenarioCase;

  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <caption className="text-muted-foreground pb-1 text-left text-xs">
          DCF value per share, {caseLabel} case
        </caption>
        <thead className="text-muted-foreground text-xs">
          <tr>
            <th className="px-3 py-1 text-left font-normal">
              {grid.y.label} ↓ · {grid.x.label} →
            </th>
            {POINTS.map((j) => (
              <th
                key={j}
                scope="col"
                title={gridPointTitle(grid.x, xKind, j, scale)}
                className="px-3 py-1 text-right font-normal"
              >
                {gridPointText(grid.x, xKind, j)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {POINTS.map((i) => (
            <tr key={i}>
              <th
                scope="row"
                title={gridPointTitle(grid.y, yKind, i, scale)}
                className="text-muted-foreground px-3 py-1 text-right text-xs font-normal"
              >
                {gridPointText(grid.y, yKind, i)}
              </th>
              {POINTS.map((j) => {
                const value = grid.values[i]?.[j] ?? null;
                const center = i === CENTER && j === CENTER;
                return (
                  <td
                    key={j}
                    title={value === null ? (grid.errors[i]?.[j] ?? undefined) : undefined}
                    aria-current={center ? "true" : undefined}
                    className={cn(
                      "num px-3 py-1 text-right",
                      upsideClass(grid.upside[i]?.[j] ?? null),
                      center && "ring-ring font-semibold ring-1 ring-inset",
                    )}
                  >
                    {formatPerShare(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface SensitivityGridProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase; // the view keys this component by scenario and case
  inputs: Input[]; // the tornado's inputs, in its order
}

/**
 * The DCF value per share over two inputs, 5 × 5 (rows and columns picked from the tornado's
 * inputs). The previous pair stays shown, marked "Updating…", while a new one loads.
 */
export function SensitivityGrid({
  ticker,
  scenarioId,
  scenarioCase,
  inputs,
}: SensitivityGridProps) {
  const id = useId();
  const [axes, setAxes] = useState(() => defaultAxes(inputs));
  const same = axes.x === axes.y;
  const { data, isPending, isPlaceholderData, error } = useQuery({
    ...sensitivityGridQueryOptions(ticker, scenarioId, scenarioCase, axes.x, axes.y),
    enabled: !same,
    placeholderData: keepPreviousData, // the table stays mounted while another pair loads (G32)
  });

  const select = (axis: "x" | "y", label: string) => (
    <span className="flex items-center gap-2">
      <Label htmlFor={`${id}-${axis}`}>{label}</Label>
      <select
        id={`${id}-${axis}`}
        className={SELECT}
        value={axes[axis]}
        onChange={(e) => setAxes((current) => ({ ...current, [axis]: e.target.value }))}
      >
        {inputs.map((input) => (
          <option key={input.code} value={input.code}>
            {input.label}
          </option>
        ))}
      </select>
    </span>
  );

  let body;
  if (same) {
    body = <p className="text-muted-foreground text-sm">Pick two different inputs</p>;
  } else if (data) {
    body = <GridTable grid={data} inputs={inputs} scenarioCase={scenarioCase} />;
  } else if (isPending) {
    body = <p className="text-muted-foreground text-sm">Loading the grid…</p>;
  } else {
    body = (
      <p className="text-destructive text-sm">
        {error instanceof ValuationUnavailable && error.detail
          ? error.detail
          : "Could not load the sensitivity grid."}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        {select("y", "Rows")}
        {select("x", "Columns")}
        {!same && isPlaceholderData && (
          <span className="text-muted-foreground text-xs">Updating…</span>
        )}
      </div>
      {body}
    </div>
  );
}
