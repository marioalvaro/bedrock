import { useSearchParams } from "react-router";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import { AuditPanel } from "./AuditPanel";
import { BacktestPanel } from "./BacktestPanel";
import { SnapshotsPanel } from "./SnapshotsPanel";

const VIEW_PARAM = "view";
const VIEWS = [
  { value: "backtest", label: "Backtest" },
  { value: "snapshots", label: "Snapshots" },
  { value: "audit", label: "Audit log" },
] as const;
type View = (typeof VIEWS)[number]["value"];

interface BacktestViewProps {
  ticker: string;
}

/** The Backtest tab: the point-in-time backtest, the snapshots and the audit log (`?view`). */
export function BacktestView({ ticker }: BacktestViewProps) {
  const [params, setParams] = useSearchParams();
  const asked = params.get(VIEW_PARAM);
  const view: View = VIEWS.find(({ value }) => value === asked)?.value ?? "backtest";

  const pick = (next: string) =>
    setParams(
      (current) => {
        const updated = new URLSearchParams(current);
        updated.set(VIEW_PARAM, next);
        return updated;
      },
      { replace: true },
    );

  return (
    <div>
      <div className="border-border border-b px-4 py-2">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          aria-label="View"
          value={view}
          onValueChange={(value) => value && pick(value)}
        >
          {VIEWS.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value}>
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      {view === "backtest" && <BacktestPanel ticker={ticker} />}
      {view === "snapshots" && <SnapshotsPanel ticker={ticker} />}
      {view === "audit" && <AuditPanel ticker={ticker} />}
    </div>
  );
}
