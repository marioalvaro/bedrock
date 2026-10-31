import { useQuery } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";
import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import type { ScenarioOut } from "@/api/generated/types.gen";
import {
  driverExportUrl,
  scenariosQueryOptions,
  useCreateScenario,
  useDeleteScenario,
  useUpdateScenario,
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
import { useScale } from "@/lib/scale";

import { DriverGrid } from "./DriverGrid";
import { DriverImportSheet } from "./DriverImportSheet";
import { ScenarioCompare } from "./ScenarioCompare";
import { ScenarioSettings } from "./ScenarioSettings";
import { useScenarioParam } from "./useScenarioParam";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

type NameMode = { type: "new" } | { type: "rename"; scenario: ScenarioOut };

interface NameFormProps {
  ticker: string;
  mode: NameMode;
  // Called with the saved scenario's id, or null on Cancel.
  onDone: (id: number | null) => void;
}

/** Names a new scenario (its settings copy Base's, its drivers inherit Base) or renames one. */
function NameForm({ ticker, mode, onDone }: NameFormProps) {
  const create = useCreateScenario(ticker);
  const update = useUpdateScenario(ticker);
  const [name, setName] = useState(mode.type === "rename" ? mode.scenario.name : "");
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
      create.mutate({ name: trimmed }, options);
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
 * The Scenarios tab: pick, create, rename and delete scenarios, set their revenue build and
 * horizons, and edit their drivers against the actual history.
 */
export function ScenariosView({ ticker }: ScenariosViewProps) {
  const scale = useScale();
  const { data: list, isPending, error } = useQuery(scenariosQueryOptions(ticker));
  const { selected, select } = useScenarioParam(list);
  const remove = useDeleteScenario(ticker);
  const [naming, setNaming] = useState<NameMode | null>(null);
  const [deleting, setDeleting] = useState<ScenarioOut | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

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

  function confirmDelete() {
    if (!deleting) return;
    remove.mutate(deleting.id, {
      onSuccess: () => select(base.id),
      onError: (e) => setMessage(companyErrorMessage(e, "Could not delete the scenario.")),
    });
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
        <UnitToggle />
        <div className="ml-auto flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <a href={driverExportUrl(ticker, selected.id, "csv")} download>
              <Download /> Export CSV
            </a>
          </Button>
          <Button asChild size="sm" variant="outline">
            <a href={driverExportUrl(ticker, selected.id, "xlsx")} download>
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
      <DriverGrid key={selected.id} ticker={ticker} scenario={selected} scale={scale} />
      <ScenarioCompare ticker={ticker} />
      <DriverImportSheet
        key={importing ? `open-${selected.id}` : "closed"}
        ticker={ticker}
        scenarioId={selected.id}
        open={importing}
        scale={scale}
        onClose={() => setImporting(false)}
      />
      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              The scenario and its drivers are removed. Base and the other scenarios stay as they
              are.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
