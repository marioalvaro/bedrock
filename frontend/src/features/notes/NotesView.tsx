import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { notesQueryOptions, useDeleteNote, type FiscalPeriod } from "@/api/context";
import type { NoteOut } from "@/api/generated/types.gen";
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

import { noteLinkText } from "./link";
import { NoteBody } from "./NoteBody";
import { PERIODS, SELECT } from "./constants";
import { NoteForm } from "./NoteForm";
import { usePeriodOptions } from "./periods";
import { useSubjectGroups } from "./subjectGroups";
import { parseSubjectKey } from "./subjects";

interface NotesViewProps {
  ticker: string;
}

/** The Notes tab: the Markdown journal of the company, filterable by line and period. */
export function NotesView({ ticker }: NotesViewProps) {
  const subjects = useSubjectGroups(ticker);
  const periods = usePeriodOptions(ticker);
  const [subject, setSubject] = useState("");
  const [year, setYear] = useState("");
  const [period, setPeriod] = useState("");
  // `null` closed, "new" writing, otherwise the note being edited.
  const [form, setForm] = useState<NoteOut | "new" | null>(null);
  const [toDelete, setToDelete] = useState<NoteOut | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const remove = useDeleteNote(ticker);

  // The API takes a year and a period together, so the period filter waits for both.
  const yearValue = /^\d{4}$/.test(year.trim()) ? Number(year.trim()) : null;
  const picked = parseSubjectKey(subject);
  const filter = {
    ...(picked?.kind === "line" && { code: picked.code }),
    ...(picked && picked.kind !== "line" && { metricKind: picked.kind, metricCode: picked.code }),
    ...(yearValue !== null && period !== "" && { fiscalYear: yearValue }),
    ...(yearValue !== null && period !== "" && { fiscalPeriod: period as FiscalPeriod }),
  };
  const { data: notes, isPending, isError } = useQuery(notesQueryOptions(ticker, filter));

  return (
    <div>
      <div className="border-border flex flex-wrap items-end gap-2 border-b px-4 py-2">
        <select
          aria-label="Filter by subject"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          className={`${SELECT} w-auto`}
        >
          <option value="">All subjects</option>
          {subjects.map((group) => (
            <optgroup key={group.group} label={group.group}>
              {group.options.map((entry) => (
                <option key={entry.value} value={entry.value}>
                  {entry.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <Input
          aria-label="Filter by year"
          type="number"
          placeholder="Year"
          value={year}
          onChange={(e) => setYear(e.target.value)}
          className="w-24"
        />
        <select
          aria-label="Filter by period"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className={`${SELECT} w-auto`}
        >
          <option value="">Any period</option>
          {PERIODS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={() => setForm("new")}
        >
          New note
        </Button>
      </div>
      {form !== null && (
        <NoteForm
          key={form === "new" ? "new" : form.id}
          ticker={ticker}
          editing={form === "new" ? null : form}
          subjects={subjects}
          periods={periods}
          onDone={() => setForm(null)}
        />
      )}
      {deleteError && (
        <p role="alert" className="text-destructive px-4 py-2 text-sm">
          {deleteError}
        </p>
      )}
      {isPending && <p className="text-muted-foreground p-4 text-sm">Loading…</p>}
      {isError && <p className="text-destructive p-4 text-sm">Could not load the notes.</p>}
      {notes && notes.length === 0 && (
        <p className="text-muted-foreground p-4 text-sm">No notes yet.</p>
      )}
      {notes && notes.length > 0 && (
        <ul className="divide-border divide-y px-4">
          {notes.map((note) => {
            const link = noteLinkText(note);
            return (
              <li key={note.id} className="space-y-1 py-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="num">{note.note_date}</span>
                  {link && <span className="text-muted-foreground">{link}</span>}
                  <span className="ml-auto inline-flex gap-1">
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      aria-label={`Edit note ${note.id}`}
                      onClick={() => setForm(note)}
                    >
                      Edit
                    </Button>
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      aria-label={`Delete note ${note.id}`}
                      onClick={() => {
                        setDeleteError(null);
                        setToDelete(note);
                      }}
                    >
                      Delete
                    </Button>
                  </span>
                </div>
                <NoteBody markdown={note.body_md} />
              </li>
            );
          })}
        </ul>
      )}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this note?</AlertDialogTitle>
            <AlertDialogDescription>
              {toDelete ? `The note from ${toDelete.note_date} will be removed.` : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) {
                  const id = toDelete.id;
                  remove.mutate(id, {
                    onSuccess: () =>
                      setForm((open) =>
                        open !== null && open !== "new" && open.id === id ? null : open,
                      ),
                    onError: (e) =>
                      setDeleteError(companyErrorMessage(e, "Could not delete the note.")),
                  });
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
