import { useQuery } from "@tanstack/react-query";
import { Archive } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import {
  archivedCompaniesQueryOptions,
  companiesQueryOptions,
  companyErrorMessage,
  deletionImpactQueryOptions,
  useAddCompany,
  useAddManualCompany,
  useArchiveCompany,
  useRemoveCompany,
  useRestoreCompany,
} from "@/api/companies";
import type { CompanyListItem, DeletionImpactOut } from "@/api/generated/types.gen";
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
import { NewFilingMark } from "@/features/filings/NewFilingMark";
import {
  formatCompact,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatRelative,
} from "@/lib/format";
import { useNow } from "@/lib/now";

function AddCompanyForm({ onError }: { onError: (message: string | null) => void }) {
  const [ticker, setTicker] = useState("");
  const add = useAddCompany();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ticker.trim()) return;
    onError(null);
    add.mutate(ticker, {
      onSuccess: () => setTicker(""),
      onError: (error) => onError(companyErrorMessage(error, "Could not add the company.")),
    });
  }

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <Input
        aria-label="Ticker"
        placeholder="Ticker, e.g. AAPL"
        className="w-40"
        value={ticker}
        onChange={(event) => setTicker(event.target.value)}
        disabled={add.isPending}
      />
      <Button type="submit" size="sm" disabled={add.isPending}>
        {add.isPending ? "Adding…" : "Add"}
      </Button>
    </form>
  );
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// A company SEC does not cover: its statements come from an import, so it needs only a name and
// the month its fiscal year ends in.
function ManualCompanyForm({ onDone }: { onDone: () => void }) {
  const add = useAddManualCompany();
  const [ticker, setTicker] = useState("");
  const [name, setName] = useState("");
  const [month, setMonth] = useState(12);
  const [sic, setSic] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) return setError("Enter a ticker");
    if (!name.trim()) return setError("Enter a name");
    if (sic.trim() && !/^\d{4}$/.test(sic.trim())) return setError("SIC must be 4 digits");
    setError(null);
    add.mutate(
      {
        ticker: symbol,
        name: name.trim(),
        fiscal_year_end_month: month,
        ...(sic.trim() ? { sic: sic.trim() } : {}),
      },
      {
        onSuccess: onDone,
        onError: (e) => setError(companyErrorMessage(e, "Could not create the company.")),
      },
    );
  }

  return (
    <form
      aria-label="Add manual company"
      onSubmit={submit}
      noValidate
      className="border-border grid gap-3 border-b px-4 py-3 sm:grid-cols-[8rem_1fr_10rem_8rem_auto] sm:items-end"
    >
      <div className="space-y-1">
        <Label htmlFor="manual-ticker">Ticker</Label>
        <Input id="manual-ticker" value={ticker} onChange={(e) => setTicker(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="manual-name">Name</Label>
        <Input id="manual-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="manual-month">Fiscal year ends</Label>
        <select
          id="manual-month"
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm"
        >
          {MONTHS.map((label, index) => (
            <option key={label} value={index + 1}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="manual-sic">SIC (optional)</Label>
        <Input
          id="manual-sic"
          inputMode="numeric"
          value={sic}
          onChange={(e) => setSic(e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={add.isPending}>
          Create
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-sm sm:col-span-full">
          {error}
        </p>
      )}
    </form>
  );
}

type CountName = Exclude<keyof DeletionImpactOut, "ticker">;

// What a permanent delete removes, in the dialog's order, as [one, many].
const IMPACT_WORDS: [CountName, string, string][] = [
  ["filings", "filing", "filings"],
  ["facts", "fact", "facts"],
  ["notes", "note", "notes"],
  ["scenarios", "scenario", "scenarios"],
  ["snapshots", "snapshot", "snapshots"],
  ["guidance", "guidance item", "guidance items"],
  ["adjustments", "adjustment", "adjustments"],
  ["checkpoints", "checkpoint", "checkpoints"],
  ["comps_sets", "comps set", "comps sets"],
  ["imports", "import", "imports"],
];

/** "12 filings, 48,210 facts, 7 notes": every count that is not zero; null when all are. */
function impactText(impact: DeletionImpactOut): string | null {
  const parts = IMPACT_WORDS.filter(([name]) => impact[name] > 0).map(
    ([name, one, many]) =>
      `${impact[name].toLocaleString("en-US")} ${impact[name] === 1 ? one : many}`,
  );
  return parts.length > 0 ? parts.join(", ") : null;
}

// The second of the two deliberate steps (FR-WS-07): names what is lost and asks for the ticker.
// Mounted per opening, so the typed confirmation starts empty each time. The delete itself runs in
// the parent: the dialog unmounts as it closes, and a mutation's callbacks die with it.
function DeleteDialog({
  ticker,
  onClose,
  onConfirm,
}: {
  ticker: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { data, isPending, isError } = useQuery(deletionImpactQueryOptions(ticker));
  const [typed, setTyped] = useState("");
  const counts = data ? impactText(data) : null;

  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {ticker} permanently?</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="flex flex-col gap-1">
              {isPending && <p>Loading…</p>}
              {isError && <p>Could not load what would be deleted.</p>}
              {data && <p>{counts ?? `Nothing else is stored for ${ticker}.`}</p>}
              <p>This cannot be undone.</p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <Input
          aria-label={`Type ${ticker} to confirm`}
          placeholder={ticker}
          autoComplete="off"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
        />
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={!data || typed !== ticker}
            onClick={onConfirm}
          >
            Delete permanently
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function ArchivedCompanies({
  onError,
  onGone,
}: {
  onError: (message: string | null) => void;
  onGone: (ticker: string) => void; // restored or deleted: no longer archived
}) {
  const { data: archived, isError } = useQuery(archivedCompaniesQueryOptions);
  const restore = useRestoreCompany();
  const remove = useRemoveCompany();
  const [open, setOpen] = useState(false);
  const [toDelete, setToDelete] = useState<string | null>(null);

  function deleteCompany(ticker: string) {
    onError(null);
    remove.mutate(ticker, {
      onSuccess: () => onGone(ticker),
      onError: (e) => onError(companyErrorMessage(e, `Could not delete ${ticker}.`)),
    });
  }
  const now = useNow();

  if (isError) {
    return (
      <p className="text-destructive px-4 py-2 text-sm">Could not load the archived companies.</p>
    );
  }
  if (!archived || archived.length === 0) return null;
  return (
    <div className="border-border border-b">
      <Button
        variant="ghost"
        size="sm"
        className="mx-2 my-1"
        aria-expanded={open}
        onClick={() => setOpen((shown) => !shown)}
      >
        Archived ({archived.length})
      </Button>
      {open && (
        <div className="overflow-x-auto">
          <table aria-label="Archived companies" className="w-full text-sm">
            <thead className="text-muted-foreground text-xs">
              <tr className="border-border border-b">
                <th className="px-4 py-1.5 text-left font-normal">Ticker</th>
                <th className="px-2 py-1.5 text-left font-normal">Name</th>
                <th className="num px-2 py-1.5 font-normal">Archived</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {archived.map((company) => (
                <tr key={company.id} className="border-border text-muted-foreground border-b">
                  <td className="px-4 py-1.5 font-medium">
                    <Link
                      to={`/c/${company.ticker}`}
                      className="underline-offset-2 hover:underline"
                    >
                      {company.ticker}
                    </Link>
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">{company.name}</td>
                  <td className="num px-2 py-1.5 whitespace-nowrap">
                    {formatRelative(company.archived_at, now)}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className="flex justify-end gap-2">
                      <Button
                        size="xs"
                        variant="outline"
                        aria-label={`Restore ${company.ticker}`}
                        disabled={restore.isPending}
                        onClick={() => {
                          onError(null);
                          restore.mutate(company.ticker, {
                            onSuccess: () => onGone(company.ticker),
                            onError: (e) =>
                              onError(
                                companyErrorMessage(e, `Could not restore ${company.ticker}.`),
                              ),
                          });
                        }}
                      >
                        Restore
                      </Button>
                      <Button
                        size="xs"
                        variant="destructive"
                        aria-label={`Delete ${company.ticker} permanently…`}
                        onClick={() => setToDelete(company.ticker)}
                      >
                        Delete permanently…
                      </Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {toDelete && (
        <DeleteDialog
          ticker={toDelete}
          onClose={() => setToDelete(null)}
          onConfirm={() => deleteCompany(toDelete)}
        />
      )}
    </div>
  );
}

export function Companies() {
  const { data: companies, isError } = useQuery(companiesQueryOptions);
  const [error, setError] = useState<string | null>(null);
  // The company just archived, offered back with Undo until it is restored or another is archived.
  const [archivedTicker, setArchivedTicker] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const archive = useArchiveCompany();
  const restore = useRestoreCompany();
  const now = useNow();

  function archiveCompany(company: CompanyListItem) {
    setError(null);
    archive.mutate(company.ticker, {
      onSuccess: () => setArchivedTicker(company.ticker),
      onError: (e) => setError(companyErrorMessage(e, `Could not archive ${company.ticker}.`)),
    });
  }

  function undoArchive(ticker: string) {
    setError(null);
    restore.mutate(ticker, {
      onSuccess: () => setArchivedTicker(null),
      onError: (e) => setError(companyErrorMessage(e, `Could not restore ${ticker}.`)),
    });
  }

  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-3 border-b px-4 py-2">
        <AddCompanyForm onError={setError} />
        <Button type="button" size="sm" variant="outline" onClick={() => setManualOpen(true)}>
          Add manual company
        </Button>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
      </div>
      {manualOpen && <ManualCompanyForm onDone={() => setManualOpen(false)} />}
      {archivedTicker && (
        <p className="border-border flex items-center gap-1 border-b px-4 py-1.5 text-sm">
          <span className="text-muted-foreground">Archived {archivedTicker}.</span>
          <Button
            variant="link"
            size="xs"
            disabled={restore.isPending}
            onClick={() => undoArchive(archivedTicker)}
          >
            Undo
          </Button>
        </p>
      )}
      {isError && <p className="text-destructive p-4 text-sm">Could not load companies.</p>}
      {companies?.length === 0 && (
        <p className="text-muted-foreground p-4 text-sm">No companies yet. Add a ticker above.</p>
      )}
      {companies && companies.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted-foreground text-xs">
              <tr className="border-border border-b">
                <th className="px-4 py-1.5 text-left font-normal">Ticker</th>
                <th className="px-2 py-1.5 text-left font-normal">Name</th>
                <th className="num px-2 py-1.5 font-normal">Price</th>
                <th className="num px-2 py-1.5 font-normal">Mkt cap</th>
                <th className="num px-2 py-1.5 font-normal">P/E</th>
                <th className="num px-2 py-1.5 font-normal">EV/EBITDA</th>
                <th className="num px-2 py-1.5 font-normal">Rev. growth</th>
                <th className="num px-2 py-1.5 font-normal">Refreshed</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => (
                <tr key={company.id} className="border-border hover:bg-muted border-b">
                  <td className="px-4 py-1.5 font-medium">
                    <Link
                      to={`/c/${company.ticker}`}
                      className="underline-offset-2 hover:underline"
                    >
                      {company.ticker}
                    </Link>
                    {company.source === "manual" && (
                      <span className="text-muted-foreground ml-2 text-xs font-normal">manual</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <div>{company.name}</div>
                    <NewFilingMark filings={company.new_filings} />
                  </td>
                  <td className="num px-2 py-1.5">{formatPrice(company.price)}</td>
                  <td className="num px-2 py-1.5">{formatCompact(company.market_cap)}</td>
                  <td className="num px-2 py-1.5">{formatMultiple(company.pe)}</td>
                  <td className="num px-2 py-1.5">{formatMultiple(company.ev_ebitda)}</td>
                  <td className="num px-2 py-1.5">{formatPercent(company.revenue_growth)}</td>
                  <td className="num text-muted-foreground px-2 py-1.5 whitespace-nowrap">
                    {formatRelative(company.last_refreshed_at, now)}
                  </td>
                  <td className="px-2 py-1.5">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Archive ${company.ticker}`}
                      title="Archive"
                      disabled={archive.isPending}
                      onClick={() => archiveCompany(company)}
                    >
                      <Archive />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ArchivedCompanies
        onError={setError}
        onGone={(ticker) => setArchivedTicker((shown) => (shown === ticker ? null : shown))}
      />
    </div>
  );
}
