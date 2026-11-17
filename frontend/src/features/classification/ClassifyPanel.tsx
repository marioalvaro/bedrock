import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState } from "react";

import {
  classificationStatusQueryOptions,
  classificationsQueryOptions,
  invalidateClassificationViews,
  RUN_POLL_MS,
  useAnswerLine,
  useDecideClassification,
  useSetClassificationMode,
  useStartRun,
} from "@/api/classification";
import { companyErrorMessage, companyQueryOptions } from "@/api/companies";
import type {
  ClassificationOut,
  ClassificationsOut,
  ClassificationStatusOut,
  ClassifiedLineOut,
  UnclassifiedLineOut,
} from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { formatValue, scaleLabel } from "@/lib/format";
import { useScale } from "@/lib/scale";

import {
  answerActions,
  chosenClassifier,
  confidenceText,
  configuredClassifiers,
  modeLabel,
  proposalText,
  runNotice,
  runProgressText,
  statusText,
  type Mode,
} from "./classify";
import { ConfirmRunDialog } from "./ConfirmRunDialog";

const STATEMENT_NAMES: Record<UnclassifiedLineOut["statement"], string> = {
  IS: "Income statement",
  BS: "Balance sheet",
  CF: "Cash flow",
};
const MODES: Mode[] = ["off", "accepted", "all"];
const SELECT = "border-input h-7 rounded-lg border bg-transparent px-2 text-xs";
const HEAD = "py-1 pr-4 font-normal";
const OTHER = "Other"; // the Change select's value for "none of the rows"

// No classifier has a key: the M7b table of the newest filings' unclassified lines, unchanged.
function UnclassifiedTable({ lines }: { lines: UnclassifiedLineOut[] }) {
  const scale = useScale();
  if (lines.length === 0) return <p className="text-sm">No lines to classify.</p>;
  return (
    <>
      <p className="text-muted-foreground mb-1 text-xs">
        Map it in the company&apos;s override file, or list it under other_lines.
      </p>
      <div className="max-h-96 overflow-auto">
        <table aria-label="Lines to classify" className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground text-left text-xs">
              <th className={HEAD}>Statement</th>
              <th className={HEAD}>Label</th>
              <th className={HEAD}>Concept</th>
              <th className={`${HEAD} text-right`}>Latest value ({scaleLabel("USD", scale)})</th>
              <th className={HEAD}>Period end</th>
              <th className="py-1 font-normal">Filings</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr
                key={`${line.statement}:${line.taxonomy}:${line.concept}`}
                className="border-border border-b align-top"
              >
                <td className="py-1 pr-4 whitespace-nowrap">{STATEMENT_NAMES[line.statement]}</td>
                <td className="py-1 pr-4">{line.label}</td>
                <td className="py-1 pr-4 break-all">
                  {line.taxonomy}:{line.concept}
                </td>
                <td className="num py-1 pr-4">{formatValue(line.latest_value, "USD", scale)}</td>
                <td className="text-muted-foreground py-1 pr-4 whitespace-nowrap">
                  {line.latest_period_end}
                </td>
                <td className="text-muted-foreground py-1">{line.filings.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

interface AnswerCellsProps {
  line: ClassifiedLineOut;
  answer: ClassificationOut | undefined;
  onDecide: (id: number, status: "accepted" | "rejected") => void;
}

// The answer half of a row: classifier, proposal, confidence, status, Accept and Reject.
function AnswerCells({ line, answer, onDecide }: AnswerCellsProps) {
  if (!answer) {
    return (
      <>
        <td className="text-muted-foreground py-1 pr-4">—</td>
        <td className="text-muted-foreground py-1 pr-4">—</td>
        <td className="text-muted-foreground py-1 pr-4">—</td>
        <td className="text-muted-foreground py-1 pr-4">—</td>
        <td className="py-1 pr-4" />
      </>
    );
  }
  const actions = answerActions(answer);
  return (
    <>
      <td className="py-1 pr-4 break-all">{answer.classifier}</td>
      <td className="py-1 pr-4">{proposalText(answer.codes, line.candidates)}</td>
      <td className="num py-1 pr-4">{confidenceText(answer.confidence)}</td>
      <td className="py-1 pr-4">{statusText(answer.status)}</td>
      <td className="py-1 pr-4 whitespace-nowrap">
        {actions.accept && (
          <Button size="xs" variant="outline" onClick={() => onDecide(answer.id, "accepted")}>
            Accept
          </Button>
        )}{" "}
        {actions.reject && (
          <Button size="xs" variant="outline" onClick={() => onDecide(answer.id, "rejected")}>
            Reject
          </Button>
        )}
      </td>
    </>
  );
}

interface LinesTableProps {
  lines: ClassifiedLineOut[];
  onDecide: (id: number, status: "accepted" | "rejected") => void;
  onChange: (line: ClassifiedLineOut, codes: string[]) => void;
}

// One row per line with its first answer; each further answer is a sub-row with its classifier.
function LinesTable({ lines, onDecide, onChange }: LinesTableProps) {
  const scale = useScale();
  if (lines.length === 0) return <p className="text-sm">No lines to classify.</p>;
  return (
    <div className="max-h-96 overflow-auto">
      <table aria-label="Lines to classify" className="w-full text-sm">
        <thead>
          <tr className="text-muted-foreground text-left text-xs">
            <th className={HEAD}>Statement</th>
            <th className={HEAD}>Label</th>
            <th className={HEAD}>Concept</th>
            <th className={`${HEAD} text-right`}>Latest value ({scaleLabel("USD", scale)})</th>
            <th className={HEAD}>Classifier</th>
            <th className={HEAD}>Proposal</th>
            <th className={`${HEAD} text-right`}>Confidence</th>
            <th className={HEAD}>Status</th>
            <th className={HEAD}>
              <span className="sr-only">Actions</span>
            </th>
            <th className="py-1 font-normal">Change</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const key = `${line.statement}:${line.taxonomy}:${line.concept}`;
            const [first, ...rest] = line.answers;
            return (
              <Fragment key={key}>
                <tr className="border-border border-b align-top">
                  <td className="py-1 pr-4 whitespace-nowrap">{STATEMENT_NAMES[line.statement]}</td>
                  <td className="py-1 pr-4">{line.label}</td>
                  <td className="py-1 pr-4 break-all">
                    {line.taxonomy}:{line.concept}
                  </td>
                  <td className="num py-1 pr-4">{formatValue(line.latest_value, "USD", scale)}</td>
                  <AnswerCells line={line} answer={first} onDecide={onDecide} />
                  <td className="py-1">
                    <select
                      aria-label={`Change ${line.label}`}
                      className={SELECT}
                      value=""
                      onChange={(event) =>
                        onChange(line, event.target.value === OTHER ? [] : [event.target.value])
                      }
                    >
                      <option value="" disabled>
                        Change…
                      </option>
                      {line.candidates.map((candidate) => (
                        <option key={candidate.code} value={candidate.code}>
                          {candidate.label}
                        </option>
                      ))}
                      <option value={OTHER}>Other</option>
                    </select>
                  </td>
                </tr>
                {rest.map((answer) => (
                  <tr key={answer.id} className="row-sub border-border border-b align-top">
                    <td colSpan={4} />
                    <AnswerCells line={line} answer={answer} onDecide={onDecide} />
                    <td />
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface ConfiguredPanelProps {
  ticker: string;
  status: ClassificationStatusOut;
  configured: string[];
  pollMs: number;
}

function ConfiguredPanel({ ticker, status, configured, pollMs }: ConfiguredPanelProps) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<string | null>(null);
  // The company's source preselects its classifier; the list waits for it so that it is asked
  // for once. A failed company read falls back to the first configured classifier.
  const company = useQuery(companyQueryOptions(ticker));
  const source = company.data?.classification_source ?? null;
  const classifier = chosenClassifier(configured, picked, source) as string;
  const list = useQuery({
    ...classificationsQueryOptions(ticker, classifier, pollMs),
    enabled: !company.isPending,
  });
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = useStartRun(ticker);
  const decide = useDecideClassification(ticker);
  const answer = useAnswerLine(ticker);
  const setMode = useSetClassificationMode(ticker);

  const data: ClassificationsOut | undefined = list.data;

  // When the newest run stops running, its proposals can fill cells (under mode `all`) and its
  // tokens count against the budgets: refresh the company's views and the usage once.
  const running = data?.run?.status === "running";
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) void invalidateClassificationViews(queryClient, ticker);
    wasRunning.current = running;
  }, [running, queryClient, ticker]);

  const failed = (fallback: string) => (e: unknown) => setError(companyErrorMessage(e, fallback));

  function confirm() {
    if (!data || data.to_ask === null) return;
    setConfirming(false);
    setError(null);
    start.mutate(
      { classifier, confirm_lines: data.to_ask },
      { onError: failed("Could not start the run.") },
    );
  }

  function decideAnswer(id: number, next: "accepted" | "rejected") {
    setError(null);
    decide.mutate({ id, status: next }, { onError: failed("Could not save the decision.") });
  }

  function changeLine(line: ClassifiedLineOut, codes: string[]) {
    setError(null);
    answer.mutate(
      { statement: line.statement, taxonomy: line.taxonomy, concept: line.concept, codes },
      { onError: failed("Could not save the answer.") },
    );
  }

  function chooseMode(mode: Mode) {
    if (!data) return;
    setError(null);
    setMode.mutate(
      { mode, source: mode === "all" ? classifier : data.source },
      { onError: failed("Could not change the mode.") },
    );
  }

  const toAsk = data?.to_ask ?? 0;
  const notice = runNotice(data?.run ?? null);

  return (
    <div>
      <h3 className="text-muted-foreground mb-1 text-xs">
        Lines to classify{data ? ` (${data.lines.length})` : ""}
      </h3>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select
          aria-label="Classifier"
          className={SELECT}
          value={classifier}
          onChange={(event) => setPicked(event.target.value)}
        >
          {configured.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <Button
          size="xs"
          variant="outline"
          disabled={!data || toAsk === 0 || running || start.isPending}
          onClick={() => setConfirming(true)}
        >
          Classify {toAsk} lines
        </Button>
        {data && (
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            spacing={0}
            aria-label="Classification mode"
            value={data.mode}
            disabled={setMode.isPending}
            onValueChange={(value) => value && chooseMode(value as Mode)}
          >
            {MODES.map((mode) => (
              <ToggleGroupItem key={mode} value={mode}>
                {modeLabel(mode, status.min_confidence)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
        {running && data?.run && (
          <span className="text-muted-foreground text-xs tabular-nums">
            {runProgressText(data.run)}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="text-destructive mb-1 text-sm">
          {error}
        </p>
      )}
      {notice && <p className="text-destructive mb-1 text-sm">{notice}</p>}
      {list.isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {list.isError && (
        <p className="text-destructive text-sm">Could not load the lines to classify.</p>
      )}
      {data && <LinesTable lines={data.lines} onDecide={decideAnswer} onChange={changeLine} />}
      {data && (
        <ConfirmRunDialog
          open={confirming}
          classifier={classifier}
          lines={toAsk}
          estimate={data.estimate}
          status={status}
          onConfirm={confirm}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  );
}

interface ClassifyPanelProps {
  ticker: string;
  unclassified: UnclassifiedLineOut[]; // `/mapping-gaps`' list, shown when no classifier has a key
  pollMs?: number;
}

/** Lines to classify (FR-DATA-25, FR-DATA-26): ask a classifier from a confirmed click, review
 * its proposals, and choose what the company's statements use. */
export function ClassifyPanel({ ticker, unclassified, pollMs = RUN_POLL_MS }: ClassifyPanelProps) {
  const status = useQuery(classificationStatusQueryOptions());
  if (status.isPending) return <p className="text-muted-foreground text-sm">Loading…</p>;
  if (status.isError) {
    return <p className="text-destructive text-sm">Could not load the classifier status.</p>;
  }
  const configured = configuredClassifiers(status.data);
  if (configured.length === 0) {
    return (
      <div>
        <h3 className="text-muted-foreground mb-1 text-xs">
          Lines to classify ({unclassified.length})
        </h3>
        <p className="text-muted-foreground mb-1 text-xs">
          No classifier is configured. See Settings.
        </p>
        <UnclassifiedTable lines={unclassified} />
      </div>
    );
  }
  return (
    <ConfiguredPanel ticker={ticker} status={status.data} configured={configured} pollMs={pollMs} />
  );
}
