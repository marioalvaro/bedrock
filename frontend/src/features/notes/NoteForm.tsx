import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { useCreateNote, useUpdateNote, type FiscalPeriod } from "@/api/context";
import type { NoteIn, NoteOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { localIsoDate, useNow } from "@/lib/now";

import { SELECT } from "./constants";
import type { PeriodOptions } from "./periods";
import type { SubjectGroup } from "./subjectGroups";
import { parseSubjectKey, subjectKey } from "./subjects";

// A link the form cannot change (a note added from a cell or a line sheet).
export interface FixedLink {
  canonical_code: string | null;
  metric_kind?: NonNullable<NoteIn["metric_kind"]>; // omitted for a line link
  metric_code?: string;
  fiscal_year: number | null;
  fiscal_period: FiscalPeriod | null;
  description: string; // "Revenue · FY2024"
}

interface NoteFormProps {
  ticker: string;
  editing: NoteOut | null;
  subjects?: SubjectGroup[]; // for the subject select; unused with a fixed link
  periods?: PeriodOptions; // for the year and period selects; unused with a fixed link
  fixedLink?: FixedLink;
  embedded?: boolean; // inside an already padded sheet: no padding or rule of its own
  onDone: () => void;
}

const NO_PERIODS: PeriodOptions = { loaded: false, years: [], periodsOf: () => [] };

// The select value of a note's subject: its line or metric, or "" for none.
function subjectOf(note: NoteOut): string {
  if (note.metric_kind && note.metric_code) return subjectKey(note.metric_kind, note.metric_code);
  return note.canonical_code ? subjectKey("line", note.canonical_code) : "";
}

/** Writes or edits a note: Markdown body, date, and an optional line / fiscal period link. */
export function NoteForm({
  ticker,
  editing,
  subjects = [],
  periods = NO_PERIODS,
  fixedLink,
  embedded = false,
  onDone,
}: NoteFormProps) {
  const create = useCreateNote(ticker);
  const update = useUpdateNote(ticker);
  const [body, setBody] = useState(editing?.body_md ?? "");
  const now = useNow();
  const [date, setDate] = useState(editing?.note_date ?? localIsoDate(now));
  const [subject, setSubject] = useState(editing ? subjectOf(editing) : "");
  const [year, setYear] = useState(editing?.fiscal_year?.toString() ?? "");
  const [period, setPeriod] = useState<string>(editing?.fiscal_period ?? "");
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending;
  // A stored year the company has no statements for stays selectable, flagged, so the select
  // never shows a different year than the one that would be saved.
  const unknownYear = periods.loaded && year !== "" && !periods.years.includes(Number(year));
  const periodChoices = unknownYear
    ? [period].filter((p) => p !== "")
    : year === ""
      ? []
      : periods.periodsOf(Number(year));

  // A stored subject that is no longer listed (a deleted custom rule) stays selectable, so the
  // select never shows a different subject than the one that would be saved.
  const storedOnly =
    editing !== null &&
    subject !== "" &&
    subject === subjectOf(editing) &&
    !subjects.some((group) => group.options.some((entry) => entry.value === subject)) &&
    subjects.length > 0;

  function pickYear(next: string) {
    setYear(next);
    if (next === "" || !periods.periodsOf(Number(next)).includes(period as FiscalPeriod)) {
      setPeriod("");
    }
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (body.trim() === "") return setError("Enter a note");
    let link: Pick<
      NoteIn,
      "canonical_code" | "metric_kind" | "metric_code" | "fiscal_year" | "fiscal_period"
    >;
    if (fixedLink) {
      link = {
        canonical_code: fixedLink.canonical_code,
        ...(fixedLink.metric_kind && {
          metric_kind: fixedLink.metric_kind,
          metric_code: fixedLink.metric_code,
        }),
        fiscal_year: fixedLink.fiscal_year,
        fiscal_period: fixedLink.fiscal_period,
      };
    } else {
      if ((year === "") !== (period === "")) {
        return setError("Pick both a fiscal year and a period");
      }
      const picked = parseSubjectKey(subject);
      link = {
        canonical_code: picked?.kind === "line" ? picked.code : null,
        metric_kind: picked && picked.kind !== "line" ? picked.kind : null,
        metric_code: picked && picked.kind !== "line" ? picked.code : null,
        fiscal_year: year === "" ? null : Number(year),
        fiscal_period: period === "" ? null : (period as FiscalPeriod),
      };
    }
    setError(null);
    const payload: NoteIn = { body_md: body.trim(), ...link, ...(date ? { note_date: date } : {}) };
    const options = {
      onSuccess: onDone,
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the note.")),
    };
    if (editing) update.mutate({ id: editing.id, body: payload }, options);
    else create.mutate(payload, options);
  }

  return (
    <form
      onSubmit={submit}
      className={embedded ? "mt-2 space-y-2" : "border-border space-y-2 border-b px-4 py-3"}
      noValidate
    >
      <div className="space-y-1">
        <Label htmlFor="note-body">Note</Label>
        <textarea
          id="note-body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder="Markdown"
          className="border-input w-full rounded-lg border bg-transparent p-2 text-sm"
        />
      </div>
      <div className="grid gap-2 sm:grid-cols-4">
        <div className="space-y-1">
          <Label htmlFor="note-date">Note date</Label>
          <Input
            id="note-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
        {fixedLink ? (
          <p className="text-muted-foreground self-end text-sm sm:col-span-3">
            Linked to {fixedLink.description}
          </p>
        ) : (
          <>
            <div className="space-y-1">
              <Label htmlFor="note-subject">Subject</Label>
              <select
                id="note-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className={SELECT}
              >
                <option value="">None</option>
                {storedOnly && (
                  <option value={subject}>
                    {editing?.label ?? editing?.metric_code ?? subject}
                  </option>
                )}
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
            </div>
            <div className="space-y-1">
              <Label htmlFor="note-year">Fiscal year</Label>
              <select
                id="note-year"
                value={year}
                onChange={(e) => pickYear(e.target.value)}
                className={SELECT}
              >
                <option value="">None</option>
                {unknownYear && <option value={year}>{year} (no statements)</option>}
                {periods.years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="note-period">Period</Label>
              <select
                id="note-period"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                disabled={year === ""}
                className={SELECT}
              >
                <option value="">None</option>
                {periodChoices.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
          </>
        )}
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
