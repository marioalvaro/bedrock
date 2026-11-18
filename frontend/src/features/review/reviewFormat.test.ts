import { describe, expect, it } from "vitest";

import { checkpointOut } from "@/test/checkpoints";
import { earningsReview, rangeOut, reviewLine } from "@/test/review";

import {
  CHECKPOINT_STATES,
  SEVERITY_WORDS,
  VERDICTS,
  checkpointValueText,
  errorClassName,
  formatDay,
  formatRangeCell,
  formatReviewValue,
  restatedCapText,
  reviewHeading,
  sinceLastFilingText,
  snapshotHeading,
} from "./reviewFormat";

const DASH = "—";

describe("dates", () => {
  it("formats an API date as it is, in any time zone", () => {
    expect(formatDay("2026-10-31")).toBe("Oct 31, 2026");
    expect(formatDay("2026-01-01")).toBe("Jan 1, 2026");
  });
});

describe("headings", () => {
  it("names the period, the form and its filing date", () => {
    expect(reviewHeading(earningsReview())).toBe("FY26 · 10-K filed Oct 31, 2026");
  });

  it("is empty with no filing", () => {
    expect(reviewHeading(earningsReview({ filing: null, period: null }))).toBe("");
  });

  it("names the snapshot's date and scenario", () => {
    const snapshot = earningsReview().snapshot!;
    expect(snapshotHeading(snapshot)).toMatch(/^Against the snapshot of Oct 3[01], 2026 \(Main\)$/);
  });
});

describe("formatReviewValue", () => {
  it("formats by unit", () => {
    expect(formatReviewValue("416161000000", "USD")).toBe("416.2B");
    expect(formatReviewValue("6.11", "USD/shares")).toBe("6.11");
    expect(formatReviewValue("0.469", "pct")).toBe("46.9%");
    expect(formatReviewValue("45", "days")).toBe("45");
    expect(formatReviewValue("1.5", "x")).toBe("1.5x");
    expect(formatReviewValue(null, "USD")).toBe(DASH);
  });
});

describe("formatRangeCell", () => {
  it("shows the range in the line's unit", () => {
    expect(formatRangeCell(rangeOut(), "USD")).toBe("410.0B–420.0B");
  });

  it("is a dash with no range", () => {
    expect(formatRangeCell(null, "USD")).toBe(DASH);
  });
});

describe("VERDICTS", () => {
  it("uses the Guidance tab's words and colors", () => {
    expect(VERDICTS.beat).toEqual({ text: "Beat", className: "text-positive" });
    expect(VERDICTS.in_range.text).toBe("In range");
    expect(VERDICTS.miss).toEqual({ text: "Miss", className: "text-negative" });
    expect(VERDICTS.pending.text).toBe("Pending");
  });
});

describe("errorClassName", () => {
  it("leaves an error inside the Bear–Bull range uncolored", () => {
    expect(errorClassName(reviewLine({ in_range: true, pct_error: "0.2" }))).toBeUndefined();
  });

  it("leaves an error with no range uncolored", () => {
    expect(errorClassName(reviewLine({ in_range: null, pct_error: "0.2" }))).toBeUndefined();
  });

  it("colors an error outside the range by its sign", () => {
    // pct_error = (forecast - actual) / |actual|: above zero the actual fell short.
    expect(errorClassName(reviewLine({ in_range: false, pct_error: "0.2" }))).toBe("text-negative");
    expect(errorClassName(reviewLine({ in_range: false, pct_error: "-0.2" }))).toBe(
      "text-positive",
    );
    expect(errorClassName(reviewLine({ in_range: false, pct_error: "0" }))).toBeUndefined();
    expect(errorClassName(reviewLine({ in_range: false, pct_error: null }))).toBeUndefined();
  });
});

describe("SEVERITY_WORDS", () => {
  it("names each flag severity", () => {
    expect(SEVERITY_WORDS.none).toBe("None");
    expect(SEVERITY_WORDS.warn).toBe("Warn");
    expect(SEVERITY_WORDS.alert).toBe("Alert");
  });
});

describe("restatedCapText", () => {
  it("says how many rows are shown when the list is capped", () => {
    expect(restatedCapText(50, 120)).toBe("Showing 50 of 120");
  });

  it("is null when every row is shown", () => {
    expect(restatedCapText(3, 3)).toBeNull();
    expect(restatedCapText(0, 0)).toBeNull();
  });
});

describe("checkpoint states", () => {
  it("uses the flag-severity colors", () => {
    expect(CHECKPOINT_STATES.holding).toEqual({ text: "Holding", className: "" });
    expect(CHECKPOINT_STATES.at_risk).toEqual({ text: "At risk", className: "flag-warn" });
    expect(CHECKPOINT_STATES.broken).toEqual({ text: "Broken", className: "flag-alert" });
    expect(CHECKPOINT_STATES.unknown).toEqual({
      text: "Unknown",
      className: "text-muted-foreground",
    });
  });

  it("says what the last filing changed", () => {
    expect(sinceLastFilingText(checkpointOut({ changed: false }))).toBe("");
    expect(sinceLastFilingText(checkpointOut({ changed: true, previous_state: "holding" }))).toBe(
      "was Holding",
    );
    expect(sinceLastFilingText(checkpointOut({ changed: true, previous_state: "at_risk" }))).toBe(
      "was At risk",
    );
  });

  it("calls a checkpoint new when the read before the report knew nothing", () => {
    expect(sinceLastFilingText(checkpointOut({ changed: true, previous_state: "unknown" }))).toBe(
      "New",
    );
  });
});

describe("checkpointValueText", () => {
  it("shows both sides as percents for a statement typed in percent", () => {
    expect(checkpointValueText(checkpointOut())).toBe("45.2% vs 44.0%");
  });

  it("shows plain numbers otherwise", () => {
    const cp = checkpointOut({ statement: "net_debt_to_ebitda <= 2", left: "1.5300", right: "2" });
    expect(checkpointValueText(cp)).toBe("1.53 vs 2");
  });

  it("shows large amounts compact", () => {
    const cp = checkpointOut({
      statement: "revenue > 400000000000",
      left: "416161000000",
      right: "400000000000",
    });
    expect(checkpointValueText(cp)).toBe("416.2B vs 400.0B");
  });

  it("keeps a negative sign on small numbers", () => {
    const cp = checkpointOut({
      statement: "yoy(shares_outstanding) < 0",
      left: "-0.0213",
      right: "0",
    });
    expect(checkpointValueText(cp)).toBe("-0.0213 vs 0");
  });

  it("shows a dash for a side the payload could not carry", () => {
    expect(checkpointValueText(checkpointOut({ left: null, right: "0.44" }))).toBe(
      `${DASH} vs 44.0%`,
    );
  });
});
