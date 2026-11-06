import { useQuery } from "@tanstack/react-query";

import { companyErrorMessage } from "@/api/companies";
import { scenariosQueryOptions } from "@/api/scenarios";
import { UnitToggle } from "@/components/UnitToggle";
import { ScenarioCasePicker } from "@/features/scenarios/ScenarioCasePicker";
import { useScenarioParam } from "@/features/scenarios/useScenarioParam";

import { ValuationInputs } from "./ValuationInputs";
import { ValuationResults } from "./ValuationResults";
import { ValuationSummary } from "./ValuationSummary";

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
      <ValuationSummary
        key={selected.id}
        ticker={ticker}
        scenarioId={selected.id}
        scenarioCase={scenarioCase}
      />
      <ValuationResults
        key={`results:${caseKey}`}
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
    </div>
  );
}
