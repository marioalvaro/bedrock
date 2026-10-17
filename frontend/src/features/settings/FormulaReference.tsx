import { useId } from "react";

import { FORMULA_GROUPS, type FormulaGroup } from "./formulaNames";

const FUNCTIONS: [string, string][] = [
  ["avg(x)", "x now and a year earlier, averaged; empty unless both exist"],
  ["yoy(x)", "growth on a year earlier (x / prior − 1); empty unless the prior is above 0"],
  ["prev(x)", "x a year earlier (the prior FY, or in TTM the same quarter a year earlier)"],
];

const NOTES = [
  "Numbers inside a formula are fractions: write 1% or 0.01 (a bare level number in a % field is a percent).",
  "Quality-of-earnings rule codes (e.g. sbc_to_revenue) and custom rule codes are not names: write sbc / revenue.",
  "eps_diluted and goodwill_impairment are both a line and a ratio or rule; in a formula they are the line.",
  "Outflows (capex, buybacks, dividends_paid…) are negative, as on the cash flow statement. A division by 0 or a negative number, or any empty operand, gives an empty value.",
];

function Group({ group }: { group: FormulaGroup }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="mt-3">
      <h4 id={id} className="text-sm font-medium">
        {group.title}
      </h4>
      <ul className="mt-1 flex flex-wrap gap-1">
        {group.names.map(({ code, unit }) => (
          <li key={code} className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs break-all">
            {unit ? `${code} (${unit})` : code}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Settings: a collapsed reference of what a QoE formula may use (FR-ANL-10): operators,
 * functions, notes on units and names, and every name by group (`formulaNames.ts`).
 */
export function FormulaReference() {
  return (
    <details className="mt-8 rounded border p-3">
      <summary className="cursor-pointer text-lg font-semibold">Formula reference</summary>
      <div className="mt-2 text-sm">
        <p>
          Operators: <code className="font-mono">+ − × ÷ ( )</code> (or <code>* /</code>)
        </p>
        <ul className="mt-2 space-y-1">
          {FUNCTIONS.map(([fn, text]) => (
            <li key={fn}>
              <code className="font-mono">{fn}</code>{" "}
              <span className="text-muted-foreground">— {text}</span>
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground mt-2">
          Functions nest: prev(prev(x)) is two years back.
        </p>
        <ul className="text-muted-foreground mt-2 list-disc space-y-1 pl-5">
          {NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
        {FORMULA_GROUPS.map((group) => (
          <Group key={group.title} group={group} />
        ))}
      </div>
    </details>
  );
}
