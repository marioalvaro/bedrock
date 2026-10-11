import { useQuery } from "@tanstack/react-query";

import { cellDetailQueryOptions } from "@/api/statements";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { formatValue } from "@/lib/format";
import type { Scale } from "@/lib/scale";

export interface CellTarget {
  code: string;
  label: string;
  unit: string;
  fiscalYear: number;
  fiscalPeriod: string;
}

interface CellDetailSheetProps {
  ticker: string;
  cik: string;
  target: CellTarget | null;
  scale: Scale;
  onClose: () => void;
}

function filingUrl(cik: string, accessionNo: string): string {
  return `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${accessionNo.replaceAll("-", "")}/`;
}

function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="border-border border-b py-2">
      <div className="text-muted-foreground text-xs">{name}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function Body({
  ticker,
  cik,
  target,
  scale,
}: Omit<CellDetailSheetProps, "onClose"> & { target: CellTarget }) {
  const { data, isPending, isError } = useQuery(
    cellDetailQueryOptions(ticker, target.code, target.fiscalYear, target.fiscalPeriod),
  );

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (isError)
    return <p className="text-destructive p-4 text-sm">Could not load the cell details.</p>;

  const money = (value: string) => formatValue(value, target.unit, scale);

  return (
    <div className="overflow-y-auto px-4 pb-4">
      <Field name="Value">
        <span className="num">{data.value === null ? "—" : money(data.value)}</span>{" "}
        <span className="text-muted-foreground">({data.provenance ?? "no value"})</span>
      </Field>
      {data.source && (
        <Field name="Source tag">
          <code className="break-all">
            {data.source.taxonomy}:{data.source.concept}
          </code>{" "}
          <span className="text-muted-foreground">({data.source.unit})</span>
        </Field>
      )}
      {data.filing && (
        <Field name="Filing">
          {data.filing.form}{" "}
          <a
            className="underline"
            href={filingUrl(cik, data.filing.accession_no)}
            target="_blank"
            rel="noreferrer"
          >
            {data.filing.accession_no}
          </a>
          , filed {data.filing.filed_at}
        </Field>
      )}
      {data.derivation && (
        <Field name="Derivation">
          <div>{data.derivation.formula}</div>
          <ul className="text-muted-foreground">
            {data.derivation.inputs.map((input) => (
              <li key={`${input.code}-${input.fiscal_period}`}>
                {input.code} {input.fiscal_period}:{" "}
                <span className="num">{money(input.value)}</span>
              </li>
            ))}
          </ul>
        </Field>
      )}
      <Field name="Vintages">
        {data.vintages.length === 0 ? (
          <span className="text-muted-foreground">
            No filed vintages: computed from other cells.
          </span>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground text-xs">
              <tr>
                <th className="pr-3 font-normal">Filed</th>
                <th className="pr-3 font-normal">Form</th>
                <th className="pr-3 font-normal">Accession</th>
                <th className="num font-normal">Value</th>
              </tr>
            </thead>
            <tbody>
              {data.vintages.map((vintage) => (
                <tr key={vintage.accession_no}>
                  <td className="pr-3">{vintage.filed_at}</td>
                  <td className="pr-3">{vintage.form}</td>
                  <td className="pr-3">{vintage.accession_no}</td>
                  <td className="num">{money(vintage.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Field>
      <Field name="Adjustments">
        {data.adjustments.length === 0 ? (
          <span className="text-muted-foreground">Adjustments: none</span>
        ) : (
          <ul>
            {data.adjustments.map((adjustment) => (
              <li key={adjustment.reason}>
                {adjustment.category}: {adjustment.reason} ({adjustment.amount})
              </li>
            ))}
          </ul>
        )}
      </Field>
    </div>
  );
}

export function CellDetailSheet({ ticker, cik, target, scale, onClose }: CellDetailSheetProps) {
  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{target?.label}</SheetTitle>
          <SheetDescription>
            {ticker} · {target?.fiscalYear} {target?.fiscalPeriod}
          </SheetDescription>
        </SheetHeader>
        {target && <Body ticker={ticker} cik={cik} target={target} scale={scale} />}
      </SheetContent>
    </Sheet>
  );
}
