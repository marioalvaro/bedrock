import type {
  AsReportedLineOut,
  AsReportedOut,
  ClassificationOut,
  ClassificationRunOut,
  ClassificationsOut,
  ClassificationStatusOut,
  ClassifiedLineOut,
} from "@/api/generated/types.gen";

// GET /classification/status: one classifier with a key, two without.
export function classifierStatus(
  overrides: Partial<ClassificationStatusOut> = {},
): ClassificationStatusOut {
  return {
    classifiers: [
      { name: "claude:claude-haiku-5-5", configured: true },
      { name: "claude:claude-sonnet-5-5", configured: false },
      { name: "openrouter:openai/gpt-6-luna", configured: true },
      { name: "jev:jev-latest", configured: false },
    ],
    daily_tokens: 200000,
    monthly_tokens: 2000000,
    used_today: 12500,
    used_month: 480000,
    cost_month_usd: "0.412300",
    max_lines_per_run: 300,
    min_confidence: 0.9,
    ...overrides,
  };
}

export const noClassifierStatus = (): ClassificationStatusOut =>
  classifierStatus({
    classifiers: classifierStatus().classifiers.map((c) => ({ ...c, configured: false })),
    used_today: 0,
    used_month: 0,
    cost_month_usd: "0.000000",
  });

export function classificationRun(
  overrides: Partial<ClassificationRunOut> = {},
): ClassificationRunOut {
  return {
    id: 1,
    classifier: "claude:claude-haiku-5-5",
    status: "done",
    started_at: "2026-11-17T10:00:00",
    finished_at: "2026-11-17T10:00:20",
    lines_asked: 2,
    lines_answered: 2,
    input_tokens: 1200,
    output_tokens: 300,
    cost_usd: "0.002700",
    error: null,
    ...overrides,
  };
}

export function answerOut(overrides: Partial<ClassificationOut> = {}): ClassificationOut {
  return {
    id: 11,
    classifier: "claude:claude-haiku-5-5",
    codes: ["sga"],
    confidence: "0.9500",
    status: "proposed",
    ...overrides,
  };
}

export function classifiedLine(overrides: Partial<ClassifiedLineOut> = {}): ClassifiedLineOut {
  return {
    statement: "IS",
    taxonomy: "aapl",
    concept: "MarketingExpense",
    label: "Marketing expense",
    latest_value: "1250000000",
    latest_period_end: "2025-09-27",
    block: { code: "operating_expenses", label: "Operating expenses" },
    candidates: [
      { code: "sga", label: "SG&A" },
      { code: "rnd", label: "Research and development" },
    ],
    effective: null,
    answers: [],
    ...overrides,
  };
}

export function classifications(overrides: Partial<ClassificationsOut> = {}): ClassificationsOut {
  return {
    mode: "off",
    source: null,
    run: null,
    to_ask: 2,
    estimate: { input_tokens: 1200, output_tokens: 300, cost_usd: "0.002700" },
    lines: [
      classifiedLine(),
      classifiedLine({
        statement: "CF",
        taxonomy: "us-gaap",
        concept: "OtherNoncashIncomeExpense",
        label: "Other",
        latest_value: "-230000000",
        block: null,
        candidates: [{ code: "other_operating_cf", label: "Other operating items" }],
      }),
    ],
    ...overrides,
  };
}

export function asReportedLine(overrides: Partial<AsReportedLineOut> = {}): AsReportedLineOut {
  return {
    position: 1,
    taxonomy: "us-gaap",
    concept: "CashAndCashEquivalentsAtCarryingValue",
    label: "Cash and cash equivalents",
    unit: "USD",
    depth: 1,
    is_total: false,
    in_tree: true,
    kind: "mapped",
    codes: [{ code: "cash", label: "Cash and equivalents" }],
    block: { code: "total_current_assets", label: "Total current assets" },
    values: ["29943000000", "29965000000"],
    foots: [null, null],
    missing_children: [],
    ...overrides,
  };
}

// GET …/as-reported?statement=BS: AAPL's newest 10-K balance sheet, cut to a few lines.
export function asReportedBalanceSheet(overrides: Partial<AsReportedOut> = {}): AsReportedOut {
  const tenK = {
    accession_no: "0000320193-25-000079",
    form: "10-K",
    filed_at: "2025-10-31",
    period_end: "2025-09-27",
  };
  return {
    filing: tenK,
    filings: [
      {
        accession_no: "0000320193-26-000020",
        form: "10-Q",
        filed_at: "2026-01-30",
        period_end: "2025-12-27",
      },
      tenK,
    ],
    periods: [
      { start: null, end: "2025-09-27" },
      { start: null, end: "2024-09-28" },
    ],
    foots: false,
    lines: [
      asReportedLine(),
      asReportedLine({
        position: 2,
        concept: "AccountsReceivableNetCurrent",
        label: "Accounts receivable, net",
        codes: [{ code: "receivables", label: "Receivables" }],
        values: ["39777000000", "33410000000"],
      }),
      asReportedLine({
        position: 3,
        taxonomy: "aapl",
        concept: "VendorNonTradeReceivables",
        label: "Vendor non-trade receivables",
        kind: "open",
        codes: [],
        values: ["33180000000", "32833000000"],
      }),
      asReportedLine({
        position: 4,
        concept: "OtherAssetsCurrent",
        label: "Other current assets",
        kind: "other",
        codes: [{ code: "receivables", label: "Receivables" }],
        values: ["14585000000", "14287000000"],
      }),
      asReportedLine({
        position: 5,
        concept: "AssetsCurrent",
        label: "Total current assets",
        depth: 0,
        is_total: true,
        codes: [{ code: "total_current_assets", label: "Total current assets" }],
        block: null,
        values: ["147957000000", "152987000000"],
        foots: [false, true],
      }),
      asReportedLine({
        position: 6,
        concept: "CommitmentsAndContingencies",
        label: "Commitments and contingencies",
        depth: 0,
        in_tree: false,
        kind: "other",
        codes: [],
        block: null,
        values: [null, null],
      }),
    ],
    ...overrides,
  };
}
