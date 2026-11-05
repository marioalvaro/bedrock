/**
 * A small "Q" beside a year's header: the year's figures are built from its quarters (FR-FCST-13),
 * as the scenario sets that year by quarter.
 */
export function BuiltFromQuartersMark() {
  return (
    <span
      role="img"
      aria-label="Built from quarters"
      title="Built from quarters"
      className="text-muted-foreground border-border ml-1 inline-block rounded-sm border px-0.5 align-middle text-[9px] leading-3"
    >
      Q
    </span>
  );
}
