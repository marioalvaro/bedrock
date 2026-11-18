import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { companyQueryOptions } from "@/api/companies";
import type {
  CheckpointOut,
  EarningsReviewOut,
  FlagChangeOut,
  RangeOut,
} from "@/api/generated/types.gen";
import { reviewQueryOptions } from "@/api/review";
import { classificationText } from "@/features/backtest/backtestFormat";
import { formatFiscalPeriod, formatRatio, formatSignedPercent } from "@/lib/format";

import {
  CHECKPOINT_STATES,
  SEVERITY_WORDS,
  VERDICTS,
  errorClassName,
  formatRangeCell,
  formatReviewValue,
  restatedCapText,
  reviewHeading,
  snapshotHeading,
} from "./reviewFormat";

const DASH = "—";
const TABLE = "w-full text-sm";
const HEAD = "text-muted-foreground px-2 py-1 text-left font-normal whitespace-nowrap";
const NUM_HEAD = "text-muted-foreground px-2 py-1 text-right font-normal whitespace-nowrap";
const CELL = "px-2 py-1 whitespace-nowrap";
const NUM_CELL = "num px-2 py-1 text-right whitespace-nowrap";
const ROW = "border-border border-t";

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-border space-y-1 border-t px-4 py-3">
      <h2 className="text-sm font-medium">{title}</h2>
      {children}
    </section>
  );
}

const Muted = ({ children }: { children: ReactNode }) => (
  <p className="text-muted-foreground text-sm">{children}</p>
);

function RangeCell({ range, unit }: { range: RangeOut | null; unit: string }) {
  if (range === null) return <td className={NUM_CELL}>{DASH}</td>;
  const verdict = VERDICTS[range.verdict];
  return (
    <td className={NUM_CELL}>
      {formatRangeCell(range, unit)}
      <span className={`ml-2 ${verdict.className ?? ""}`}>{verdict.text}</span>
    </td>
  );
}

function KeyLines({ review }: { review: EarningsReviewOut }) {
  return (
    <Block title="Key lines">
      <div className="overflow-x-auto">
        <table aria-label="Key lines" className={TABLE}>
          <thead>
            <tr>
              <th className={HEAD}>Line</th>
              <th className={NUM_HEAD}>Actual</th>
              <th className={NUM_HEAD}>YoY</th>
              <th className={NUM_HEAD}>Forecast</th>
              <th className={NUM_HEAD}>Error</th>
              <th className={NUM_HEAD}>Bear–Bull</th>
              <th className={NUM_HEAD}>Consensus</th>
              <th className={NUM_HEAD}>Guidance</th>
            </tr>
          </thead>
          <tbody>
            {review.lines.map((line) => (
              <tr key={line.code} className={ROW}>
                <td className={CELL}>{line.label}</td>
                <td className={NUM_CELL}>{formatReviewValue(line.actual, line.unit)}</td>
                <td className={NUM_CELL}>{formatSignedPercent(line.yoy)}</td>
                <td className={NUM_CELL}>{formatReviewValue(line.forecast, line.unit)}</td>
                <td className={NUM_CELL}>
                  <span className={errorClassName(line)}>
                    {formatSignedPercent(line.pct_error)}
                  </span>
                </td>
                <td className={NUM_CELL}>
                  {line.low === null || line.high === null
                    ? DASH
                    : `${formatReviewValue(line.low, line.unit)}–${formatReviewValue(line.high, line.unit)}`}
                </td>
                <RangeCell range={line.consensus} unit={line.unit} />
                <RangeCell range={line.guidance} unit={line.unit} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Block>
  );
}

function Drivers({ review }: { review: EarningsReviewOut }) {
  const title = "Drivers that missed most";
  if (review.drivers.length === 0) {
    return (
      <Block title={title}>
        <Muted>{review.drivers_note ?? "No driver could be scored."}</Muted>
      </Block>
    );
  }
  return (
    <Block title={title}>
      <table aria-label={title} className={TABLE}>
        <thead>
          <tr>
            <th className={HEAD}>Driver</th>
            <th className={NUM_HEAD}>Forecast</th>
            <th className={NUM_HEAD}>Actual</th>
            <th className={NUM_HEAD}>Error</th>
            <th className={HEAD}>Source</th>
          </tr>
        </thead>
        <tbody>
          {review.drivers.map((driver) => (
            <tr key={driver.code} className={ROW}>
              <td className={CELL}>{driver.label}</td>
              <td className={NUM_CELL}>{formatReviewValue(driver.forecast, driver.unit)}</td>
              <td className={NUM_CELL}>{formatReviewValue(driver.actual, driver.unit)}</td>
              <td className={NUM_CELL}>{formatSignedPercent(driver.pct_error)}</td>
              <td className={CELL}>{driver.source ?? DASH}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {review.drivers_note && <Muted>{review.drivers_note}</Muted>}
    </Block>
  );
}

function Restated({ review }: { review: EarningsReviewOut }) {
  if (review.restated.length === 0) {
    return (
      <Block title="Restated">
        <Muted>Nothing was restated.</Muted>
      </Block>
    );
  }
  const cap = restatedCapText(review.restated.length, review.restated_total);
  return (
    <Block title="Restated">
      <table aria-label="Restated" className={TABLE}>
        <thead>
          <tr>
            <th className={HEAD}>Line</th>
            <th className={HEAD}>Period</th>
            <th className={NUM_HEAD}>Before</th>
            <th className={NUM_HEAD}>After</th>
            <th className={NUM_HEAD}>Change</th>
          </tr>
        </thead>
        <tbody>
          {review.restated.map((row) => (
            <tr
              key={`${row.statement}:${row.code}:${row.fiscal_year}:${row.fiscal_period}`}
              className={ROW}
            >
              <td className={CELL}>{row.label}</td>
              <td className={CELL}>{formatFiscalPeriod(row.fiscal_year, row.fiscal_period)}</td>
              <td className={NUM_CELL}>{formatReviewValue(row.before, row.unit)}</td>
              <td className={NUM_CELL}>{formatReviewValue(row.after, row.unit)}</td>
              <td className={NUM_CELL}>{formatSignedPercent(row.pct_change)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {cap && <Muted>{cap}</Muted>}
    </Block>
  );
}

const severity = (value: FlagChangeOut["before"]) =>
  value === null ? DASH : SEVERITY_WORDS[value];

function Flags({ review }: { review: EarningsReviewOut }) {
  if (review.flags.length === 0) {
    return (
      <Block title="Quality flags">
        <Muted>No flag changed.</Muted>
      </Block>
    );
  }
  return (
    <Block title="Quality flags">
      <table aria-label="Quality flags" className={TABLE}>
        <thead>
          <tr>
            <th className={HEAD}>Rule</th>
            <th className={HEAD}>Before → After</th>
            <th className={NUM_HEAD}>Value</th>
          </tr>
        </thead>
        <tbody>
          {review.flags.map((flag) => (
            <tr key={flag.code} className={ROW}>
              <td className={CELL}>{flag.label}</td>
              <td className={CELL}>
                {severity(flag.before)} → {severity(flag.after)}
              </td>
              <td className={NUM_CELL}>
                {formatRatio(flag.value_before, flag.unit)} →{" "}
                {formatRatio(flag.value_after, flag.unit)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Block>
  );
}

// "New" when the read before the report knew nothing (a company's first report).
const beforeWord = (checkpoint: CheckpointOut) =>
  checkpoint.previous_state === null || checkpoint.previous_state === "unknown"
    ? "New"
    : CHECKPOINT_STATES[checkpoint.previous_state].text;

function Thesis({ review, ticker }: { review: EarningsReviewOut; ticker: string }) {
  const notes = (
    <Link to={`/c/${ticker}/notes`} className="underline underline-offset-2">
      Notes
    </Link>
  );
  if (review.checkpoints.length === 0) {
    return (
      <Block title="Thesis">
        <Muted>No checkpoint changed. The checkpoints are on the {notes} tab.</Muted>
      </Block>
    );
  }
  return (
    <Block title="Thesis">
      <table aria-label="Thesis" className={TABLE}>
        <thead>
          <tr>
            <th className={HEAD}>Checkpoint</th>
            <th className={HEAD}>Before → After</th>
          </tr>
        </thead>
        <tbody>
          {review.checkpoints.map((checkpoint) => (
            <tr key={checkpoint.id} className={ROW}>
              <td className={CELL}>{checkpoint.label}</td>
              <td className={CELL}>
                {beforeWord(checkpoint)} → {CHECKPOINT_STATES[checkpoint.state].text}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Muted>All checkpoints are on the {notes} tab.</Muted>
    </Block>
  );
}

/** The Review tab (FR-ACC-06): the newest 10-K or 10-Q against the snapshot taken before it, the
 * consensus and the guidance; then what missed, what was restated and what changed state. */
export function ReviewView({ ticker }: { ticker: string }) {
  const { data: review, isPending } = useQuery(reviewQueryOptions(ticker));
  const { data: company } = useQuery(companyQueryOptions(ticker));

  if (!review) {
    return isPending ? (
      <p className="text-muted-foreground p-4 text-sm">Loading…</p>
    ) : (
      <p className="text-destructive p-4 text-sm">Could not load the review.</p>
    );
  }
  if (review.filing === null) {
    return <p className="text-muted-foreground p-4 text-sm">No 10-K or 10-Q is loaded yet.</p>;
  }

  const snapshot = review.snapshot;
  const modeDiffers =
    snapshot !== null &&
    company !== undefined &&
    snapshot.classification_mode !== company.classification_mode;

  return (
    <div>
      <div className="space-y-0.5 px-4 py-3 text-sm">
        <p className="font-medium">{reviewHeading(review)}</p>
        {snapshot ? (
          <p>
            <Link
              to={`/c/${ticker}/backtest?view=snapshots`}
              className="underline-offset-2 hover:underline"
            >
              {snapshotHeading(snapshot)}
            </Link>
            {modeDiffers && (
              <span className="text-muted-foreground ml-2">
                {classificationText(snapshot.classification_mode, company.classification_mode)}
              </span>
            )}
          </p>
        ) : (
          <p className="text-muted-foreground">No snapshot was taken before this filing.</p>
        )}
      </div>
      <KeyLines review={review} />
      <Drivers review={review} />
      <Restated review={review} />
      <Flags review={review} />
      <Thesis review={review} ticker={ticker} />
    </div>
  );
}
