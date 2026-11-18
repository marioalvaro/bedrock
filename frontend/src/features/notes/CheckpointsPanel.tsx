import { useQuery } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  checkpointsQueryOptions,
  useCreateCheckpoint,
  useDeleteCheckpoint,
  useUpdateCheckpoint,
} from "@/api/checkpoints";
import { companyErrorMessage } from "@/api/companies";
import { ApiError } from "@/api/errors";
import type { CheckpointIn, CheckpointOut } from "@/api/generated/types.gen";
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
import {
  CHECKPOINT_STATES,
  checkpointValueText,
  sinceLastFilingText,
} from "@/features/review/reviewFormat";

type Freq = CheckpointIn["freq"];

const HEAD = "text-muted-foreground px-2 py-1 text-left font-normal whitespace-nowrap";
const CELL = "px-2 py-1 align-top";

interface CheckpointFormProps {
  ticker: string;
  editing: CheckpointOut | null;
  onDone: () => void;
}

/** The inline add / edit form. A 422 keeps the text and shows the API's reason under the
 * statement, with the position it names. */
function CheckpointForm({ ticker, editing, onDone }: CheckpointFormProps) {
  const create = useCreateCheckpoint(ticker);
  const update = useUpdateCheckpoint(ticker);
  const [statement, setStatement] = useState(editing?.statement ?? "");
  const [label, setLabel] = useState(editing?.label ?? "");
  const [freq, setFreq] = useState<Freq>(editing?.freq ?? "ttm");
  const [margin, setMargin] = useState(editing?.margin ?? "");
  const [error, setError] = useState<{ text: string; invalid: boolean } | null>(null);
  const pending = create.isPending || update.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const body: CheckpointIn = {
      statement,
      label: label.trim() || null,
      freq,
      margin: margin.trim() || null,
    };
    const handlers = {
      onSuccess: onDone,
      onError: (e: Error) =>
        setError({
          text: companyErrorMessage(e, "Could not save the checkpoint."),
          invalid: e instanceof ApiError && e.status === 422,
        }),
    };
    if (editing) update.mutate({ id: editing.id, body }, handlers);
    else create.mutate(body, handlers);
  }

  return (
    <form
      aria-label={editing ? "Edit checkpoint" : "Add checkpoint"}
      onSubmit={submit}
      noValidate
      className="border-border grid gap-3 border-b py-3 sm:grid-cols-[1fr_14rem_auto_8rem] sm:items-start"
    >
      <div className="space-y-1">
        <Label htmlFor="checkpoint-statement">Statement</Label>
        <Input
          id="checkpoint-statement"
          className="font-mono"
          placeholder="gross_margin > 44%"
          value={statement}
          aria-invalid={error?.invalid ? true : undefined}
          aria-describedby={error ? "checkpoint-error" : undefined}
          onChange={(e) => setStatement(e.target.value)}
        />
        {error && (
          <p id="checkpoint-error" role="alert" className="text-destructive text-xs">
            {error.text}
          </p>
        )}
      </div>
      <div className="space-y-1">
        <Label htmlFor="checkpoint-label">Label</Label>
        <Input
          id="checkpoint-label"
          placeholder="Optional"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </div>
      <div className="space-y-1">
        <Label id="checkpoint-freq">Frequency</Label>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-labelledby="checkpoint-freq"
          value={freq}
          onValueChange={(value) => value && setFreq(value as Freq)}
        >
          <ToggleGroupItem value="ttm">TTM</ToggleGroupItem>
          <ToggleGroupItem value="annual">Annual</ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className="space-y-1">
        <Label htmlFor="checkpoint-margin">At-risk margin</Label>
        <Input
          id="checkpoint-margin"
          placeholder="e.g. 1%"
          value={margin}
          onChange={(e) => setMargin(e.target.value)}
        />
      </div>
      <div className="flex gap-2 sm:col-span-full">
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

function ValueCell({ checkpoint }: { checkpoint: CheckpointOut }) {
  if (checkpoint.error) return <span className="text-destructive">{checkpoint.error}</span>;
  return (
    <>
      <div className="num">{checkpointValueText(checkpoint)}</div>
      {checkpoint.period && (
        <div className="text-muted-foreground text-xs">{checkpoint.period.label}</div>
      )}
    </>
  );
}

/** The thesis checkpoints of a company (FR-NOTE-03): each statement's state on the latest data,
 * computed by the backend, and what the newest report changed. */
export function CheckpointsPanel({ ticker }: { ticker: string }) {
  const { data, isPending } = useQuery(checkpointsQueryOptions(ticker));
  const remove = useDeleteCheckpoint(ticker);
  // `null` closed, "new" adding, otherwise the checkpoint being edited.
  const [form, setForm] = useState<CheckpointOut | "new" | null>(null);
  const [toDelete, setToDelete] = useState<CheckpointOut | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  let body;
  if (!data) {
    body = isPending ? (
      <p className="text-muted-foreground text-sm">Loading…</p>
    ) : (
      <p className="text-destructive text-sm">Could not load the checkpoints.</p>
    );
  } else if (data.checkpoints.length === 0) {
    body = (
      <p className="text-muted-foreground text-sm">
        No checkpoints yet. Write what must stay true for the thesis to hold.
      </p>
    );
  } else {
    body = (
      <div className="overflow-x-auto">
        <table aria-label="Thesis checkpoints" className="w-full text-sm">
          <thead>
            <tr>
              <th className={HEAD}>State</th>
              <th className={HEAD}>Checkpoint</th>
              <th className={HEAD}>Value</th>
              <th className={HEAD}>Since last filing</th>
              <th className="px-2 py-1" />
            </tr>
          </thead>
          <tbody>
            {data.checkpoints.map((checkpoint) => {
              const state = CHECKPOINT_STATES[checkpoint.state];
              return (
                <tr key={checkpoint.id} className="border-border border-t">
                  <td className={`${CELL} whitespace-nowrap`}>
                    <span className={`rounded px-1 ${state.className}`}>{state.text}</span>
                  </td>
                  <td className={CELL}>
                    <div>{checkpoint.label}</div>
                    <div className="text-muted-foreground font-mono text-xs break-words">
                      {checkpoint.statement}
                    </div>
                  </td>
                  <td className={`${CELL} whitespace-nowrap`}>
                    <ValueCell checkpoint={checkpoint} />
                  </td>
                  <td className={`${CELL} text-muted-foreground whitespace-nowrap`}>
                    {sinceLastFilingText(checkpoint)}
                  </td>
                  <td className={`${CELL} whitespace-nowrap`}>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Edit ${checkpoint.label}`}
                      onClick={() => setForm(checkpoint)}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${checkpoint.label}`}
                      onClick={() => {
                        setDeleteError(null);
                        setToDelete(checkpoint);
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <section className="border-border space-y-2 border-b px-4 py-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-medium">Thesis checkpoints</h2>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={() => setForm("new")}
        >
          Add checkpoint
        </Button>
      </div>
      {form !== null && (
        <CheckpointForm
          key={form === "new" ? "new" : form.id}
          ticker={ticker}
          editing={form === "new" ? null : form}
          onDone={() => setForm(null)}
        />
      )}
      {deleteError && (
        <p role="alert" className="text-destructive text-sm">
          {deleteError}
        </p>
      )}
      {body}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this checkpoint?</AlertDialogTitle>
            <AlertDialogDescription>
              {toDelete ? `"${toDelete.label}" will be removed.` : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!toDelete) return;
                const id = toDelete.id;
                remove.mutate(id, {
                  onSuccess: () =>
                    setForm((open) =>
                      open !== null && open !== "new" && open.id === id ? null : open,
                    ),
                  onError: (e) =>
                    setDeleteError(companyErrorMessage(e, "Could not delete the checkpoint.")),
                });
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
