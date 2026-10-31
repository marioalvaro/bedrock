import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { segmentsQueryOptions } from "@/api/context";
import type { ScenarioOut, ScenarioSettingsIn } from "@/api/generated/types.gen";
import { useUpdateScenario } from "@/api/scenarios";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

type Method = ScenarioOut["revenue_method"];
type Dimension = NonNullable<ScenarioOut["segment_dimension"]>;

const METHODS: { value: Method; label: string }[] = [
  { value: "growth", label: "Growth" },
  { value: "segments", label: "Segments" },
  { value: "volume_price", label: "Volume × price" },
];
const DIMENSIONS: { value: Dimension; label: string }[] = [
  { value: "business", label: "Business" },
  { value: "geo", label: "Geographic" },
];

type Settings = Required<Omit<ScenarioSettingsIn, "name">>;

const settingsOf = (scenario: ScenarioOut): Settings => ({
  revenue_method: scenario.revenue_method,
  segment_dimension: scenario.segment_dimension,
  volume_kpi: scenario.volume_kpi,
  price_kpi: scenario.price_kpi,
});

const same = (a: Settings, b: Settings) =>
  (Object.keys(a) as (keyof Settings)[]).every((key) => a[key] === b[key]);

// The company's KPI series of one unit, as (code, name) choices.
function useKpis(ticker: string, enabled: boolean) {
  const { data } = useQuery({ ...segmentsQueryOptions(ticker, "annual"), enabled });
  const kpis = data?.blocks.find((block) => block.dimension === "kpi")?.series ?? [];
  const ofUnit = (unit: string) =>
    kpis
      .filter((series) => series.unit === unit)
      .map((series) => ({ code: series.metric, name: series.name }));
  return { loaded: data !== undefined, volume: ofUnit("count"), price: ofUnit("USD_per_unit") };
}

interface ScenarioSettingsProps {
  ticker: string;
  scenario: ScenarioOut; // the form is keyed by the scenario, so it re-fills after a save
}

/** The scenario's revenue build (the horizon is fixed); Save is disabled while nothing changed. */
export function ScenarioSettings({ ticker, scenario }: ScenarioSettingsProps) {
  const update = useUpdateScenario(ticker);
  const [draft, setDraft] = useState<Settings>(() => settingsOf(scenario));
  const [error, setError] = useState<string | null>(null);
  const kpis = useKpis(ticker, draft.revenue_method === "volume_price");

  const set = (patch: Partial<Settings>) => setDraft((current) => ({ ...current, ...patch }));

  function pickMethod(method: Method) {
    // Segments needs a dimension: start from Business rather than an invalid empty choice.
    set({
      revenue_method: method,
      ...(method === "segments" && !draft.segment_dimension && { segment_dimension: "business" }),
    });
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    update.mutate(
      { id: scenario.id, body: draft },
      { onError: (e) => setError(companyErrorMessage(e, "Could not save the settings.")) },
    );
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Scenario settings"
      className="border-border flex flex-wrap items-end gap-3 border-b px-4 py-2 text-sm"
      noValidate
    >
      <div className="space-y-1">
        <Label htmlFor="scenario-method">Revenue build</Label>
        <select
          id="scenario-method"
          className={SELECT}
          value={draft.revenue_method ?? "growth"}
          onChange={(e) => pickMethod(e.target.value as Method)}
        >
          {METHODS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {draft.revenue_method === "segments" && (
        <div className="space-y-1">
          <Label htmlFor="scenario-dimension">Segment dimension</Label>
          <select
            id="scenario-dimension"
            className={SELECT}
            value={draft.segment_dimension ?? "business"}
            onChange={(e) => set({ segment_dimension: e.target.value as Dimension })}
          >
            {DIMENSIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      )}
      {draft.revenue_method === "volume_price" &&
        kpis.loaded &&
        (kpis.volume.length === 0 || kpis.price.length === 0 ? (
          <p className="text-muted-foreground self-center text-xs">
            Add a count KPI and a price KPI in Segments
          </p>
        ) : (
          <>
            <KpiSelect
              id="scenario-volume"
              label="Volume KPI"
              choices={kpis.volume}
              value={draft.volume_kpi}
              onChange={(code) => set({ volume_kpi: code })}
            />
            <KpiSelect
              id="scenario-price"
              label="Price KPI"
              choices={kpis.price}
              value={draft.price_kpi}
              onChange={(code) => set({ price_kpi: code })}
            />
          </>
        ))}
      <Button
        type="submit"
        size="sm"
        disabled={same(draft, settingsOf(scenario)) || update.isPending}
      >
        Save settings
      </Button>
      {error && (
        <p role="alert" className="text-destructive basis-full text-xs">
          {error}
        </p>
      )}
    </form>
  );
}

interface KpiSelectProps {
  id: string;
  label: string;
  choices: { code: string; name: string }[];
  value: string | null;
  onChange: (code: string | null) => void;
}

function KpiSelect({ id, label, choices, value, onChange }: KpiSelectProps) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        className={SELECT}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">Choose…</option>
        {choices.map((choice) => (
          <option key={choice.code} value={choice.code}>
            {choice.name}
          </option>
        ))}
      </select>
    </div>
  );
}
