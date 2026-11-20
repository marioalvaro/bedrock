import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  adjustmentsQueryOptions,
  corporateActionsQueryOptions,
  useDeleteAdjustment,
} from "@/api/adjustments";
import { companyErrorMessage } from "@/api/companies";
import type {
  AdjustmentOut,
  CoverageOut,
  RuleWarningOut,
  UnmappedConceptOut,
} from "@/api/generated/types.gen";
import { mappingGapsQueryOptions } from "@/api/statements";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  formatFiscalPeriod,
  formatPercent,
  formatSplitRatio,
  formatValue,
  scaleLabel,
} from "@/lib/format";
import { useScale } from "@/lib/scale";
import { ClassifyPanel } from "@/features/classification/ClassifyPanel";
import { ImportButton } from "@/features/imports/ImportButton";

function UnmappedConcepts({ concepts }: { concepts: UnmappedConceptOut[] }) {
  const scale = useScale();
  const [showClassified, setShowClassified] = useState(false);
  const open = concepts.filter((c) => c.classification === null);
  const classified = concepts.filter((c) => c.classification !== null);

  return (
    <div>
      <h3 className="text-muted-foreground mb-1 text-xs">
        Unmapped concepts in the latest 10-K ({open.length}), {scaleLabel("USD", scale)}
      </h3>
      {concepts.length === 0 ? (
        <p className="text-sm">No unmapped concepts.</p>
      ) : open.length === 0 ? (
        <p className="text-sm">No unclassified concepts.</p>
      ) : (
        <ConceptTable concepts={open} />
      )}
      {classified.length > 0 && (
        <div className="mt-2">
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={showClassified}
            onClick={() => setShowClassified((shown) => !shown)}
          >
            {showClassified ? "Hide" : "Show"} classified ({classified.length})
          </Button>
          {showClassified && <ConceptTable concepts={classified} classified />}
        </div>
      )}
    </div>
  );
}

function ConceptTable({
  concepts,
  classified = false,
}: {
  concepts: UnmappedConceptOut[];
  classified?: boolean;
}) {
  const scale = useScale();
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted-foreground text-left text-xs">
            <th className="py-1 pr-4 font-normal">Concept</th>
            <th className="py-1 pr-4 text-right font-normal">Latest value</th>
            <th className="py-1 pr-4 font-normal">Unit</th>
            <th className="py-1 pr-4 font-normal">Period end</th>
            <th className="py-1 pr-4 text-right font-normal">Facts</th>
            {classified ? (
              <>
                <th className="py-1 pr-4 font-normal">Type</th>
                <th className="py-1 pr-4 font-normal">Codes</th>
                <th className="py-1 font-normal">Reason</th>
              </>
            ) : (
              <th className="py-1 font-normal">Suggested</th>
            )}
          </tr>
        </thead>
        <tbody>
          {concepts.map((concept) => (
            <tr
              key={`${concept.taxonomy}:${concept.concept}:${concept.unit}`}
              className="border-border border-b"
            >
              <td className="py-1 pr-4 whitespace-nowrap">
                {concept.taxonomy}:{concept.concept}
              </td>
              <td className="num py-1 pr-4">
                {concept.unit === "USD"
                  ? formatValue(concept.latest_value, concept.unit, scale)
                  : concept.latest_value}
              </td>
              <td className="text-muted-foreground py-1 pr-4">{concept.unit}</td>
              <td className="text-muted-foreground py-1 pr-4">{concept.latest_period_end}</td>
              <td className="num text-muted-foreground py-1 pr-4">{concept.facts}</td>
              {classified && concept.classification ? (
                <>
                  <td className="py-1 pr-4">{concept.classification.type}</td>
                  <td className="py-1 pr-4">{concept.classification.codes.join(", ")}</td>
                  <td className="py-1">{concept.classification.reason}</td>
                </>
              ) : (
                <td className="py-1">{concept.suggested_codes.join(", ")}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const STATEMENT_NAMES: Record<CoverageOut["statement"], string> = {
  IS: "Income statement",
  BS: "Balance sheet",
  CF: "Cash flow",
};

const FREQ_NAMES: Record<CoverageOut["freq"], string> = {
  annual: "Annual",
  quarterly: "Quarterly",
};

type CauseName = keyof CoverageOut["empty_by_cause"];

// Every cause of an empty cell, in the API's order (`statements/coverage.py::CAUSES`), with its
// column name and a one-line explanation.
const CAUSES: { cause: CauseName; name: string; text: string }[] = [
  {
    cause: "no_filing_data",
    name: "No filing data",
    text: "The statement has no figures for the period; no coverage counts the cell.",
  },
  {
    cause: "not_applicable",
    name: "Not applicable",
    text: "The line cannot exist then (before its accounting standard), or the company never reports it.",
  },
  {
    cause: "included_in",
    name: "Included in",
    text: "The amount sits inside a combined line, which the grid marks with a dot.",
  },
  {
    cause: "structural",
    name: "Structural",
    text: "No concept or formula gives this line for the company.",
  },
  {
    cause: "rule_rejected",
    name: "Rule rejected",
    text: "A rule refused to fill the cell; the rule warnings say why.",
  },
  {
    cause: "annual_only",
    name: "Annual only",
    text: "The fiscal year has a value and none of its quarters has one.",
  },
  {
    cause: "extension_unclassified",
    name: "Unclassified line",
    text: "The filing's statement has a line nobody classified near this one; see Lines to classify.",
  },
  {
    cause: "not_reported",
    name: "Not reported",
    text: "No filing gives the value.",
  },
];

// The causes the applicable coverage leaves out on top of the strict one: the backend's
// `statements/coverage.py::INAPPLICABLE` less `no_filing_data`. Keep the two in step (the tooltip
// only names them; the percentages themselves come from the API).
const NOT_APPLICABLE: CauseName[] = ["not_applicable", "included_in"];
const causeName = (cause: CauseName) => CAUSES.find((c) => c.cause === cause)?.name ?? cause;

const COVERAGE_COLUMNS = [
  "Statement",
  "Frequency",
  "Coverage",
  "Filled",
  "Inferred 0",
  "Approximated",
  ...CAUSES.map((c) => c.name),
];

function coverageText(c: CoverageOut): string {
  return `${formatPercent(c.fraction)} (applicable ${formatPercent(c.fraction_applicable)})`;
}

function coverageTitle(c: CoverageOut): string {
  const count = (cause: CauseName) => `${causeName(cause)} (${c.empty_by_cause[cause]})`;
  return (
    `Both leave out ${count("no_filing_data")}. Applicable also leaves out ` +
    `${NOT_APPLICABLE.map(count).join(" and ")}: cells that cannot hold a value.`
  );
}

function CoverageTable({ coverage }: { coverage: CoverageOut[] }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label="Coverage" className="w-full text-sm">
        <thead>
          <tr className="text-muted-foreground text-left text-xs">
            {COVERAGE_COLUMNS.map((name, at) => (
              <th key={name} className={`py-1 pr-4 font-normal ${at >= 2 ? "text-right" : ""}`}>
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {coverage.map((c) => (
            <tr key={`${c.statement}-${c.freq}`} className="border-border border-b">
              <td className="py-1 pr-4">{STATEMENT_NAMES[c.statement]}</td>
              <td className="text-muted-foreground py-1 pr-4">{FREQ_NAMES[c.freq]}</td>
              <td className="num py-1 pr-4 whitespace-nowrap" title={coverageTitle(c)}>
                {coverageText(c)}
              </td>
              <td className="num py-1 pr-4">
                {c.filled} / {c.cells}
              </td>
              <td className="num py-1 pr-4">{c.by_provenance.zero_inferred}</td>
              <td className="num py-1 pr-4">{c.by_provenance.approximated}</td>
              {CAUSES.map(({ cause }) => (
                <td key={cause} className="num py-1 pr-4">
                  {c.empty_by_cause[cause]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CauseList() {
  return (
    <dl
      role="list"
      aria-label="Empty-cell causes"
      className="text-muted-foreground mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs"
    >
      {CAUSES.map(({ cause, name, text }) => (
        <div key={cause} role="listitem" className="contents">
          <dt className="text-foreground">{name}</dt>
          <dd>{text}</dd>
        </div>
      ))}
    </dl>
  );
}

// "FY2024" or "FY2024Q3", as the API's period keys, read "FY2024" and "Q3 FY2024".
function warningPeriod(key: string): string {
  const match = /^FY(\d{4})(Q[1-4])?$/.exec(key);
  return match ? formatFiscalPeriod(Number(match[1]), match[2] ?? "FY") : key;
}

function RuleWarnings({ warnings }: { warnings: RuleWarningOut[] }) {
  const scale = useScale();
  return (
    <div>
      <h3 className="text-muted-foreground mb-1 text-xs">Rule warnings ({warnings.length})</h3>
      {warnings.length === 0 ? (
        <p className="text-sm">No rule warnings.</p>
      ) : (
        <div className="max-h-96 overflow-auto">
          <table aria-label="Rule warnings" className="w-full text-sm">
            <thead>
              <tr className="text-muted-foreground text-left text-xs">
                <th className="py-1 pr-4 font-normal">Rule</th>
                <th className="py-1 pr-4 font-normal">Line</th>
                <th className="py-1 pr-4 font-normal">Period</th>
                <th className="py-1 pr-4 text-right font-normal">
                  Value ({scaleLabel("USD", scale)})
                </th>
                <th className="py-1 font-normal">Reason</th>
              </tr>
            </thead>
            <tbody>
              {warnings.map((w) => (
                <tr
                  key={`${w.rule}-${w.code}-${w.period_key}`}
                  className="border-border border-b align-top"
                >
                  <td className="py-1 pr-4 whitespace-nowrap">{w.rule}</td>
                  <td className="py-1 pr-4">{w.label}</td>
                  <td className="py-1 pr-4 whitespace-nowrap">{warningPeriod(w.period_key)}</td>
                  <td className="num py-1 pr-4">{formatValue(w.value, w.unit, scale)}</td>
                  <td className="py-1">{w.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DataGaps({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(mappingGapsQueryOptions(ticker));

  return (
    <section aria-label="Data gaps" className="px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium">Data gaps</h2>
        <ImportButton ticker={ticker} />
      </div>
      {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && <p className="text-destructive text-sm">Could not load the data gaps.</p>}
      {data && (
        <div className="flex flex-col gap-4">
          <div>
            <h3 className="text-muted-foreground mb-1 text-xs">Coverage</h3>
            {data.coverage.length === 0 ? (
              <p className="text-sm">No statement data yet.</p>
            ) : (
              <>
                <CoverageTable coverage={data.coverage} />
                <CauseList />
              </>
            )}
          </div>
          <RuleWarnings warnings={data.rule_warnings} />
          <ClassifyPanel ticker={ticker} unclassified={data.unclassified_lines} />
          <div>
            <h3 className="text-muted-foreground mb-1 text-xs">
              Missing items ({data.missing_items.length})
            </h3>
            {data.missing_items.length === 0 ? (
              <p className="text-sm">No missing items.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <tbody>
                    {data.missing_items.map((item) => (
                      <tr key={item.code} className="border-border border-b align-top">
                        <td className="py-1 pr-4">{item.label}</td>
                        <td className="text-muted-foreground py-1 pr-4">{item.statement}</td>
                        <td className="text-muted-foreground py-1">
                          {item.missing_periods.join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <UnmappedConcepts concepts={data.unmapped_concepts} />
        </div>
      )}
    </section>
  );
}

function Adjustments({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(adjustmentsQueryOptions(ticker));
  const remove = useDeleteAdjustment(ticker);
  const scale = useScale();
  const [toDelete, setToDelete] = useState<AdjustmentOut | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  return (
    <section aria-label="Adjustments" className="border-border border-t px-4 py-3">
      <h2 className="mb-2 text-sm font-medium">Adjustments</h2>
      {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && <p className="text-destructive text-sm">Could not load the adjustments.</p>}
      {deleteError && (
        <p role="alert" className="text-destructive mb-1 text-sm">
          {deleteError}
        </p>
      )}
      {data &&
        (data.length === 0 ? (
          <p className="text-sm">No adjustments.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted-foreground text-left text-xs">
                  <th className="py-1 pr-4 font-normal">Period</th>
                  <th className="py-1 pr-4 font-normal">Line</th>
                  <th className="py-1 pr-4 text-right font-normal">
                    Amount ({scaleLabel("USD", scale)})
                  </th>
                  <th className="py-1 pr-4 font-normal">Category</th>
                  <th className="py-1 pr-4 font-normal">Reason</th>
                  <th className="py-1 font-normal">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.id} className="border-border border-b align-top">
                    <td className="py-1 pr-4 whitespace-nowrap">
                      {formatFiscalPeriod(a.fiscal_year, a.fiscal_period)}
                    </td>
                    <td className="py-1 pr-4">{a.label}</td>
                    <td className="num py-1 pr-4">{formatValue(a.amount, "USD", scale)}</td>
                    <td className="text-muted-foreground py-1 pr-4">{a.category}</td>
                    <td className="py-1 pr-4">{a.reason}</td>
                    <td className="py-1">
                      <Button
                        type="button"
                        size="xs"
                        variant="outline"
                        aria-label={`Delete adjustment ${a.reason}`}
                        onClick={() => {
                          setDeleteError(null);
                          setToDelete(a);
                        }}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this adjustment?</AlertDialogTitle>
            <AlertDialogDescription>{toDelete?.reason}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) {
                  remove.mutate(toDelete.id, {
                    onError: (e) =>
                      setDeleteError(companyErrorMessage(e, "Could not delete the adjustment.")),
                  });
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function CorporateActions({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(corporateActionsQueryOptions(ticker));

  return (
    <section aria-label="Corporate actions" className="border-border border-t px-4 py-3">
      <h2 className="mb-2 text-sm font-medium">Corporate actions</h2>
      {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && <p className="text-destructive text-sm">Could not load the corporate actions.</p>}
      {data &&
        (data.length === 0 ? (
          <p className="text-sm">No corporate actions.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted-foreground text-left text-xs">
                  <th className="py-1 pr-4 font-normal">Date</th>
                  <th className="py-1 font-normal">Split</th>
                </tr>
              </thead>
              <tbody>
                {data.map((action) => (
                  <tr
                    key={`${action.type}:${action.effective_date}`}
                    className="border-border border-b"
                  >
                    <td className="py-1 pr-4 whitespace-nowrap">{action.effective_date}</td>
                    <td className="num py-1">{formatSplitRatio(action.ratio)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </section>
  );
}

/** The Data tab (FR-WS-04): the panels on the data behind the statements, moved off the Overview. */
export function DataView({ ticker }: { ticker: string }) {
  return (
    <div>
      <DataGaps ticker={ticker} />
      <Adjustments ticker={ticker} />
      <CorporateActions ticker={ticker} />
    </div>
  );
}
