import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { ImportFailed, useImportSegments } from "@/api/context";
import type { ImportIssueOut, SegmentImportIn, SegmentImportOut } from "@/api/generated/types.gen";
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

type Dimension = SegmentImportIn["dimension"];
type ImportScale = SegmentImportIn["scale"];

const SELECT = "border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm";

const DIMENSIONS: { value: Dimension; label: string }[] = [
  { value: "business", label: "Business segments" },
  { value: "geo", label: "Geographic segments" },
  { value: "kpi", label: "KPIs" },
];
const SCALES: { value: ImportScale; label: string }[] = [
  { value: "units", label: "Units" },
  { value: "K", label: "Thousands (K)" },
  { value: "M", label: "Millions (M)" },
  { value: "B", label: "Billions (B)" },
];

// The header cells of the pasted text (comma or tab separated), to name a column in an error.
function headerCells(text: string): string[] {
  const header = text.replace(/^﻿/, "").split(/\r?\n/, 1)[0] ?? "";
  const delimiter = header.includes("\t") ? "\t" : ",";
  return header.split(delimiter).map((cell) => cell.trim().replace(/^"(.*)"$/, "$1"));
}

function issueText(issue: ImportIssueOut, header: string[]): string {
  if (issue.column === null) return `row ${issue.row}: ${issue.message}`;
  const name = header[issue.column - 1];
  return `row ${issue.row}, ${name ? name : `column ${issue.column}`}: ${issue.message}`;
}

interface ImportSheetProps {
  ticker: string;
  open: boolean;
  scale: Scale; // the page scale, the default import scale
  onClose: () => void;
}

/** Paste or choose a CSV/TSV of segment or KPI series; an invalid file lists every error. */
export function ImportSheet({ ticker, open, scale, onClose }: ImportSheetProps) {
  const importSegments = useImportSegments(ticker);
  const [dimension, setDimension] = useState<Dimension>("geo");
  const [importScale, setImportScale] = useState<ImportScale>(scale);
  const [text, setText] = useState("");
  const [issues, setIssues] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setIssues([]);
    setMessage(null);
    if (text.trim() === "") return setError("Paste or choose a CSV or TSV first");
    setError(null);
    importSegments.mutate(
      { dimension, scale: importScale, text },
      {
        onSuccess: (done: SegmentImportOut) =>
          setMessage(
            `${done.series_created} series created, ${done.values_created} values created, ` +
              `${done.values_updated} values updated.`,
          ),
        onError: (e) => {
          if (e instanceof ImportFailed) {
            const header = headerCells(text);
            setIssues(e.issues.map((issue) => issueText(issue, header)));
          } else {
            setError(companyErrorMessage(e, "Could not import the file."));
          }
        },
      },
    );
  }

  async function chooseFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) setText(await file.text());
  }

  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Import segments or KPIs</SheetTitle>
          <SheetDescription>
            Header: name,metric,unit, then one column per period written FY2024 or Q1 FY2024 (the
            grid shows FY24). A blank cell keeps the stored value. USD values are multiplied by the
            scale; a percent is typed as 5.2 or 5.2%.
          </SheetDescription>
        </SheetHeader>
        <form onSubmit={submit} className="space-y-3 px-4 pb-4" noValidate>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="import-dimension">Dimension</Label>
              <select
                id="import-dimension"
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
            <div className="space-y-1">
              <Label htmlFor="import-scale">Scale</Label>
              <select
                id="import-scale"
                value={importScale}
                onChange={(e) => setImportScale(e.target.value as ImportScale)}
                className={SELECT}
              >
                {SCALES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="import-file">File</Label>
            <input
              id="import-file"
              type="file"
              accept=".csv,.tsv,.txt"
              onChange={chooseFile}
              className="text-sm"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="import-text">CSV or TSV</Label>
            <textarea
              id="import-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={8}
              spellCheck={false}
              className="border-input w-full rounded-lg border bg-transparent p-2 font-mono text-xs"
            />
          </div>
          {error && (
            <p role="alert" className="text-destructive text-xs">
              {error}
            </p>
          )}
          {issues.length > 0 && (
            <ul role="alert" className="text-destructive list-disc space-y-1 pl-4 text-xs">
              {issues.map((issue, index) => (
                <li key={`${index}-${issue}`}>{issue}</li>
              ))}
            </ul>
          )}
          {message && <p className="text-positive text-xs">{message}</p>}
          <Button type="submit" size="sm" disabled={importSegments.isPending}>
            Import
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}
