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
  CompanyListItem,
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
  formatCompact,
  formatFiscalPeriod,
  formatSplitRatio,
  formatMultiple,
  formatPercent,
  formatPrice,
  formatValue,
  scaleLabel,
} from "@/lib/format";
import { useScale } from "@/lib/scale";

function Stat({ name, value }: { name: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{name}</dt>
      <dd className="text-base tabular-nums">{value}</dd>
    </div>
  );
}

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

const COVERAGE_COLUMNS = [
  "Statement",
  "Frequency",
  "Coverage",
  "Filled",
  "Inferred 0",
  "Approximated",
  "No filing data",
  "Structural",
  "Rule rejected",
  "Not reported",
];

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
              <td className="num py-1 pr-4">{formatPercent(c.fraction)}</td>
              <td className="num py-1 pr-4">
                {c.filled} / {c.cells}
              </td>
              <td className="num py-1 pr-4">{c.by_provenance.zero_inferred}</td>
              <td className="num py-1 pr-4">{c.by_provenance.approximated}</td>
              <td className="num py-1 pr-4">{c.empty_by_cause.no_filing_data}</td>
              <td className="num py-1 pr-4">{c.empty_by_cause.structural}</td>
              <td className="num py-1 pr-4">{c.empty_by_cause.rule_rejected}</td>
              <td className="num py-1 pr-4">{c.empty_by_cause.not_reported}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
      <h2 className="mb-2 text-sm font-medium">Data gaps</h2>
      {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && <p className="text-destructive text-sm">Could not load the data gaps.</p>}
      {data && (
        <div className="flex flex-col gap-4">
          <div>
            <h3 className="text-muted-foreground mb-1 text-xs">Coverage</h3>
            {data.coverage.length === 0 ? (
              <p className="text-sm">No statement data yet.</p>
            ) : (
              <CoverageTable coverage={data.coverage} />
            )}
          </div>
          <RuleWarnings warnings={data.rule_warnings} />
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

export function Overview({ company }: { company: CompanyListItem }) {
  return (
    <div>
      <section aria-label="Key stats" className="border-border border-b px-4 py-3">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Stat name="Price" value={formatPrice(company.price)} />
          <Stat name="Market cap" value={formatCompact(company.market_cap)} />
          <Stat name="P/E" value={formatMultiple(company.pe)} />
          <Stat name="EV/EBITDA" value={formatMultiple(company.ev_ebitda)} />
          <Stat name="Revenue growth" value={formatPercent(company.revenue_growth)} />
        </dl>
      </section>
      <DataGaps ticker={company.ticker} />
      <Adjustments ticker={company.ticker} />
      <CorporateActions ticker={company.ticker} />
    </div>
  );
}
