// Display helpers of the Review tab and the thesis checkpoints (M7c, FR-ACC-06, FR-NOTE-03). Pure:
// every number, state and verdict comes from the backend; these only choose words and formats.
import type {
  CheckpointOut,
  EarningsReviewOut,
  FlagChangeOut,
  RangeOut,
  ReviewLineOut,
  ReviewSnapshotOut,
} from "@/api/generated/types.gen";
import { utcDate } from "@/features/backtest/backtestFormat";
import { formatCompact, formatInput, formatPercent } from "@/lib/format";

const DASH = "—";

/** An API date ("2026-10-31") as "Oct 31, 2026", read in UTC so no time zone shifts the day. */
export function formatDay(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-US", {
    dateStyle: "medium",
    timeZone: "UTC",
  });
}

/** "FY26 · 10-K filed Oct 31, 2026"; empty when nothing is loaded. */
export function reviewHeading(review: EarningsReviewOut): string {
  if (!review.filing || !review.period) return "";
  return `${review.period.label} · ${review.filing.form} filed ${formatDay(review.filing.filed_at)}`;
}

/** "Against the snapshot of Oct 31, 2026 (Main)", the day in the browser's time zone. */
export function snapshotHeading(snapshot: ReviewSnapshotOut): string {
  const day = utcDate(snapshot.created_at).toLocaleDateString("en-US", { dateStyle: "medium" });
  return `Against the snapshot of ${day} (${snapshot.scenario_name})`;
}

/** A line's or a driver's value by its unit: amounts compact ("416.2B"), the rest as ratios. */
export function formatReviewValue(value: string | null, unit: string): string {
  return formatInput(value, unit);
}

/** A consensus or guidance range in the line's unit ("410.0B–420.0B"); "—" with none. */
export function formatRangeCell(range: RangeOut | null, unit: string): string {
  if (range === null) return DASH;
  return `${formatReviewValue(range.low, unit)}–${formatReviewValue(range.high, unit)}`;
}

/** The Guidance tab's verdict words and colors. */
export const VERDICTS: Record<RangeOut["verdict"], { text: string; className?: string }> = {
  beat: { text: "Beat", className: "text-positive" },
  in_range: { text: "In range" },
  miss: { text: "Miss", className: "text-negative" },
  pending: { text: "Pending" },
};

/**
 * The Error cell's color: only outside the Bear–Bull range, by sign. `pct_error` is
 * (forecast − actual) / |actual|, so above zero the actual fell short of the forecast.
 */
export function errorClassName(line: ReviewLineOut): string | undefined {
  if (line.in_range !== false || line.pct_error === null) return undefined;
  const error = Number(line.pct_error);
  if (error > 0) return "text-negative";
  if (error < 0) return "text-positive";
  return undefined;
}

type Severity = NonNullable<FlagChangeOut["before"]>;

/** A QoE flag's severity as a word. */
export const SEVERITY_WORDS: Record<Severity, string> = {
  none: "None",
  warn: "Warn",
  alert: "Alert",
};

/** "Showing 50 of 120" when the restated rows are capped; null when all are shown. */
export function restatedCapText(shown: number, total: number): string | null {
  return total > shown ? `Showing ${shown} of ${total}` : null;
}

/** A checkpoint state's word and its flag-severity color class. */
export const CHECKPOINT_STATES: Record<
  CheckpointOut["state"],
  { text: string; className: string }
> = {
  holding: { text: "Holding", className: "" },
  at_risk: { text: "At risk", className: "flag-warn" },
  broken: { text: "Broken", className: "flag-alert" },
  unknown: { text: "Unknown", className: "text-muted-foreground" },
};

/**
 * What the newest report changed: "was Holding", "New" when the read before it knew nothing
 * (unknown, as for a company's first report), or "" when it changed nothing.
 */
export function sinceLastFilingText(checkpoint: CheckpointOut): string {
  const before = checkpoint.previous_state;
  if (!checkpoint.changed || before === null) return "";
  return before === "unknown" ? "New" : `was ${CHECKPOINT_STATES[before].text}`;
}

// A side of a checkpoint with no unit in the payload: amounts from a million up compact, the rest
// with up to 4 decimals.
function plainNumber(value: string): string {
  const number = Number(value);
  if (Math.abs(number) >= 1e6) return formatCompact(value);
  return String(Number(number.toFixed(4)));
}

/**
 * "45.2% vs 44.0%": the two sides at the point evaluated. The payload carries no unit, so a
 * statement typed with "%" shows both sides as percents and any other as plain numbers.
 */
export function checkpointValueText(checkpoint: CheckpointOut): string {
  const percent = checkpoint.statement.includes("%");
  const side = (value: string | null) =>
    value === null ? DASH : percent ? formatPercent(value) : plainNumber(value);
  return `${side(checkpoint.left)} vs ${side(checkpoint.right)}`;
}
