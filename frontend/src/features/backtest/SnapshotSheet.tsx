import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { snapshotQueryOptions } from "@/api/accountability";
import { companyQueryOptions } from "@/api/companies";
import type { SnapshotCaseOut, SnapshotOut } from "@/api/generated/types.gen";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { formatPrice, formatSignedPercent, formatValue, scaleLabel } from "@/lib/format";
import { useScale, type Scale } from "@/lib/scale";

import { classificationText, formatLocalTime } from "./backtestFormat";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const HEAD = "px-2 py-1 text-right font-medium";
const CELL = "px-2 py-1 text-right";
const DEFAULT_LINE = "revenue";

type CaseCode = SnapshotCaseOut["case"];
const CASE_TOGGLES: { value: CaseCode; label: string }[] = [
  { value: "base", label: "Base" },
  { value: "bull", label: "Bull" },
  { value: "bear", label: "Bear" },
];

const inRangeText = (inRange: boolean | null) => (inRange === null ? "—" : inRange ? "Yes" : "No");

interface CaseBodyProps {
  frozen: SnapshotCaseOut;
  picked: string;
  onPick: (code: string) => void;
  scale: Scale;
}

function CaseBody({ frozen, picked, onPick, scale }: CaseBodyProps) {
  const line =
    frozen.lines.find((l) => l.code === picked) ??
    frozen.lines.find((l) => l.code === DEFAULT_LINE) ??
    frozen.lines[0];
  if (frozen.error) return <p className="text-destructive text-sm">{frozen.error}</p>;
  return (
    <>
      {line && (
        <>
          <select
            aria-label="Line"
            className={SELECT}
            value={line.code}
            onChange={(e) => onPick(e.target.value)}
          >
            {frozen.lines.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          <div className="overflow-x-auto">
            <table aria-label="Forecast against actual" className="num w-full text-sm">
              <caption className="text-muted-foreground mb-1 text-left text-xs">
                {line.label} · {scaleLabel(line.unit, scale)}
              </caption>
              <thead className="text-muted-foreground">
                <tr>
                  <th className="px-2 py-1 text-left font-medium">Period</th>
                  <th className={HEAD}>Forecast</th>
                  <th className={HEAD}>Actual</th>
                  <th className={HEAD}>Error</th>
                  <th className={HEAD}>In range</th>
                </tr>
              </thead>
              <tbody>
                {line.cells.map((cell) => (
                  <tr key={cell.label} className="border-border border-t">
                    <th scope="row" className="px-2 py-1 text-left font-medium">
                      {cell.label}
                    </th>
                    <td className={CELL}>{formatValue(cell.forecast, line.unit, scale)}</td>
                    <td className={CELL}>{formatValue(cell.actual, line.unit, scale)}</td>
                    <td className={CELL}>{formatSignedPercent(cell.pct_error)}</td>
                    <td className={CELL}>{inRangeText(cell.in_range)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {frozen.warnings.length > 0 && (
        <ul className="text-muted-foreground space-y-0.5 text-sm">
          {frozen.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {frozen.valuation.length > 0 && (
        <table aria-label="Valuations" className="num w-full text-sm">
          <thead className="text-muted-foreground">
            <tr>
              <th className="px-2 py-1 text-left font-medium">Method</th>
              <th className={HEAD}>Value per share</th>
              <th className={HEAD}>Upside</th>
            </tr>
          </thead>
          <tbody>
            {frozen.valuation.map((result) => (
              <tr key={result.key} className="border-border border-t">
                <th scope="row" className="px-2 py-1 text-left font-medium">
                  {result.label}
                </th>
                {result.error ? (
                  <td colSpan={2} className="text-muted-foreground px-2 py-1 text-left">
                    {result.error}
                  </td>
                ) : (
                  <>
                    <td className={CELL}>{formatPrice(result.value_per_share)}</td>
                    <td className={CELL}>{formatSignedPercent(result.upside)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

interface SnapshotSheetProps {
  ticker: string;
  snapshot: SnapshotOut;
  onClose: () => void;
}

/** One frozen scenario: each case's forecast against the actuals so far, warnings and valuations. */
export function SnapshotSheet({ ticker, snapshot, onClose }: SnapshotSheetProps) {
  const scale = useScale();
  const { data, isPending } = useQuery(snapshotQueryOptions(ticker, snapshot.id));
  // Optional: without the company, the mode is shown with no comparison.
  const { data: company } = useQuery(companyQueryOptions(ticker));
  const [caseCode, setCaseCode] = useState<CaseCode>("base");
  const [picked, setPicked] = useState(DEFAULT_LINE);
  const frozen = data?.cases.find((c) => c.case === caseCode);

  return (
    <Sheet open onOpenChange={(next) => !next && onClose()}>
      <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>
            {snapshot.scenario_name} · {formatLocalTime(snapshot.created_at)}
          </SheetTitle>
          <SheetDescription>
            {snapshot.note ?? `Data as of ${snapshot.data_as_of ?? "—"}`}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-4">
          <p className="text-muted-foreground text-xs">
            {classificationText(snapshot.classification_mode, company?.classification_mode)}
          </p>
          {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
          {!data && !isPending && (
            <p className="text-destructive text-sm">Could not load the snapshot.</p>
          )}
          {data && (
            <>
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                spacing={0}
                aria-label="Case"
                value={caseCode}
                onValueChange={(value) => value && setCaseCode(value as CaseCode)}
              >
                {CASE_TOGGLES.map(({ value, label }) => (
                  <ToggleGroupItem key={value} value={value}>
                    {label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              {frozen && (
                <CaseBody frozen={frozen} picked={picked} onPick={setPicked} scale={scale} />
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
