import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useCreateAdjustment, useDeleteAdjustment, useUpdateAdjustment } from "@/api/adjustments";
import { companyErrorMessage } from "@/api/companies";
import type { AdjustmentIn, CellAdjustmentOut } from "@/api/generated/types.gen";
import { cellDetailQueryOptions } from "@/api/statements";
import type { FiscalPeriod } from "@/api/context";
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
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  formatFiscalPeriod,
  formatValue,
  parseScaled,
  scaleLabel,
  toScaledText,
} from "@/lib/format";
import type { Scale } from "@/lib/scale";
import { NotesPanel } from "@/features/notes/NotesPanel";

export interface CellTarget {
  code: string;
  label: string;
  unit: string;
  adjustable: boolean; // the row takes adjustments (the API's `adjustable`)
  fiscalYear: number;
  fiscalPeriod: string;
}

interface CellDetailSheetProps {
  ticker: string;
  cik: string | null;
  target: CellTarget | null;
  scale: Scale;
  onClose: () => void;
}

function filingUrl(cik: string, accessionNo: string): string {
  return `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${accessionNo.replaceAll("-", "")}/`;
}

function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="border-border border-b py-2">
      <div className="text-muted-foreground text-xs">{name}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

// What a rule-produced value is. A reported, derived or normalized cell needs no extra words: its
// derivation and vintages say it all.
const RULE_NOTES: Record<string, { name: string; text: string }> = {
  zero_inferred: {
    name: "inferred zero",
    text: "Inferred zero: the filing does not report this line, and a rule concluded it is exactly 0.",
  },
  approximated: {
    name: "approximated",
    text: "Approximated: rebuilt by a rule (a Q4 average or the cover-page share count), not reported. Backtests never score against it.",
  },
};

const CATEGORIES: AdjustmentIn["category"][] = ["one-off", "restatement", "reclass", "other"];
const PERIODS: readonly string[] = ["FY", "Q1", "Q2", "Q3", "Q4"];

function AdjustmentForm({
  ticker,
  target,
  scale,
  editing,
  onDone,
}: {
  ticker: string;
  target: CellTarget;
  scale: Scale;
  editing: CellAdjustmentOut | null;
  onDone: () => void;
}) {
  const create = useCreateAdjustment(ticker);
  const update = useUpdateAdjustment(ticker);
  const [amount, setAmount] = useState(editing ? toScaledText(editing.amount, scale) : "");
  const [category, setCategory] = useState<AdjustmentIn["category"]>(
    editing ? (editing.category as AdjustmentIn["category"]) : "one-off",
  );
  const [reason, setReason] = useState(editing?.reason ?? "");
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const units = parseScaled(amount, scale);
    if (units === null) return setError("Enter a number");
    if (reason.trim() === "") return setError("Enter a reason");
    setError(null);
    // An edit keeps the adjustment's own cell: one listed here may belong to a paired period
    // (a Q2 flow adjustment also shows in FY; an FY instant one also shows in Q4).
    const cell = editing
      ? {
          code: editing.canonical_code,
          year: editing.fiscal_year,
          period: editing.fiscal_period,
        }
      : { code: target.code, year: target.fiscalYear, period: target.fiscalPeriod };
    const body: AdjustmentIn = {
      canonical_code: cell.code,
      fiscal_year: cell.year,
      fiscal_period: cell.period as AdjustmentIn["fiscal_period"],
      amount: units,
      category,
      reason: reason.trim(),
    };
    const options = {
      onSuccess: onDone,
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the adjustment.")),
    };
    if (editing) update.mutate({ id: editing.id, body }, options);
    else create.mutate(body, options);
  }

  return (
    <form onSubmit={submit} className="mt-2 space-y-2" noValidate>
      <div className="space-y-1">
        <Label htmlFor="adjustment-amount">Amount ({scaleLabel("USD", scale)})</Label>
        <Input
          id="adjustment-amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          inputMode="decimal"
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="adjustment-category">Category</Label>
        <select
          id="adjustment-category"
          value={category}
          onChange={(e) => setCategory(e.target.value as AdjustmentIn["category"])}
          className="border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="adjustment-reason">Reason</Label>
        <Input id="adjustment-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
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

function Adjustments({
  ticker,
  target,
  scale,
  adjustments,
}: {
  ticker: string;
  target: CellTarget;
  scale: Scale;
  adjustments: CellAdjustmentOut[];
}) {
  const remove = useDeleteAdjustment(ticker);
  // `null` closed, "new" adding, otherwise the adjustment being edited.
  const [form, setForm] = useState<CellAdjustmentOut | "new" | null>(null);
  const [toDelete, setToDelete] = useState<CellAdjustmentOut | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const canAdd = target.adjustable && PERIODS.includes(target.fiscalPeriod);

  return (
    <>
      {adjustments.length === 0 ? (
        <span className="text-muted-foreground">Adjustments: none</span>
      ) : (
        <ul className="space-y-1">
          {adjustments.map((a) => (
            <li key={a.id}>
              {formatFiscalPeriod(a.fiscal_year, a.fiscal_period)} · {a.category} ·{" "}
              <span className="num">{formatValue(a.amount, "USD", scale)}</span>: {a.reason}
              {a.via !== null && <span className="text-muted-foreground"> via {a.label}</span>}
              {a.via === null && (
                <span className="ml-2 inline-flex gap-1">
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    aria-label={`Edit adjustment ${a.reason}`}
                    onClick={() => setForm(a)}
                  >
                    Edit
                  </Button>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    aria-label={`Delete adjustment ${a.reason}`}
                    onClick={() => {
                      setDeleteError(null);
                      setToDelete(a);
                    }}
                  >
                    Delete
                  </Button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {deleteError && (
        <p role="alert" className="text-destructive text-xs">
          {deleteError}
        </p>
      )}
      {form !== null ? (
        <AdjustmentForm
          key={form === "new" ? "new" : form.id}
          ticker={ticker}
          target={target}
          scale={scale}
          editing={form === "new" ? null : form}
          onDone={() => setForm(null)}
        />
      ) : (
        canAdd && (
          <div className="mt-2">
            <Button type="button" size="sm" variant="outline" onClick={() => setForm("new")}>
              Add adjustment
            </Button>
          </div>
        )
      )}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this adjustment?</AlertDialogTitle>
            <AlertDialogDescription>{toDelete?.reason}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) {
                  remove.mutate(toDelete.id, {
                    onError: (e) =>
                      setDeleteError(companyErrorMessage(e, "Could not delete the adjustment.")),
                  });
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function Body({
  ticker,
  cik,
  target,
  scale,
}: Omit<CellDetailSheetProps, "onClose"> & { target: CellTarget }) {
  const { data, isPending, isError } = useQuery(
    cellDetailQueryOptions(ticker, target.code, target.fiscalYear, target.fiscalPeriod),
  );

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (isError)
    return <p className="text-destructive p-4 text-sm">Could not load the cell details.</p>;

  const money = (value: string) => formatValue(value, target.unit, scale);

  return (
    <div className="overflow-y-auto px-4 pb-4">
      <Field name="Value">
        <span className="num">{data.value === null ? "—" : money(data.value)}</span>{" "}
        <span className="text-muted-foreground">
          ({(data.provenance && RULE_NOTES[data.provenance]?.name) || data.provenance || "no value"}
          )
        </span>
        {data.normalized_value !== null && (
          <>
            {" "}
            <span className="prov-normalized">
              Normalized <span className="num">{money(data.normalized_value)}</span>
            </span>
          </>
        )}
      </Field>
      {data.source && (
        <Field name="Source tag">
          <code className="break-all">
            {data.source.taxonomy}:{data.source.concept}
          </code>{" "}
          <span className="text-muted-foreground">({data.source.unit})</span>
        </Field>
      )}
      {data.filing && (
        <Field name="Filing">
          {data.filing.form}{" "}
          {cik === null ? (
            data.filing.accession_no
          ) : (
            <a
              className="underline"
              href={filingUrl(cik, data.filing.accession_no)}
              target="_blank"
              rel="noreferrer"
            >
              {data.filing.accession_no}
            </a>
          )}
          , filed {data.filing.filed_at}
        </Field>
      )}
      {data.provenance && RULE_NOTES[data.provenance] && (
        <Field name="Rule">{RULE_NOTES[data.provenance]?.text}</Field>
      )}
      {data.derivation && (
        <Field name="Derivation">
          <div>{data.derivation.formula}</div>
          <ul className="text-muted-foreground">
            {data.derivation.inputs.map((input) => (
              <li key={`${input.code}-${input.fiscal_period}`}>
                {input.code} {input.fiscal_period}:{" "}
                <span className="num">{money(input.value)}</span>
              </li>
            ))}
          </ul>
        </Field>
      )}
      <Field name="Vintages">
        {data.vintages.length === 0 ? (
          <span className="text-muted-foreground">
            No filed vintages: computed from other cells.
          </span>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground text-xs">
              <tr>
                <th className="pr-3 font-normal">Filed</th>
                <th className="pr-3 font-normal">Form</th>
                <th className="pr-3 font-normal">Accession</th>
                <th className="num font-normal">Value</th>
              </tr>
            </thead>
            <tbody>
              {data.vintages.map((vintage) => (
                <tr key={vintage.accession_no}>
                  <td className="pr-3">{vintage.filed_at}</td>
                  <td className="pr-3">{vintage.form}</td>
                  <td className="pr-3">{vintage.accession_no}</td>
                  <td className="num">{money(vintage.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Field>
      <Field name="Adjustments">
        <Adjustments ticker={ticker} target={target} scale={scale} adjustments={data.adjustments} />
      </Field>
      <Field name="Notes">
        {PERIODS.includes(target.fiscalPeriod) ? (
          <NotesPanel
            ticker={ticker}
            filter={{
              code: target.code,
              fiscalYear: target.fiscalYear,
              fiscalPeriod: target.fiscalPeriod as FiscalPeriod,
            }}
            addLink={{
              canonical_code: target.code,
              fiscal_year: target.fiscalYear,
              fiscal_period: target.fiscalPeriod as FiscalPeriod,
              description: `${target.label} · ${formatFiscalPeriod(target.fiscalYear, target.fiscalPeriod)}`,
            }}
          />
        ) : (
          <span className="text-muted-foreground">Notes: none</span>
        )}
      </Field>
    </div>
  );
}

export function CellDetailSheet({ ticker, cik, target, scale, onClose }: CellDetailSheetProps) {
  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{target?.label}</SheetTitle>
          <SheetDescription>
            {ticker} · {target?.fiscalYear} {target?.fiscalPeriod}
          </SheetDescription>
        </SheetHeader>
        {target && <Body ticker={ticker} cik={cik} target={target} scale={scale} />}
      </SheetContent>
    </Sheet>
  );
}
