import { useQuery } from "@tanstack/react-query";

import {
  capitalAllocationQueryOptions,
  flagsQueryOptions,
  ratiosQueryOptions,
} from "@/api/analysis";
import { statementQueryOptions, type StatementType } from "@/api/statements";

import { subjectKey, type SubjectKind } from "./subjects";

export interface SubjectOption {
  value: string; // the subject key, "ratio:roe"
  label: string;
}

// The subjects of one select group: a statement's lines, or a kind of metric.
export interface SubjectGroup {
  group: string;
  options: SubjectOption[];
}

const STATEMENTS: { type: StatementType; name: string }[] = [
  { type: "IS", name: "Income" },
  { type: "BS", name: "Balance" },
  { type: "CF", name: "Cash flow" },
];

const option = (kind: SubjectKind, { code, label }: { code: string; label: string }) => ({
  value: subjectKey(kind, code),
  label,
});

/**
 * Everything a note can be about, grouped for the subject selects: the lines of each statement,
 * then the ratios, the capital-allocation metrics and the quality rules (built-in and custom).
 * They come from the annual (reported) payloads, which list every row and are usually cached by
 * the tabs. A payload that has not loaded yet, or failed, leaves its group out.
 */
export function useSubjectGroups(ticker: string): SubjectGroup[] {
  const statements = [
    useQuery(statementQueryOptions(ticker, "IS", "annual")),
    useQuery(statementQueryOptions(ticker, "BS", "annual")),
    useQuery(statementQueryOptions(ticker, "CF", "annual")),
  ];
  const ratios = useQuery(ratiosQueryOptions(ticker, "annual", "reported"));
  const capital = useQuery(capitalAllocationQueryOptions(ticker, "annual"));
  const quality = useQuery(flagsQueryOptions(ticker, "annual"));
  const groups: (SubjectGroup | null | undefined)[] = [
    ...STATEMENTS.map(({ name }, index) => {
      const rows = statements[index]?.data?.rows;
      return rows ? { group: name, options: rows.map((row) => option("line", row)) } : null;
    }),
    ratios.data && { group: "Ratios", options: ratios.data.rows.map((r) => option("ratio", r)) },
    capital.data && {
      group: "Capital",
      options: capital.data.rows.map((r) => option("capital", r)),
    },
    quality.data && {
      group: "Quality",
      options: quality.data.rules.map((r) => option("quality", r)),
    },
  ];
  return groups.filter((group): group is SubjectGroup => !!group);
}
