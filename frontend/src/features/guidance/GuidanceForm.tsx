import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { useCreateGuidance, useUpdateGuidance } from "@/api/context";
import type { GuidanceEntryOut, GuidanceIn, MetricChoiceOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { parseGuidanceValue, scaleLabel, toGuidanceText } from "@/lib/format";
import { localIsoDate, useNow } from "@/lib/now";
import { useScale, type Scale } from "@/lib/scale";

type Period = GuidanceIn["fiscal_period"];
type Direction = NonNullable<GuidanceIn["direction"]>;
type Basis = GuidanceIn["basis"];

const SELECT = "border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm";
const QUARTERS: Period[] = ["Q1", "Q2", "Q3", "Q4"];
const GROUPS: { group: MetricChoiceOut["group"]; label: string }[] = [
  { group: "line", label: "Lines" },
  { group: "ratio", label: "Ratios" },
  { group: "kpi", label: "KPIs" },
];

// What a value is typed in, shown next to Low and High.
function unitHint(unit: string, scale: Scale): string {
  if (unit === "USD" || unit === "shares") return scaleLabel(unit, scale);
  if (unit === "pct") return "%";
  if (unit === "USD/shares" || unit === "USD_per_unit") return "USD";
  return unit;
}

interface GuidanceFormProps {
  ticker: string;
  metrics: MetricChoiceOut[];
  // The entry being edited; a new entry when absent.
  entry?: GuidanceEntryOut;
  onDone: () => void;
}

/** Adds or edits one guidance entry: metric, period, range in the metric's unit and basis. */
export function GuidanceForm({ ticker, metrics, entry, onDone }: GuidanceFormProps) {
  const scale = useScale();
  const now = useNow();
  const today = localIsoDate(now);
  const create = useCreateGuidance(ticker);
  const update = useUpdateGuidance(ticker);

  // A stored metric that is no longer offered (a deleted KPI) stays selectable.
  const choices =
    entry && !metrics.some((m) => m.metric === entry.metric)
      ? [
          ...metrics,
          {
            metric: entry.metric,
            label: entry.label,
            group: "kpi" as const,
            unit: entry.unit ?? "count",
            default_direction: entry.direction,
            quarterly: true,
          },
        ]
      : metrics;
  const initial = entry ? entry.metric : (choices[0]?.metric ?? "");
  const initialUnit = choices.find((m) => m.metric === initial)?.unit ?? "count";

  const [metric, setMetric] = useState(initial);
  const [year, setYear] = useState(String(entry?.fiscal_year ?? now.getFullYear()));
  const [period, setPeriod] = useState<Period>((entry?.fiscal_period as Period) ?? "FY");
  const [low, setLow] = useState(entry ? toGuidanceText(entry.low, initialUnit, scale) : "");
  const [high, setHigh] = useState(entry ? toGuidanceText(entry.high, initialUnit, scale) : "");
  const [basis, setBasis] = useState<Basis>(entry?.basis ?? "reported");
  const [direction, setDirection] = useState<Direction>(
    entry?.direction ?? choices.find((m) => m.metric === initial)?.default_direction ?? "higher",
  );
  const [givenOn, setGivenOn] = useState(entry?.given_on ?? today);
  const [sourceNote, setSourceNote] = useState(entry?.source_note ?? "");
  const [error, setError] = useState<string | null>(null);

  const choice = choices.find((m) => m.metric === metric);
  const unit = choice?.unit ?? "count";
  const periods: Period[] = choice?.quarterly ? ["FY", ...QUARTERS] : ["FY"];

  function pickMetric(next: string) {
    const picked = choices.find((m) => m.metric === next);
    setMetric(next);
    if (picked) setDirection(picked.default_direction);
    if (!picked?.quarterly) setPeriod("FY");
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const lowValue = parseGuidanceValue(low, unit, scale);
    const highValue = parseGuidanceValue(high, unit, scale);
    if (lowValue === null || highValue === null) return setError("Enter a number");
    if (!/^\d{4}$/.test(year.trim())) return setError("Enter a fiscal year");
    if (givenOn === "") return setError("Enter the date given");
    setError(null);
    const body: GuidanceIn = {
      metric,
      fiscal_year: Number(year.trim()),
      fiscal_period: period,
      low: lowValue,
      high: highValue,
      basis,
      direction,
      given_on: givenOn,
      source_note: sourceNote.trim() || null,
    };
    const options = {
      onSuccess: onDone,
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the guidance.")),
    };
    if (entry) update.mutate({ id: entry.id, body }, options);
    else create.mutate(body, options);
  }

  return (
    <form onSubmit={submit} className="border-border space-y-2 border-b px-4 py-3" noValidate>
      <div className="grid gap-2 sm:grid-cols-3">
        <div className="space-y-1 sm:col-span-3">
          <Label htmlFor="guidance-metric">Metric</Label>
          <select
            id="guidance-metric"
            value={metric}
            onChange={(e) => pickMetric(e.target.value)}
            className={SELECT}
          >
            {GROUPS.map(({ group, label }) => {
              const options = choices.filter((m) => m.group === group);
              if (options.length === 0) return null;
              return (
                <optgroup key={group} label={label}>
                  {options.map((m) => (
                    <option key={m.metric} value={m.metric}>
                      {m.label}
                    </option>
                  ))}
                </optgroup>
              );
            })}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="guidance-year">Fiscal year</Label>
          <Input
            id="guidance-year"
            inputMode="numeric"
            value={year}
            onChange={(e) => setYear(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="guidance-period">Period</Label>
          <select
            id="guidance-period"
            value={period}
            onChange={(e) => setPeriod(e.target.value as Period)}
            className={SELECT}
          >
            {periods.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="guidance-given-on">Given on</Label>
          <Input
            id="guidance-given-on"
            type="date"
            value={givenOn}
            onChange={(e) => setGivenOn(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <span className="flex items-baseline justify-between gap-2">
            <Label htmlFor="guidance-low">Low</Label>
            <span className="text-muted-foreground text-xs">{unitHint(unit, scale)}</span>
          </span>
          <Input
            id="guidance-low"
            inputMode="decimal"
            value={low}
            onChange={(e) => setLow(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="guidance-high">High</Label>
          <Input
            id="guidance-high"
            inputMode="decimal"
            value={high}
            onChange={(e) => setHigh(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="guidance-basis">Basis</Label>
          <select
            id="guidance-basis"
            value={basis}
            onChange={(e) => setBasis(e.target.value as Basis)}
            className={SELECT}
          >
            <option value="reported">Reported</option>
            <option value="normalized">Normalized</option>
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="guidance-direction">Direction</Label>
          <select
            id="guidance-direction"
            value={direction}
            onChange={(e) => setDirection(e.target.value as Direction)}
            className={SELECT}
          >
            <option value="higher">Higher is better</option>
            <option value="lower">Lower is better</option>
          </select>
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="guidance-source">Source note</Label>
          <Input
            id="guidance-source"
            value={sourceNote}
            onChange={(e) => setSourceNote(e.target.value)}
          />
        </div>
      </div>
      <p className="text-muted-foreground text-xs">
        Use the statements' sign: outflows such as capex are negative
      </p>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={create.isPending || update.isPending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
