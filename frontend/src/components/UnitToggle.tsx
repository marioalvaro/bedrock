import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { SCALES, setScale, useScale, type Scale } from "@/lib/scale";

export function UnitToggle() {
  const scale = useScale();

  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      spacing={0}
      aria-label="Scale"
      value={scale}
      // Radix reports "" when the active item is clicked again; keep the current scale.
      onValueChange={(value) => value && setScale(value as Scale)}
    >
      {SCALES.map((option) => (
        <ToggleGroupItem key={option} value={option} aria-label={option}>
          {option}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
