import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { noteLinksQueryOptions } from "@/api/context";

import { noteIndex, type NoteIndex } from "./subjects";

/**
 * The company's note-links index for the grid markers. The markers are optional: a failed
 * request leaves the grid without them.
 */
export function useNoteIndex(ticker: string): NoteIndex {
  const { data: links } = useQuery(noteLinksQueryOptions(ticker));
  return useMemo(() => noteIndex(links ?? []), [links]);
}
