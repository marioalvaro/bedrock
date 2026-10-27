import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import {
  companiesQueryOptions,
  companyErrorMessage,
  useAddCompany,
  useAddManualCompany,
  useRemoveCompany,
} from "@/api/companies";
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

export function Companies() {
  const { data: companies, isPending, isError } = useQuery(companiesQueryOptions);
  const [error, setError] = useState<string | null>(null);
  const [toRemove, setToRemove] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const remove = useRemoveCompany();
  const now = useNow();

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
      {isPending && null}
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
                  <td className="px-2 py-1.5 whitespace-nowrap">{company.name}</td>
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
                      aria-label={`Remove ${company.ticker}`}
                      onClick={() => setToRemove(company.ticker)}
                    >
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AlertDialog open={toRemove !== null} onOpenChange={(open) => !open && setToRemove(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {toRemove}?</AlertDialogTitle>
            <AlertDialogDescription>
              Its filings, facts and prices are deleted. You can add it again later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toRemove) {
                  setError(null);
                  remove.mutate(toRemove, {
                    onError: (e) =>
                      setError(companyErrorMessage(e, `Could not remove ${toRemove}.`)),
                  });
                }
              }}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
