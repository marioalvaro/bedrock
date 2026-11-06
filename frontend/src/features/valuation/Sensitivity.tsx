import { useQuery } from "@tanstack/react-query";

import type { ScenarioCase } from "@/api/scenarios";
import { ValuationUnavailable, tornadoQueryOptions } from "@/api/valuation";

import { CARD } from "./card";
import { SensitivityGrid } from "./SensitivityGrid";
import { Tornado } from "./Tornado";

interface SensitivityProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase; // the view keys this component by scenario and case
}

/**
 * Which inputs move the picked case's DCF value per share (the tornado) and the value over any
 * two of them (the 5 × 5 grid, its inputs the tornado's).
 */
export function Sensitivity({ ticker, scenarioId, scenarioCase }: SensitivityProps) {
  const { data, isPending, error } = useQuery(
    tornadoQueryOptions(ticker, scenarioId, scenarioCase),
  );

  let body;
  if (data) {
    body = (
      <>
        <Tornado tornado={data} />
        <SensitivityGrid
          ticker={ticker}
          scenarioId={scenarioId}
          scenarioCase={scenarioCase}
          inputs={data.bars}
        />
      </>
    );
  } else if (isPending) {
    body = <p className="text-muted-foreground text-sm">Loading the sensitivity…</p>;
  } else {
    body = (
      <p className="text-destructive text-sm">
        {error instanceof ValuationUnavailable && error.detail
          ? error.detail
          : "Could not load the sensitivity."}
      </p>
    );
  }

  return (
    <section aria-label="Sensitivity" className={CARD}>
      <h2 className="text-base font-semibold">Sensitivity</h2>
      {body}
    </section>
  );
}
