import type { CustomHeaderGroupProps, CustomHeaderProps } from "ag-grid-react";
import { useContext } from "react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import { YearModesContext, type YearModeValue } from "./yearModes";

// The switch shows one letter so it fits any year header, even over a single quarter; the full
// name is the hover title and the accessible name.
const YEAR_MODE_LABELS: Record<YearModeValue, { name: string; letter: string }> = {
  annual: { name: "Annual", letter: "A" },
  quarterly: { name: "By quarter", letter: "Q" },
};

/** The Annual | By quarter switch of a forecast year of the quarterly span; nothing after it. */
function YearSwitch({ year }: { year: number }) {
  const { modes, disabled, onMode } = useContext(YearModesContext);
  const entry = modes.get(year);
  if (!entry?.in_span) return null;
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      spacing={0}
      disabled={disabled}
      aria-label={`${entry.label} mode`}
      value={entry.mode}
      onValueChange={(value) =>
        value && value !== entry.mode && onMode(year, value as YearModeValue)
      }
    >
      {(Object.keys(YEAR_MODE_LABELS) as YearModeValue[]).map((value) => (
        <ToggleGroupItem
          key={value}
          value={value}
          title={YEAR_MODE_LABELS[value].name}
          aria-label={YEAR_MODE_LABELS[value].name}
          className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-5 min-w-0 px-1.5 text-[11px]"
        >
          {YEAR_MODE_LABELS[value].letter}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** Header of a forecast year in the annual grid: its switch, then its label. */
export function YearHeader({ displayName, year }: CustomHeaderProps & { year: number }) {
  return (
    <div className="flex w-full items-center justify-end gap-2">
      <YearSwitch year={year} />
      <span>{displayName}</span>
    </div>
  );
}

/** Header over a forecast year's quarters in the quarterly grid. */
export function YearGroupHeader({ displayName, year }: CustomHeaderGroupProps & { year: number }) {
  return (
    <div className="flex w-full items-center justify-center gap-2">
      <YearSwitch year={year} />
      <span>{displayName}</span>
    </div>
  );
}
