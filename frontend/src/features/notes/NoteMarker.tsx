interface NoteMarkerProps {
  label: string; // the row's label, for the accessible name
  onClick: () => void;
}

/** The "•" after a row label whose subject has notes; opens the subject's notes. */
export function NoteMarker({ label, onClick }: NoteMarkerProps) {
  return (
    <button
      type="button"
      className="text-note-marker cursor-pointer leading-none"
      aria-label={`Notes on ${label}`}
      onClick={onClick}
    >
      •
    </button>
  );
}
