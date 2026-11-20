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
import { Td, Th } from "@/components/ui/table";
import { classificationText } from "@/features/backtest/backtestFormat";
import {
  formatFiscalPeriod,
  formatInput,
  formatRatio,
  formatSignedPercent,
  DASH,
} from "@/lib/format";

import {
  CHECKPOINT_STATES,
  SEVERITY_WORDS,
  VERDICTS,
  errorClassName,
  formatRangeCell,
  restatedCapText,
  reviewHeading,
  snapshotHeading,
} from "./reviewFormat";

const TABLE = "w-full text-sm";
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
  if (range === null) return <Td numeric>{DASH}</Td>;
  const verdict = VERDICTS[range.verdict];
  return (
    <Td numeric>
      {formatRangeCell(range, unit)}
      <span className={`ml-2 ${verdict.className ?? ""}`}>{verdict.text}</span>
    </Td>
  );
}

function KeyLines({ review }: { review: EarningsReviewOut }) {
  return (
    <Block title="Key lines">
      <div className="overflow-x-auto">
        <table aria-label="Key lines" className={TABLE}>
          <thead>
            <tr>
              <Th>Line</Th>
              <Th numeric>Actual</Th>
              <Th numeric>YoY</Th>
              <Th numeric>Forecast</Th>
              <Th numeric>Error</Th>
              <Th numeric>Bear–Bull</Th>
              <Th numeric>Consensus</Th>
              <Th numeric>Guidance</Th>
            </tr>
          </thead>
          <tbody>
            {review.lines.map((line) => (
              <tr key={line.code} className={ROW}>
                <Td>{line.label}</Td>
                <Td numeric>{formatInput(line.actual, line.unit)}</Td>
                <Td numeric>{formatSignedPercent(line.yoy)}</Td>
                <Td numeric>{formatInput(line.forecast, line.unit)}</Td>
                <Td numeric>
                  <span className={errorClassName(line)}>
                    {formatSignedPercent(line.pct_error)}
                  </span>
                </Td>
                <Td numeric>
                  {line.low === null || line.high === null
                    ? DASH
                    : `${formatInput(line.low, line.unit)}–${formatInput(line.high, line.unit)}`}
                </Td>
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
            <Th>Driver</Th>
            <Th numeric>Forecast</Th>
            <Th numeric>Actual</Th>
            <Th numeric>Error</Th>
            <Th>Source</Th>
          </tr>
        </thead>
        <tbody>
          {review.drivers.map((driver) => (
            <tr key={driver.code} className={ROW}>
              <Td>{driver.label}</Td>
              <Td numeric>{formatInput(driver.forecast, driver.unit)}</Td>
              <Td numeric>{formatInput(driver.actual, driver.unit)}</Td>
              <Td numeric>{formatSignedPercent(driver.pct_error)}</Td>
              <Td>{driver.source ?? DASH}</Td>
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
            <Th>Line</Th>
            <Th>Period</Th>
            <Th numeric>Before</Th>
            <Th numeric>After</Th>
            <Th numeric>Change</Th>
          </tr>
        </thead>
        <tbody>
          {review.restated.map((row) => (
            <tr
              key={`${row.statement}:${row.code}:${row.fiscal_year}:${row.fiscal_period}`}
              className={ROW}
            >
              <Td>{row.label}</Td>
              <Td>{formatFiscalPeriod(row.fiscal_year, row.fiscal_period)}</Td>
              <Td numeric>{formatInput(row.before, row.unit)}</Td>
              <Td numeric>{formatInput(row.after, row.unit)}</Td>
              <Td numeric>{formatSignedPercent(row.pct_change)}</Td>
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
            <Th>Rule</Th>
            <Th>Before → After</Th>
            <Th numeric>Value</Th>
          </tr>
        </thead>
        <tbody>
          {review.flags.map((flag) => (
            <tr key={flag.code} className={ROW}>
              <Td>{flag.label}</Td>
              <Td>
                {severity(flag.before)} → {severity(flag.after)}
              </Td>
              <Td numeric>
                {formatRatio(flag.value_before, flag.unit)} →{" "}
                {formatRatio(flag.value_after, flag.unit)}
              </Td>
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
            <Th>Checkpoint</Th>
            <Th>Before → After</Th>
          </tr>
        </thead>
        <tbody>
          {review.checkpoints.map((checkpoint) => (
            <tr key={checkpoint.id} className={ROW}>
              <Td>{checkpoint.label}</Td>
              <Td>
                {beforeWord(checkpoint)} → {CHECKPOINT_STATES[checkpoint.state].text}
              </Td>
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
