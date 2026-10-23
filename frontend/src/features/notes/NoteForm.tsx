import { useState } from "react";

import { companyErrorMessage } from "@/api/companies";
import { useCreateNote, useUpdateNote, type FiscalPeriod } from "@/api/context";
import type { NoteIn, NoteOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { PERIODS, SELECT } from "./constants";
import type { LineGroup } from "./lines";

// A link the form cannot change (a note added from a cell or a line sheet).
export interface FixedLink {
  canonical_code: string | null;
  fiscal_year: number | null;
  fiscal_period: FiscalPeriod | null;
  description: string; // "Revenue · FY2024"
}

interface NoteFormProps {
  ticker: string;
  editing: NoteOut | null;
  lines?: LineGroup[]; // for the line select; unused with a fixed link
  fixedLink?: FixedLink;
  onDone: () => void;
}

/** Writes or edits a note: Markdown body, date, and an optional line / fiscal period link. */
export function NoteForm({ ticker, editing, lines = [], fixedLink, onDone }: NoteFormProps) {
  const create = useCreateNote(ticker);
  const update = useUpdateNote(ticker);
  const [body, setBody] = useState(editing?.body_md ?? "");
  const [date, setDate] = useState(editing?.note_date ?? "");
  const [code, setCode] = useState(editing?.canonical_code ?? "");
  const [year, setYear] = useState(editing?.fiscal_year?.toString() ?? "");
  const [period, setPeriod] = useState<string>(editing?.fiscal_period ?? "");
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (body.trim() === "") return setError("Enter a note");
    let link: Pick<NoteIn, "canonical_code" | "fiscal_year" | "fiscal_period">;
    if (fixedLink) {
      link = {
        canonical_code: fixedLink.canonical_code,
        fiscal_year: fixedLink.fiscal_year,
        fiscal_period: fixedLink.fiscal_period,
      };
    } else {
      const yearText = year.trim();
      if ((yearText === "") !== (period === "")) {
        return setError("Pick both a fiscal year and a period");
      }
      if (yearText !== "" && !/^\d{4}$/.test(yearText)) return setError("Enter a four-digit year");
      link = {
        canonical_code: code === "" ? null : code,
        fiscal_year: yearText === "" ? null : Number(yearText),
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
    <form onSubmit={submit} className="border-border space-y-2 border-b px-4 py-3" noValidate>
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
              <Label htmlFor="note-line">Line</Label>
              <select
                id="note-line"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className={SELECT}
              >
                <option value="">None</option>
                {lines.map((group) => (
                  <optgroup key={group.statement} label={group.statement}>
                    {group.lines.map((line) => (
                      <option key={line.code} value={line.code}>
                        {line.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="note-year">Fiscal year</Label>
              <Input
                id="note-year"
                type="number"
                value={year}
                onChange={(e) => setYear(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="note-period">Period</Label>
              <select
                id="note-period"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className={SELECT}
              >
                <option value="">None</option>
                {PERIODS.map((p) => (
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
