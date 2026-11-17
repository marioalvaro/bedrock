import type {
  AsReportedFilingOut,
  AsReportedLineOut,
  AsReportedOut,
  AsReportedPeriodOut,
} from "@/api/generated/types.gen";

// M7d S5: the As reported view's rows and columns (docs/erd/face-tree.md "As reported"). Pure:
// values stay the API's decimal strings, and the grid formats them at render time.

export const NOT_FOOTING_TITLE = "Does not equal the sum of its lines in this filing";

export interface BedrockRowText {
  text: string;
  muted: boolean;
}

export interface AsReportedRow {
  id: string; // the line's presentation position, unique within one statement of one filing
  label: string;
  depth: number;
  isTotal: boolean;
  unit: string;
  values: Record<string, string | null>;
  notFooting: Record<string, boolean>; // true where a total does not equal the sum of its lines
  bedrock: BedrockRowText;
}

// An instant reads as its end date; a duration as "start – end".
export function periodHeader(period: AsReportedPeriodOut): string {
  return period.start === null ? period.end : `${period.start} – ${period.end}`;
}

// The column ids of the face periods, aligned with `values` and `foots`.
export function periodKeys(periods: readonly AsReportedPeriodOut[]): string[] {
  return periods.map((_, index) => `p${index}`);
}

// Where the line lands among Bedrock's rows. A mapped line names its rows and an open line says
// so wherever they sit; a line in a residual outside the calculation tree shows a muted dash.
export function bedrockRowText(line: AsReportedLineOut): BedrockRowText {
  const labels = line.codes.map((ref) => ref.label);
  if (line.kind === "mapped") return { text: labels.join(", "), muted: false };
  if (line.kind === "open") return { text: "Not classified", muted: false };
  if (!line.in_tree) return { text: "—", muted: true };
  return { text: labels.length > 0 ? `Other: ${labels.join(", ")}` : "Other", muted: false };
}

export function filingOptionText(filing: AsReportedFilingOut): string {
  return `${filing.form} · period ended ${filing.period_end} · filed ${filing.filed_at}`;
}

export function toAsReportedRows(view: AsReportedOut): AsReportedRow[] {
  const keys = periodKeys(view.periods);
  return view.lines.map((line) => ({
    id: String(line.position),
    label: line.label,
    depth: line.depth,
    isTotal: line.is_total,
    unit: line.unit ?? "USD",
    values: Object.fromEntries(keys.map((key, index) => [key, line.values[index] ?? null])),
    notFooting: Object.fromEntries(keys.map((key, index) => [key, line.foots[index] === false])),
    bedrock: bedrockRowText(line),
  }));
}
