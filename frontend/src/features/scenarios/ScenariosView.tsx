import { useQuery } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";
import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import type { ScenarioOut } from "@/api/generated/types.gen";
import {
  CASES,
  driverExportUrl,
  scenariosQueryOptions,
  useCreateScenario,
  useDeleteScenario,
  useResetCase,
  useUpdateScenario,
  type ForecastFreq,
  type ScenarioCase,
} from "@/api/scenarios";
import { UnitToggle } from "@/components/UnitToggle";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useScale } from "@/lib/scale";

import { DriverGrid } from "./DriverGrid";
import { DriverImportSheet } from "./DriverImportSheet";
import { ScenarioCompare } from "./ScenarioCompare";
import { ScenarioSettings } from "./ScenarioSettings";
import { useScenarioParam } from "./useScenarioParam";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

type NameMode = { type: "new" } | { type: "rename"; scenario: ScenarioOut };

// What Reset asks, per case: Base has no rows of its own after a reset, Bull and Bear get the
// default offsets back.
const OFFSETS_RESET =
  "Its own values are removed and the default offsets come back (+3 pts revenue growth, +1 pt gross margin; each segment's growth on Segments).";
const RESET_TEXT: Record<ScenarioCase, string> = {
  base: "Every driver of Base goes back to its default.",
  bull: OFFSETS_RESET,
  bear: OFFSETS_RESET,
};

// The revenue builds a new scenario can start from; "" takes the default scenario's. Volume × price
// needs KPIs, so it is set in the settings after the scenario exists.
const NEW_BUILDS = [
  { value: "growth", label: "Growth" },
  { value: "segments", label: "Segments" },
] as const;
type NewBuild = (typeof NEW_BUILDS)[number]["value"] | "";

interface NameFormProps {
  ticker: string;
  mode: NameMode;
  defaultName: string;
  // Called with the saved scenario's id, or null on Cancel.
  onDone: (id: number | null) => void;
}

/**
 * Names a new scenario (it starts from the default drivers, on the chosen revenue build) or
 * renames one.
 */
function NameForm({ ticker, mode, defaultName, onDone }: NameFormProps) {
  const create = useCreateScenario(ticker);
  const update = useUpdateScenario(ticker);
  const [name, setName] = useState(mode.type === "rename" ? mode.scenario.name : "");
  const [build, setBuild] = useState<NewBuild>("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") return setError("Enter a name");
    setError(null);
    const options = {
      onSuccess: (saved: ScenarioOut) => onDone(saved.id),
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the scenario.")),
    };
    if (mode.type === "rename") {
      update.mutate({ id: mode.scenario.id, body: { name: trimmed } }, options);
    } else {
      create.mutate(
        {
          name: trimmed,
          ...(build !== "" && { revenue_method: build }),
          ...(build === "segments" && { segment_dimension: "business" as const }),
        },
        options,
      );
    }
  }

  return (
    <form onSubmit={submit} className="border-border space-y-2 border-b px-4 py-3" noValidate>
      <div className="max-w-sm space-y-1">
        <Label htmlFor="scenario-name">Name</Label>
        <Input
          id="scenario-name"
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      {mode.type === "new" && (
        <div className="space-y-1">
          <Label htmlFor="scenario-new-build">Revenue build</Label>
          <select
            id="scenario-new-build"
            aria-label="New scenario revenue build"
            className={SELECT}
            value={build}
            onChange={(e) => setBuild(e.target.value as NewBuild)}
          >
            <option value="">Same as {defaultName}</option>
            {NEW_BUILDS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={create.isPending || update.isPending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => onDone(null)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

interface ScenariosViewProps {
  ticker: string;
}

/**
 * The Scenarios tab: pick, create, rename and delete scenarios, set a scenario's revenue build,
 * and pick one of its three cases (Base, Bull, Bear) to edit its drivers against the actual
 * history, reset it or compare the three.
 */
export function ScenariosView({ ticker }: ScenariosViewProps) {
  const scale = useScale();
  const { data: list, isPending, error } = useQuery(scenariosQueryOptions(ticker));
  const { selected, select, scenarioCase, selectCase } = useScenarioParam(list);
  const remove = useDeleteScenario(ticker);
  const reset = useResetCase(ticker);
  const [naming, setNaming] = useState<NameMode | null>(null);
  const [deleting, setDeleting] = useState<ScenarioOut | null>(null);
  const [resetting, setResetting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [freq, setFreq] = useState<ForecastFreq>("annual");

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  // Only a failed first load replaces the tab; a failed background refetch keeps the data shown.
  if (!list || !selected) {
    return (
      <p className="text-destructive p-4 text-sm">
        {companyErrorMessage(error, "Could not load the scenarios.")}
      </p>
    );
  }
  const base = list.find((scenario) => scenario.is_default) ?? list[0]!;
  const caseLabel = CASES.find((candidate) => candidate.value === scenarioCase)!.label;

  function confirmDelete() {
    if (!deleting) return;
    remove.mutate(deleting.id, {
      onSuccess: () => select(base.id),
      onError: (e) => setMessage(companyErrorMessage(e, "Could not delete the scenario.")),
    });
  }

  function confirmReset() {
    setMessage(null);
    reset.mutate(
      { id: selected!.id, case: scenarioCase },
      { onError: (e) => setMessage(companyErrorMessage(e, "Could not reset the case.")) },
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
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setNaming({ type: "new" })}
        >
          New
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setNaming({ type: "rename", scenario: selected })}
        >
          Rename
        </Button>
        {!selected.is_default && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              setMessage(null);
              setDeleting(selected);
            }}
          >
            Delete
          </Button>
        )}
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
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={reset.isPending}
          onClick={() => {
            setMessage(null);
            setResetting(true);
          }}
        >
          Reset {caseLabel}
        </Button>
        <UnitToggle />
        <div className="ml-auto flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <a href={driverExportUrl(ticker, selected.id, scenarioCase, "csv")} download>
              <Download /> Export CSV
            </a>
          </Button>
          <Button asChild size="sm" variant="outline">
            <a href={driverExportUrl(ticker, selected.id, scenarioCase, "xlsx")} download>
              <Download /> Export Excel
            </a>
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setImporting(true)}>
            <Upload /> Import
          </Button>
        </div>
      </div>
      {message && (
        <p role="alert" className="text-destructive px-4 py-2 text-sm">
          {message}
        </p>
      )}
      {naming && (
        <NameForm
          key={naming.type === "rename" ? `rename-${naming.scenario.id}` : "new"}
          ticker={ticker}
          mode={naming}
          defaultName={base.name}
          onDone={(id) => {
            setNaming(null);
            if (id !== null) select(id);
          }}
        />
      )}
      <ScenarioSettings
        key={`${selected.id}-${selected.updated_at}`}
        ticker={ticker}
        scenario={selected}
      />
      <DriverGrid
        key={`${selected.id}-${scenarioCase}`}
        ticker={ticker}
        scenario={selected}
        scenarioCase={scenarioCase}
        freq={freq}
        onFreq={setFreq}
        scale={scale}
      />
      <ScenarioCompare key={selected.id} ticker={ticker} scenarioId={selected.id} />
      <DriverImportSheet
        key={importing ? `open-${selected.id}-${scenarioCase}` : "closed"}
        ticker={ticker}
        scenarioId={selected.id}
        scenarioCase={scenarioCase}
        open={importing}
        scale={scale}
        onClose={() => setImporting(false)}
      />
      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              The scenario, its Base, Bull and Bear cases and their drivers are removed. The other
              scenarios stay as they are.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={resetting} onOpenChange={setResetting}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset {caseLabel}?</AlertDialogTitle>
            <AlertDialogDescription>{RESET_TEXT[scenarioCase]}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmReset}>Reset</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
