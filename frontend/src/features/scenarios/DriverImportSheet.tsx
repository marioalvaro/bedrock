import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import type {
  DriverChangeOut,
  DriverFileIssueOut,
  DriverImportOut,
  DriverRowOut,
} from "@/api/generated/types.gen";
import {
  DriverFileFailed,
  driversQueryOptions,
  useConfirmDriverImport,
  usePreviewDriverImport,
  type ScenarioCase,
} from "@/api/scenarios";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { Scale } from "@/lib/scale";

import { forecastLabel, formatDriverOffset, formatDriverValue } from "./driverCells";

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

// "row 3, column F: not a number"; the parts the API could not place are left out.
function issueText(issue: DriverFileIssueOut): string {
  const where = [
    issue.row === null ? null : `row ${issue.row}`,
    issue.column === null ? null : `column ${issue.column}`,
  ].filter((part) => part !== null);
  return where.length === 0 ? issue.message : `${where.join(", ")}: ${issue.message}`;
}

// One side of a change: an offset as an offset, a value by the driver's unit, none as "—".
function side(
  value: string | null,
  kind: DriverChangeOut["old_kind"],
  driver: DriverRowOut | undefined,
  scale: Scale,
): string {
  if (value === null) return "—";
  if (!driver) return value; // a driver the grid no longer lists: the plain number
  return kind === "offset"
    ? formatDriverOffset(value, driver.unit, scale)
    : formatDriverValue(value, driver.unit, scale);
}

// "Revenue growth · FY27: 5.0% → 8.0%", "… → cleared" for a removed value.
function changeText(change: DriverChangeOut, driver: DriverRowOut | undefined, scale: Scale) {
  const label = driver?.label ?? change.driver_code;
  const year = forecastLabel(change.fiscal_year).slice(0, -1);
  const after = change.new === null ? "cleared" : side(change.new, change.new_kind, driver, scale);
  return `${label} · ${year}: ${side(change.old, change.old_kind, driver, scale)} → ${after}`;
}

interface DriverImportSheetProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase;
  open: boolean;
  scale: Scale; // the page scale, used to show USD values
  onClose: () => void;
}

/**
 * Import a case's drivers from a CSV or Excel file (the export's layout): preview what would
 * change, then apply it. A driver absent from the file is untouched.
 */
export function DriverImportSheet({
  ticker,
  scenarioId,
  scenarioCase,
  open,
  scale,
  onClose,
}: DriverImportSheetProps) {
  const { data: grid } = useQuery(driversQueryOptions(ticker, scenarioId, scenarioCase));
  const previewImport = usePreviewDriverImport(ticker);
  const confirmImport = useConfirmDriverImport(ticker);
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0); // remounts the file input to clear it
  const [result, setResult] = useState<DriverImportOut | null>(null);
  const [issues, setIssues] = useState<DriverFileIssueOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const driverOf = (code: string) => grid?.rows.find((row) => row.code === code);

  function reset() {
    setResult(null);
    setIssues([]);
    setError(null);
    setMessage(null);
  }

  function failed(e: Error, fallback: string) {
    if (e instanceof DriverFileFailed && e.issues.length > 0) setIssues(e.issues);
    else setError(companyErrorMessage(e, fallback));
  }

  function preview(event: React.FormEvent) {
    event.preventDefault();
    reset();
    if (!file) return setError("Choose a file first");
    previewImport.mutate(
      { id: scenarioId, case: scenarioCase, file },
      { onSuccess: setResult, onError: (e) => failed(e, "Could not read the file.") },
    );
  }

  function apply() {
    if (!file) return;
    setError(null);
    confirmImport.mutate(
      { id: scenarioId, case: scenarioCase, file },
      {
        onSuccess: (done) => {
          reset();
          setFile(null);
          setFileKey((key) => key + 1);
          setMessage(`Applied ${plural(done.changes.length, "change")}.`);
        },
        onError: (e) => failed(e, "Could not import the file."),
      },
    );
  }

  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>Import drivers</SheetTitle>
          <SheetDescription>
            Upload a driver file in the export&apos;s layout (CSV or Excel). Each row replaces that
            driver&apos;s own values in the file&apos;s years; a blank row clears it.
          </SheetDescription>
        </SheetHeader>
        <form onSubmit={preview} className="space-y-3 px-4 pb-4" noValidate>
          <div className="space-y-1">
            <Label htmlFor="driver-file">Driver file</Label>
            <input
              key={fileKey}
              id="driver-file"
              type="file"
              accept=".csv,.xlsx"
              className="block w-full text-sm"
              onChange={(e) => {
                reset();
                setFile(e.target.files?.[0] ?? null);
              }}
            />
          </div>
          <Button type="submit" size="sm" variant="outline" disabled={previewImport.isPending}>
            Preview
          </Button>
          {error && (
            <p role="alert" className="text-destructive text-xs">
              {error}
            </p>
          )}
          {message && (
            <p role="status" className="text-muted-foreground text-xs">
              {message}
            </p>
          )}
          {issues.length > 0 && (
            <ul aria-label="Errors" className="text-destructive list-disc space-y-1 pl-4 text-xs">
              {issues.map((issue, index) => (
                <li key={`${index}-${issue.message}`}>{issueText(issue)}</li>
              ))}
            </ul>
          )}
          {result && result.changes.length === 0 && (
            <p className="text-muted-foreground text-sm">Nothing to change</p>
          )}
          {result && result.changes.length > 0 && (
            <>
              <ul aria-label="Changes" className="list-disc space-y-1 pl-4 text-xs">
                {result.changes.map((change) => (
                  <li key={`${change.driver_code}-${change.fiscal_year}`} className="num">
                    {changeText(change, driverOf(change.driver_code), scale)}
                  </li>
                ))}
              </ul>
              <Button type="button" size="sm" disabled={confirmImport.isPending} onClick={apply}>
                Apply {plural(result.changes.length, "change")}
              </Button>
            </>
          )}
        </form>
      </SheetContent>
    </Sheet>
  );
}
