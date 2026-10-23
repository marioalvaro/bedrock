import { useQuery } from "@tanstack/react-query";

import { statementQueryOptions, type StatementType } from "@/api/statements";

export interface LineOption {
  code: string;
  label: string;
}

// The canonical lines of one statement, for the line selects.
export interface LineGroup {
  statement: string;
  lines: LineOption[];
}

const STATEMENTS: { type: StatementType; name: string }[] = [
  { type: "IS", name: "Income" },
  { type: "BS", name: "Balance" },
  { type: "CF", name: "Cash flow" },
];

/**
 * The canonical lines grouped by statement, from the annual statement payloads (they list every
 * line, empty or not, and are usually cached by the statement tabs). A statement that has not
 * loaded yet is left out.
 */
export function useLineGroups(ticker: string): LineGroup[] {
  const income = useQuery(statementQueryOptions(ticker, "IS", "annual"));
  const balance = useQuery(statementQueryOptions(ticker, "BS", "annual"));
  const cashFlow = useQuery(statementQueryOptions(ticker, "CF", "annual"));
  const payloads = [income.data, balance.data, cashFlow.data];
  return STATEMENTS.flatMap(({ name }, index) => {
    const payload = payloads[index];
    return payload
      ? [{ statement: name, lines: payload.rows.map(({ code, label }) => ({ code, label })) }]
      : [];
  });
}
