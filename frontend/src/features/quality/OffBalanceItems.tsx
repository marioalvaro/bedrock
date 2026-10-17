import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  offBalanceItemsQueryOptions,
  useCreateOffBalanceItem,
  useDeleteOffBalanceItem,
  useUpdateOffBalanceItem,
} from "@/api/analysis";
import { companyErrorMessage } from "@/api/companies";
import type { OffBalanceItemIn, OffBalanceItemOut } from "@/api/generated/types.gen";
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
import { formatValue, parseScaled, scaleLabel, toScaledText } from "@/lib/format";
import { type Scale, useScale } from "@/lib/scale";

interface OffBalanceItemsProps {
  ticker: string;
}

type Kind = OffBalanceItemIn["kind"];

const KIND_LABELS: Record<Kind, string> = {
  lease: "Lease",
  guarantee: "Guarantee",
  vie: "VIE",
  purchase_commitment: "Purchase commitment",
  other: "Other",
};
const KINDS: Kind[] = ["lease", "guarantee", "vie", "purchase_commitment", "other"];

function ItemForm({
  ticker,
  scale,
  editing,
  onDone,
}: {
  ticker: string;
  scale: Scale;
  editing: OffBalanceItemOut | null;
  onDone: () => void;
}) {
  const create = useCreateOffBalanceItem(ticker);
  const update = useUpdateOffBalanceItem(ticker);
  const [kind, setKind] = useState<Kind>(editing ? (editing.kind as Kind) : "lease");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [amount, setAmount] = useState(
    editing?.amount != null ? toScaledText(editing.amount, scale) : "",
  );
  const [asOf, setAsOf] = useState(editing?.as_of ?? "");
  const [note, setNote] = useState(editing?.source_note ?? "");
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (description.trim() === "") return setError("Enter a description");
    const units = amount.trim() === "" ? null : parseScaled(amount, scale);
    if (amount.trim() !== "" && units === null) return setError("Enter a number");
    if (asOf === "") return setError("Enter a date");
    setError(null);
    const body: OffBalanceItemIn = {
      kind,
      description: description.trim(),
      amount: units,
      as_of: asOf,
      source_note: note.trim() === "" ? null : note.trim(),
    };
    const options = {
      onSuccess: onDone,
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the item.")),
    };
    if (editing) update.mutate({ id: editing.id, body }, options);
    else create.mutate(body, options);
  }

  return (
    <form onSubmit={submit} className="mt-2 space-y-2" noValidate>
      <div className="space-y-1">
        <Label htmlFor="obs-kind">Kind</Label>
        <select
          id="obs-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
          className="border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="obs-description">Description</Label>
        <Input
          id="obs-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="obs-amount">Amount ({scaleLabel("USD", scale)})</Label>
        <Input
          id="obs-amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          inputMode="decimal"
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="obs-as-of">As of</Label>
        <Input id="obs-as-of" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="obs-note">Source note</Label>
        <Input id="obs-note" value={note} onChange={(e) => setNote(e.target.value)} />
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

/**
 * "Off-balance-sheet items": the list (kind, description, amount in the page scale, as-of date,
 * source note) with Edit and Delete (behind an alert-dialog), and a form to add or edit one.
 */
export function OffBalanceItems({ ticker }: OffBalanceItemsProps) {
  const scale = useScale();
  const { data: items, isPending, isError } = useQuery(offBalanceItemsQueryOptions(ticker));
  const remove = useDeleteOffBalanceItem(ticker);
  // `null` closed, "new" adding, otherwise the item being edited.
  const [form, setForm] = useState<OffBalanceItemOut | "new" | null>(null);
  const [toDelete, setToDelete] = useState<OffBalanceItemOut | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Off-balance-sheet items</h2>
        {form === null && (
          <Button type="button" size="sm" variant="outline" onClick={() => setForm("new")}>
            Add item
          </Button>
        )}
      </div>
      {isPending ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : isError ? (
        <p className="text-destructive text-sm">Could not load the off-balance-sheet items.</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground text-sm">None logged.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className="border-border space-y-1 border-b pb-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground text-xs">
                  {KIND_LABELS[item.kind] ?? item.kind}
                </span>
                <span>{item.description}</span>
                <span className="num">
                  {item.amount === null ? "—" : formatValue(item.amount, "USD", scale)}
                </span>
                <span className="text-muted-foreground text-xs">{`as of ${item.as_of}`}</span>
                <span className="ml-auto inline-flex gap-1">
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    aria-label={`Edit ${item.description}`}
                    onClick={() => setForm(item)}
                  >
                    Edit
                  </Button>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    aria-label={`Delete ${item.description}`}
                    onClick={() => {
                      setDeleteError(null);
                      setToDelete(item);
                    }}
                  >
                    Delete
                  </Button>
                </span>
              </div>
              {item.source_note !== null && (
                <div className="text-muted-foreground text-xs">{item.source_note}</div>
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
      {form !== null && (
        <ItemForm
          key={form === "new" ? "new" : `${form.id}-${scale}`}
          ticker={ticker}
          scale={scale}
          editing={form === "new" ? null : form}
          onDone={() => setForm(null)}
        />
      )}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this item?</AlertDialogTitle>
            <AlertDialogDescription>{toDelete?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) {
                  const id = toDelete.id;
                  remove.mutate(id, {
                    onSuccess: () =>
                      setForm((f) => (f !== null && f !== "new" && f.id === id ? null : f)),
                    onError: (e) =>
                      setDeleteError(companyErrorMessage(e, "Could not delete the item.")),
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
