import type { ScenarioOut } from "@/api/generated/types.gen";
import { CASES, type ScenarioCase } from "@/api/scenarios";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

interface ScenarioCasePickerProps {
  list: ScenarioOut[];
  selected: ScenarioOut;
  select: (id: number) => void;
  scenarioCase: ScenarioCase;
  selectCase: (next: ScenarioCase) => void;
}

/**
 * The scenario select and the Base | Bull | Bear toggle of the Forecast and Valuation toolbars,
 * fed by `useScenarioParam` (so both tabs share `?scenario` and `?case`).
 */
export function ScenarioCasePicker({
  list,
  selected,
  select,
  scenarioCase,
  selectCase,
}: ScenarioCasePickerProps) {
  return (
    <>
      <select
        aria-label="Scenario"
        className={SELECT}
        value={selected.id}
        onChange={(e) => select(Number(e.target.value))}
      >
        {list.map((scenario) => (
          <option key={scenario.id} value={scenario.id}>
            {scenario.name}
          </option>
        ))}
      </select>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={0}
        aria-label="Case"
        value={scenarioCase}
        onValueChange={(value) => value && selectCase(value as ScenarioCase)}
      >
        {CASES.map(({ value, label }) => (
          <ToggleGroupItem key={value} value={value}>
            {label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </>
  );
}
