import { useQuery } from "@tanstack/react-query";

import { ratioCellQueryOptions, type AnalysisFreq } from "@/api/analysis";
import type { OperandOut, RatioCellOut, TermOut } from "@/api/generated/types.gen";
import type { Basis } from "@/api/statements";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { SubjectNotes } from "@/features/notes/SubjectNotesSheet";
import type { FiscalPeriod } from "@/api/context";
import { formatFiscalPeriod, formatInput, formatRatio, type RatioUnit } from "@/lib/format";

export interface RatioCellTarget {
  code: string;
  label: string;
  periodLabel: string; // the column's label, "FY2024" or "TTM Q3 FY24"
  fiscalYear: number;
  fiscalPeriod: string;
  ttm: boolean; // a TTM column carries no notes
}

interface RatioCellSheetProps {
  ticker: string;
  freq: AnalysisFreq;
  basis: Basis;
  target: RatioCellTarget | null;
  onClose: () => void;
}

/**
 * The details of one ratio value: how it was computed, as the statements' cell details do. The
 * formula as numerator ÷ denominator, every input with its value (a metric expanded into its own
 * inputs, an average showing both years), why an empty value is empty, and the cell's notes.
 * See erd/analysis.md "Ratio cell details (M3)".
 */
export function RatioCellSheet({ ticker, freq, basis, target, onClose }: RatioCellSheetProps) {
  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{target?.label}</SheetTitle>
          <SheetDescription>
            {ticker} · {target?.periodLabel}
          </SheetDescription>
        </SheetHeader>
        {target && <Details ticker={ticker} freq={freq} basis={basis} target={target} />}
      </SheetContent>
    </Sheet>
  );
}

function Details({
  ticker,
  freq,
  basis,
  target,
}: {
  ticker: string;
  freq: AnalysisFreq;
  basis: Basis;
  target: RatioCellTarget;
}) {
  const { data, isPending, isError } = useQuery(
    ratioCellQueryOptions(ticker, freq, basis, target.code, target.fiscalYear, target.fiscalPeriod),
  );

  return (
    <div className="space-y-3 overflow-y-auto px-4 pb-4 text-sm">
      {isPending && <p className="text-muted-foreground">Loading…</p>}
      {isError && <p className="text-destructive">Could not load the ratio details.</p>}
      {data && <Explanation cell={data} />}
      {!target.ttm && (
        <section aria-label="Notes" className="border-border border-t pt-3">
          <h3 className="mb-2 font-medium">Notes</h3>
          <SubjectNotes
            ticker={ticker}
            target={{
              kind: "ratio",
              code: target.code,
              label: target.label,
              period: {
                fiscalYear: target.fiscalYear,
                fiscalPeriod: target.fiscalPeriod as FiscalPeriod,
              },
            }}
          />
        </section>
      )}
    </div>
  );
}

function Explanation({ cell }: { cell: RatioCellOut }) {
  const unit = cell.unit as RatioUnit;
  return (
    <>
      <div>
        <div className="num text-2xl">{formatRatio(cell.value, unit)}</div>
        {cell.reason && <p className="text-muted-foreground">No value: {cell.reason}</p>}
      </div>
      <p className="text-muted-foreground">{cell.definition}</p>
      {cell.scale !== "1" && <p className="text-muted-foreground">× {cell.scale}</p>}
      {cell.caveat && <p className="text-muted-foreground">† {cell.caveat}</p>}
      <Operand title="Numerator" operand={cell.numerator} cell={cell} />
      {cell.denominator && <Operand title="Denominator" operand={cell.denominator} cell={cell} />}
    </>
  );
}

function Operand({
  title,
  operand,
  cell,
}: {
  title: string;
  operand: OperandOut;
  cell: RatioCellOut;
}) {
  const current = formatFiscalPeriod(cell.fiscal_year, cell.fiscal_period);
  const prior = formatFiscalPeriod(cell.fiscal_year - 1, cell.fiscal_period);
  return (
    <section aria-label={title} className="border-border border-t pt-3">
      <h3 className="font-medium">{title}</h3>
      <p className="text-muted-foreground text-xs">
        {operand.average ? `Average of ${current} and ${prior}: ` : ""}
        {operand.text}
      </p>
      {operand.average ? (
        <>
          <Terms heading={current} terms={operand.terms} />
          <Terms heading={prior} terms={operand.prior_terms} />
        </>
      ) : (
        <Terms terms={operand.terms} />
      )}
      {(operand.average || operand.terms.length > 1) && (
        <div className="flex justify-between pt-1">
          <span className="text-muted-foreground">{operand.average ? "Average" : "Total"}</span>
          <span className="num">{formatInput(operand.value, operandUnit(operand))}</span>
        </div>
      )}
    </section>
  );
}

// An operand's unit is its first term's (a formula mixes lines of one unit).
function operandUnit(operand: OperandOut): string {
  return operand.terms[0]?.unit ?? "USD";
}

function Terms({ heading, terms }: { heading?: string; terms: TermOut[] }) {
  return (
    <div className="pt-1">
      {heading && <div className="text-muted-foreground text-xs">{heading}</div>}
      <ul>
        {terms.map((term) => (
          <TermRow key={`${term.code}:${term.note ?? ""}`} term={term} depth={0} />
        ))}
      </ul>
    </div>
  );
}

function TermRow({ term, depth }: { term: TermOut; depth: number }) {
  const label = term.sign < 0 ? `− ${term.label}` : term.label;
  return (
    <li>
      <div className="flex justify-between gap-2" style={{ paddingLeft: depth * 16 }}>
        <span title={term.definition || undefined}>{label}</span>
        <span className="num">{formatInput(term.value, term.unit)}</span>
      </div>
      {term.definition && term.kind !== "line" && (
        <div className="text-muted-foreground text-xs" style={{ paddingLeft: depth * 16 }}>
          {term.definition}
        </div>
      )}
      {term.note && (
        <div className="text-muted-foreground text-xs" style={{ paddingLeft: depth * 16 }}>
          {term.note}
        </div>
      )}
      {term.children.length > 0 && (
        <ul>
          {term.children.map((child) => (
            <TermRow key={`${child.code}:${child.note ?? ""}`} term={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
