import { useQuery } from "@tanstack/react-query";

import { companyErrorMessage } from "@/api/companies";
import { CASES, scenariosQueryOptions, type ScenarioCase } from "@/api/scenarios";
import { UnitToggle } from "@/components/UnitToggle";
import { ScenarioCasePicker } from "@/features/scenarios/ScenarioCasePicker";
import { useScenarioParam } from "@/features/scenarios/useScenarioParam";

import { Sensitivity } from "./Sensitivity";
import { ValuationInputs } from "./ValuationInputs";
import { ValuationResults } from "./ValuationResults";
import { ValuationSummary } from "./ValuationSummary";

// The case's color, as in the summary and the comparison: green up, blue neutral, red down.
const CASE_DOT: Record<ScenarioCase, string> = {
  bull: "bg-positive",
  base: "bg-chart-1",
  bear: "bg-negative",
};

interface ValuationViewProps {
  ticker: string;
}

/**
 * The Valuation tab: the picked scenario's three cases against the price, then the picked case's
 * DCF and multiple-target results and its inputs. `?scenario` and `?case` are shared with the
 * Forecast and Scenarios tabs.
 */
export function ValuationView({ ticker }: ValuationViewProps) {
  const { data: list, isPending, error } = useQuery(scenariosQueryOptions(ticker));
  const { selected, select, scenarioCase, selectCase } = useScenarioParam(list);

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (list?.length === 0) return <p className="text-muted-foreground p-4 text-sm">No scenarios.</p>;
  // Only a failed first load replaces the tab; a failed background refetch keeps the data shown.
  if (!list || !selected) {
    return (
      <p className="text-destructive p-4 text-sm">
        {companyErrorMessage(error, "Could not load the scenarios.")}
      </p>
    );
  }

  // Keyed so another scenario's or case's numbers (and a case's edit errors) never show for this one.
  const caseKey = `${selected.id}:${scenarioCase}`;
  const caseLabel = `${CASES.find((item) => item.value === scenarioCase)?.label ?? scenarioCase} case`;
  return (
    <div>
      <div className="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <ScenarioCasePicker
          list={list}
          selected={selected}
          select={select}
          scenarioCase={scenarioCase}
          selectCase={selectCase}
        />
        <UnitToggle />
      </div>
      <div className="space-y-4 p-4">
        <ValuationSummary
          key={selected.id}
          ticker={ticker}
          scenarioId={selected.id}
          scenarioCase={scenarioCase}
        />
        {/* Everything below details the picked case, so it is grouped under its name. */}
        <section aria-labelledby="valuation-case" className="space-y-4">
          <div className="flex items-center gap-2 pt-2">
            <span aria-hidden className={`size-2.5 rounded-full ${CASE_DOT[scenarioCase]}`} />
            <h2 id="valuation-case" className="text-lg font-semibold">
              {caseLabel}
            </h2>
            <span className="text-muted-foreground text-sm">{selected.name} scenario</span>
          </div>
          <ValuationResults
            key={`results:${caseKey}`}
            ticker={ticker}
            scenarioId={selected.id}
            scenarioCase={scenarioCase}
          />
          <Sensitivity
            key={`sensitivity:${caseKey}`}
            ticker={ticker}
            scenarioId={selected.id}
            scenarioCase={scenarioCase}
          />
          <ValuationInputs
            key={`inputs:${caseKey}`}
            ticker={ticker}
            scenarioId={selected.id}
            scenarioCase={scenarioCase}
          />
        </section>
      </div>
    </div>
  );
}
