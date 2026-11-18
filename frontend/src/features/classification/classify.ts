import type {
  ClassificationOut,
  ClassificationRunOut,
  ClassificationStatusOut,
  EstimateOut,
  RowRefOut,
} from "@/api/generated/types.gen";

// M7d S5: the texts and choices of the classify panel (docs/erd/face-tree.md "Lines to
// classify"). Pure; every figure comes from the API as is.

export type Mode = "off" | "accepted" | "all";
export type AnswerStatus = ClassificationOut["status"];

// A proposal by its rows: one label, "Other" for none, "Combined: a + b" for several.
export function proposalText(codes: readonly string[], candidates: readonly RowRefOut[]): string {
  const labels = codes.map((code) => candidates.find((c) => c.code === code)?.label ?? code);
  if (labels.length === 0) return "Other";
  if (labels.length === 1) return labels[0] as string;
  return `Combined: ${labels.join(" + ")}`;
}

// The API's confidence (a decimal string in [0, 1]) as a whole percentage.
export function confidenceText(confidence: string): string {
  return `${Math.round(Number(confidence) * 100)}%`;
}

const STATUS_TEXT: Record<AnswerStatus, string> = {
  proposed: "Proposed",
  accepted: "Accepted",
  rejected: "Rejected",
};

export function statusText(status: AnswerStatus): string {
  return STATUS_TEXT[status];
}

// What an answer row offers; Change is per line, not per answer.
export function answerActions(answer: ClassificationOut): { accept: boolean; reject: boolean } {
  return { accept: answer.status !== "accepted", reject: answer.status !== "rejected" };
}

export function modeLabel(mode: Mode, minConfidence: number): string {
  if (mode === "off") return "Off";
  if (mode === "accepted") return "Accepted only";
  return `All above ${Math.round(minConfidence * 100)}%`;
}

// Who receives the lines a run sends, by the registry name's prefix.
const PROVIDERS: Record<string, string> = {
  claude: "Anthropic",
  jev: "Typesafe",
  openrouter: "OpenRouter",
};

export function providerName(classifier: string): string {
  const prefix = classifier.split(":")[0] ?? classifier;
  return PROVIDERS[prefix] ?? prefix;
}

export function configuredClassifiers(status: ClassificationStatusOut): string[] {
  return status.classifiers.filter((c) => c.configured).map((c) => c.name);
}

// The user's pick, else the company's source, else the first configured classifier; a name
// that is not configured is never chosen.
export function chosenClassifier(
  configured: readonly string[],
  picked: string | null,
  source: string | null,
): string | null {
  for (const name of [picked, source]) {
    if (name !== null && configured.includes(name)) return name;
  }
  return configured[0] ?? null;
}

export function tokensLeft(status: ClassificationStatusOut): { today: number; month: number } {
  return {
    today: Math.max(0, status.daily_tokens - status.used_today),
    month: Math.max(0, status.monthly_tokens - status.used_month),
  };
}

export function runProgressText(run: ClassificationRunOut): string {
  return `Classifying… ${run.lines_answered} of ${run.lines_asked}`;
}

// What the newest run reports, shown above the table: the reason of a stopped or failed run, and
// the note of a finished run whose lines did not all get a usable answer; null otherwise.
export function runNotice(run: ClassificationRunOut | null): string | null {
  if (run === null || run.status === "running") return null;
  if (run.status === "done") return run.error ? `The last run finished. ${run.error}` : null;
  const head = `The last run ${run.status}.`;
  return run.error ? `${head} ${run.error}` : head;
}

// The API's USD cost (a decimal string): to the cent from a cent up, else to four places, so a
// run of a fraction of a cent does not read as free.
export function costText(cost: string): string {
  const amount = Number(cost);
  return `$${amount.toFixed(amount === 0 || amount >= 0.01 ? 2 : 4)}`;
}

export function tokensText(tokens: number): string {
  return tokens.toLocaleString("en-US");
}

export function estimateText(estimate: EstimateOut): string {
  return `${tokensText(estimate.input_tokens)} in + ${tokensText(estimate.output_tokens)} out`;
}
