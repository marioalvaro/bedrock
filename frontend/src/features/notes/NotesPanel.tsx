import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { notesQueryOptions, type NoteFilter } from "@/api/context";
import { Button } from "@/components/ui/button";

import { noteLinkText } from "./link";
import { NoteBody } from "./NoteBody";
import { NoteForm, type FixedLink } from "./NoteForm";

interface NotesPanelProps {
  ticker: string;
  filter: NoteFilter;
  addLink: FixedLink; // the link a note added here gets
}

/**
 * The notes of one cell or line (the API's filter semantics) rendered as Markdown, with an
 * "Add note" form whose link is fixed to `addLink`. Used in the cell and line sheets.
 */
export function NotesPanel({ ticker, filter, addLink }: NotesPanelProps) {
  const { data: notes, isPending, isError } = useQuery(notesQueryOptions(ticker, filter));
  const [adding, setAdding] = useState(false);

  return (
    <div className="space-y-2">
      {isPending && <span className="text-muted-foreground">Loading…</span>}
      {isError && <span className="text-destructive">Could not load the notes.</span>}
      {notes && notes.length === 0 && <span className="text-muted-foreground">Notes: none</span>}
      {notes && notes.length > 0 && (
        <ul className="space-y-2">
          {notes.map((note) => (
            <li key={note.id} className="border-border space-y-1 border-b pb-2">
              <div className="text-muted-foreground flex gap-2 text-xs">
                <span className="num">{note.note_date}</span>
                <span>{noteLinkText(note)}</span>
              </div>
              <NoteBody markdown={note.body_md} />
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <NoteForm
          ticker={ticker}
          editing={null}
          fixedLink={addLink}
          onDone={() => setAdding(false)}
        />
      ) : (
        <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)}>
          Add note
        </Button>
      )}
    </div>
  );
}
