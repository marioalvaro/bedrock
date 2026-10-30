import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { useCreateSeries, useUpdateSeries } from "@/api/context";
import type { SegmentSeriesIn } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Dimension = SegmentSeriesIn["dimension"];
type Unit = SegmentSeriesIn["unit"];

// What the form starts from: a new series (in a block, or the default one) or a rename.
export type SeriesFormMode =
  | { type: "new"; dimension: Dimension; metric: string }
  | { type: "rename"; id: number; name: string; displayOrder: number };

const SELECT = "border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm";

const DIMENSIONS: { value: Dimension; label: string }[] = [
  { value: "business", label: "Business segment" },
  { value: "geo", label: "Geographic segment" },
  { value: "kpi", label: "KPI" },
];
const METRICS = [
  { value: "revenue", label: "Revenue" },
  { value: "operating_income", label: "Operating income" },
];
const KPI_UNITS: { value: Unit; label: string }[] = [
  { value: "USD", label: "USD" },
  { value: "pct", label: "Percent" },
  { value: "count", label: "Count" },
  { value: "USD_per_unit", label: "USD per unit" },
];

interface SeriesFormProps {
  ticker: string;
  mode: SeriesFormMode;
  onDone: () => void;
}

/** Adds a series (name, dimension and metric; a KPI also a code and unit) or renames one. */
export function SeriesForm({ ticker, mode, onDone }: SeriesFormProps) {
  const create = useCreateSeries(ticker);
  const update = useUpdateSeries(ticker);
  const [name, setName] = useState(mode.type === "rename" ? mode.name : "");
  const [dimension, setDimension] = useState<Dimension>(
    mode.type === "new" ? mode.dimension : "business",
  );
  const [metric, setMetric] = useState(mode.type === "new" ? mode.metric : "revenue");
  const [code, setCode] = useState("");
  const [unit, setUnit] = useState<Unit>("USD");
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending;
  const isKpi = dimension === "kpi";

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (name.trim() === "") return setError("Enter a name");
    setError(null);
    const options = {
      onSuccess: onDone,
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the series.")),
    };
    if (mode.type === "rename") {
      update.mutate(
        { id: mode.id, body: { name: name.trim(), display_order: mode.displayOrder } },
        options,
      );
      return;
    }
    if (isKpi && code.trim() === "") return setError("Enter a code");
    create.mutate(
      {
        dimension,
        name: name.trim(),
        metric: isKpi ? code.trim() : metric,
        unit: isKpi ? unit : "USD",
      },
      options,
    );
  }

  return (
    <form onSubmit={submit} className="border-border space-y-2 border-b px-4 py-3" noValidate>
      <div className="grid gap-2 sm:grid-cols-2">
        {mode.type === "new" && (
          <div className="space-y-1">
            <Label htmlFor="series-dimension">Dimension</Label>
            <select
              id="series-dimension"
              value={dimension}
              onChange={(e) => setDimension(e.target.value as Dimension)}
              className={SELECT}
            >
              {DIMENSIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="space-y-1">
          <Label htmlFor="series-name">Name</Label>
          <Input id="series-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {mode.type === "new" && !isKpi && (
          <div className="space-y-1">
            <Label htmlFor="series-metric">Metric</Label>
            <select
              id="series-metric"
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className={SELECT}
            >
              {METRICS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        )}
        {mode.type === "new" && isKpi && (
          <>
            <div className="space-y-1">
              <Label htmlFor="series-code">Code</Label>
              <Input
                id="series-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="same_store_sales"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="series-unit">Unit</Label>
              <select
                id="series-unit"
                value={unit}
                onChange={(e) => setUnit(e.target.value as Unit)}
                className={SELECT}
              >
                {KPI_UNITS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </>
        )}
      </div>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={pending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
