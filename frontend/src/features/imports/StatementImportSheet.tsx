import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import type { ImportFileIssueOut, ImportPreviewOut } from "@/api/generated/types.gen";
import {
  ImportFileFailed,
  importTemplateUrl,
  importsQueryOptions,
  useConfirmImport,
  useDeleteImport,
  usePreviewImport,
  type ImportFormat,
  type ImportScale,
} from "@/api/imports";
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
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { formatValue } from "@/lib/format";
import type { Scale } from "@/lib/scale";

const SELECT = "border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm";
const TH = "py-1 pr-3 text-left font-normal";

const FORMATS: { value: ImportFormat; label: string }[] = [
  { value: "xlsx", label: "Excel (.xlsx)" },
  { value: "csv", label: "CSV" },
];
const SCALES: { value: ImportScale; label: string }[] = [
  { value: "units", label: "Units" },
  { value: "thousands", label: "Thousands" },
  { value: "millions", label: "Millions" },
  { value: "billions", label: "Billions" },
];
const IGNORED_REASON = { sec: "SEC has a value", derived: "A formula gives another value" };

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

// "IS, row 12, column G: not a number"; the parts the API could not place are left out.
function issueText(issue: ImportFileIssueOut): string {
  const where = [
    issue.sheet,
    issue.row === null ? null : `row ${issue.row}`,
    issue.column === null ? null : `column ${issue.column}`,
  ].filter((part) => part !== null);
  return where.length === 0 ? issue.message : `${where.join(", ")}: ${issue.message}`;
}

function IssueList({ issues }: { issues: ImportFileIssueOut[] }) {
  return (
    <ul className="list-disc space-y-1 pl-4 text-xs">
      {issues.map((issue, index) => (
        <li key={`${index}-${issue.message}`}>{issueText(issue)}</li>
      ))}
    </ul>
  );
}

function Table({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="max-h-64 overflow-auto">
      <table aria-label={name} className="w-full text-xs">
        {children}
      </table>
    </div>
  );
}

function Preview({ result, scale }: { result: ImportPreviewOut; scale: Scale }) {
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap gap-x-4 text-sm">
        <span className="font-medium">{plural(result.fills.length, "cell")} would be filled</span>
        <span className="text-muted-foreground">{result.ignored.length} ignored</span>
        <span className="text-muted-foreground">{result.unchanged} unchanged</span>
      </p>
      {result.fills.length > 0 && (
        <Table name="Cells to fill">
          <thead className="text-muted-foreground">
            <tr>
              <th className={TH}>Statement</th>
              <th className={TH}>Line</th>
              <th className={TH}>Period</th>
              <th className="py-1 text-right font-normal">Value</th>
            </tr>
          </thead>
          <tbody>
            {result.fills.map((cell) => (
              <tr key={`${cell.statement}-${cell.code}-${cell.period_key}`}>
                <td className="pr-3">{cell.statement}</td>
                <td className="pr-3">{cell.label}</td>
                <td className="pr-3">{cell.period_key}</td>
                <td className="num">{formatValue(cell.value, cell.unit, scale)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {result.ignored.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-muted-foreground text-xs">
            Left as they are: {plural(result.ignored.length, "typed value")} not stored
          </h3>
          <Table name="Ignored cells">
            <thead className="text-muted-foreground">
              <tr>
                <th className={TH}>Line</th>
                <th className={TH}>Period</th>
                <th className="py-1 pr-3 text-right font-normal">Shown</th>
                <th className="py-1 pr-3 text-right font-normal">File</th>
                <th className="py-1 text-left font-normal">Why</th>
              </tr>
            </thead>
            <tbody>
              {result.ignored.map((cell) => (
                <tr key={`${cell.statement}-${cell.code}-${cell.period_key}`}>
                  <td className="pr-3">{cell.label}</td>
                  <td className="pr-3">{cell.period_key}</td>
                  <td className="num pr-3">{formatValue(cell.existing_value, cell.unit, scale)}</td>
                  <td className="num pr-3">{formatValue(cell.imported_value, cell.unit, scale)}</td>
                  <td>{IGNORED_REASON[cell.reason]}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      {result.lines.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-muted-foreground text-xs">Custom lines created</h3>
          <ul className="list-disc space-y-1 pl-4 text-xs">
            {result.lines.map((line) => (
              <li key={line.code}>
                {`${line.label} under ${line.parent_label} (${line.statement})`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {result.built.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-muted-foreground text-xs">
            Parents filled from a complete breakdown
          </h3>
          <Table name="Parents built from custom lines">
            <tbody>
              {result.built.map((cell) => (
                <tr key={`${cell.statement}-${cell.code}-${cell.period_key}`}>
                  <td className="pr-3">{cell.label}</td>
                  <td className="pr-3">{cell.period_key}</td>
                  <td className="num">{formatValue(cell.value, cell.unit, scale)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      {result.warnings.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-muted-foreground text-xs">Warnings</h3>
          <IssueList issues={result.warnings} />
        </div>
      )}
    </div>
  );
}

function History({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(importsQueryOptions(ticker));
  const remove = useDeleteImport(ticker);
  const [toDelete, setToDelete] = useState<{ id: number; filename: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <section className="space-y-2 px-4 pb-4">
      <h3 className="text-sm font-medium">History</h3>
      {isPending && <p className="text-muted-foreground text-xs">Loading…</p>}
      {isError && <p className="text-destructive text-xs">Could not load the imports.</p>}
      {data?.length === 0 && <p className="text-muted-foreground text-xs">No imports yet.</p>}
      {data && data.length > 0 && (
        <Table name="Import history">
          <thead className="text-muted-foreground">
            <tr>
              <th className={TH}>File</th>
              <th className={TH}>Imported</th>
              <th className={TH}>Scale</th>
              <th className="py-1 text-right font-normal">Cells</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.id}>
                <td className="pr-3">{item.filename}</td>
                <td className="pr-3 whitespace-nowrap">{item.imported_at.slice(0, 10)}</td>
                <td className="pr-3">{item.scale}</td>
                <td className="num">{plural(item.cells, "cell")}</td>
                <td className="text-right">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Delete ${item.filename}`}
                    onClick={() => {
                      setError(null);
                      setToDelete({ id: item.id, filename: item.filename });
                    }}
                  >
                    <Trash2 />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {toDelete?.filename}?</AlertDialogTitle>
            <AlertDialogDescription>
              Its values and custom lines are removed, and the cells fall back to SEC data or an
              earlier import.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) {
                  remove.mutate(toDelete.id, {
                    onError: (e) =>
                      setError(companyErrorMessage(e, "Could not delete the import.")),
                  });
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

interface StatementImportSheetProps {
  ticker: string;
  open: boolean;
  scale: Scale; // the page scale, used to show the values of the preview
  onClose: () => void;
}

/**
 * Fill the company's statements from Excel or CSV: download the template, upload it, review
 * what would change (SEC values are never replaced), confirm, and manage the history.
 */
export function StatementImportSheet({ ticker, open, scale, onClose }: StatementImportSheetProps) {
  const previewImport = usePreviewImport(ticker);
  const confirmImport = useConfirmImport(ticker);
  const [format, setFormat] = useState<ImportFormat>("xlsx");
  const [prefill, setPrefill] = useState(false);
  const [importScale, setImportScale] = useState<ImportScale>("millions");
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0); // remounts the file input to clear it
  const [result, setResult] = useState<ImportPreviewOut | null>(null);
  const [issues, setIssues] = useState<ImportFileIssueOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function reset() {
    setResult(null);
    setIssues([]);
    setError(null);
    setMessage(null);
  }

  function failed(e: Error, fallback: string) {
    if (e instanceof ImportFileFailed && e.issues.length > 0) setIssues(e.issues);
    else setError(companyErrorMessage(e, fallback));
  }

  function preview(event: React.FormEvent) {
    event.preventDefault();
    reset();
    if (!file) return setError("Choose a file first");
    previewImport.mutate(
      { file, scale: importScale },
      {
        onSuccess: setResult,
        onError: (e) => failed(e, "Could not read the file."),
      },
    );
  }

  function confirm() {
    if (!file) return;
    setError(null);
    confirmImport.mutate(
      { file, scale: importScale },
      {
        onSuccess: (done) => {
          reset();
          setFile(null);
          setFileKey((key) => key + 1);
          setMessage(
            done.import_id === null
              ? "Nothing was stored."
              : `Imported ${plural(done.fills.length, "cell")}.`,
          );
        },
        onError: (e) => failed(e, "Could not import the file."),
      },
    );
  }

  const changes = result !== null && (result.fills.length > 0 || result.lines.length > 0);

  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>Import statements</SheetTitle>
          <SheetDescription>
            Fill the gaps SEC leaves, or a whole manual company, from Excel or CSV. A typed value
            never replaces an SEC value.
          </SheetDescription>
        </SheetHeader>
        <section className="space-y-3 px-4 pb-4">
          <h3 className="text-sm font-medium">1. Template</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="import-format">Format</Label>
              <select
                id="import-format"
                value={format}
                onChange={(e) => setFormat(e.target.value as ImportFormat)}
                className={SELECT}
              >
                {FORMATS.map((option) => (
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
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={prefill}
              onChange={(e) => setPrefill(e.target.checked)}
            />
            Prefill with current values
          </label>
          <Button asChild variant="outline" size="sm">
            <a href={importTemplateUrl(ticker, { format, prefill, scale: importScale })} download>
              Download template
            </a>
          </Button>
          <p className="text-muted-foreground text-xs">
            The template lists 20 fiscal years, each as FY and Q1 to Q4: fill the columns you have.
            Set fiscal_year_end once (the date your annual period ends, on the Instructions sheet)
            and every column&apos;s dates follow from it. The scale applies to USD amounts and share
            counts, never to per-share values. Add a custom line by listing a new row with a parent;
            mark the parent row children_complete to build it from its lines.
          </p>
        </section>
        <form onSubmit={preview} className="space-y-3 px-4 pb-4" noValidate>
          <h3 className="text-sm font-medium">2. Upload and review</h3>
          <div className="space-y-1">
            <Label htmlFor="import-file">File</Label>
            <input
              key={fileKey}
              id="import-file"
              type="file"
              accept=".xlsx,.csv,.tsv,.txt"
              onChange={(e) => {
                reset();
                setFile(e.target.files?.[0] ?? null);
              }}
              className="text-sm"
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
          {issues.length > 0 && (
            <div role="alert" className="text-destructive space-y-1">
              <p className="text-xs font-medium">The file was not imported:</p>
              <IssueList issues={issues} />
            </div>
          )}
          {message && <p className="text-positive text-xs">{message}</p>}
          {result && <Preview result={result} scale={scale} />}
          {result && !changes && (
            <p className="text-muted-foreground text-xs">
              Nothing to import: the file changes no cell.
            </p>
          )}
          {changes && (
            <Button type="button" size="sm" disabled={confirmImport.isPending} onClick={confirm}>
              {`Import ${plural(result.fills.length, "cell")}`}
            </Button>
          )}
        </form>
        <History ticker={ticker} />
      </SheetContent>
    </Sheet>
  );
}
