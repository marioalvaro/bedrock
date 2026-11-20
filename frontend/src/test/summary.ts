import type {
  CompanySummaryOut,
  SummaryMetricOut,
  SummaryYearOut,
} from "@/api/generated/types.gen";

const years = (values: (string | null)[]): SummaryYearOut[] =>
  values.map((value, at) => ({ fiscal_year: 2021 + at, value }));

function metric(
  code: string,
  label: string,
  unit: SummaryMetricOut["unit"],
  values: (string | null)[],
  yoy: string | null,
): SummaryMetricOut {
  return { code, label, unit, years: years(values), latest: values.at(-1) ?? null, yoy };
}

/** GET /companies/AAPL/summary, shaped like the recorded AAPL fixtures (FY2021–FY2025). */
export function companySummary(overrides: Partial<CompanySummaryOut> = {}): CompanySummaryOut {
  return {
    ticker: "AAPL",
    metrics: [
      metric(
        "revenue",
        "Revenue",
        "USD",
        ["365817000000", "394328000000", "383285000000", "391035000000", "416161000000"],
        "0.064255",
      ),
      metric(
        "gross_margin",
        "Gross margin",
        "pct",
        ["0.417800", "0.433100", "0.441300", "0.462100", "0.469100"],
        "0.007000",
      ),
      metric(
        "operating_margin",
        "Operating margin",
        "pct",
        ["0.297800", "0.302900", "0.298200", "0.315100", "0.319700"],
        "0.004600",
      ),
      metric(
        "fcf_margin",
        "FCF margin",
        "pct",
        ["0.254000", "0.253000", "0.261000", "0.276000", "0.237000"],
        "-0.039000",
      ),
      metric(
        "roic",
        "Return on invested capital",
        "pct",
        [null, "0.553000", "0.548000", "0.564000", "0.598000"],
        "0.034000",
      ),
      metric(
        "eps_diluted",
        "EPS (diluted)",
        "USD/shares",
        ["5.61", "6.11", "6.13", "6.08", "7.46"],
        "0.226974",
      ),
      metric(
        "net_debt_to_ebitda",
        "Net debt / EBITDA",
        "x",
        ["0.42", "0.39", "0.36", "0.27", "0.18"],
        "-0.09",
      ),
    ],
    flags: [
      {
        code: "accruals_ratio",
        label: "Accruals ratio",
        severity: "alert",
        value: "0.123400",
        unit: "pct",
        period_label: "FY26",
      },
      {
        code: "receivables_vs_revenue",
        label: "Receivables growing faster than revenue",
        severity: "warn",
        value: "1.8",
        unit: "x",
        period_label: "FY26",
      },
    ],
    valuation: {
      scenario_id: 2,
      scenario_name: "Base thesis",
      price: "231.40",
      price_date: "2026-10-07",
      low: "180.25",
      high: "265.10",
      base: "242.00",
      upside: "0.045808",
    },
    notes: [
      { id: 9, excerpt: "Services margin keeps widening.", created_at: "2026-11-02T10:00:00Z" },
      { id: 7, excerpt: "Buyback pace slowed in Q3.", created_at: "2026-10-20T10:00:00Z" },
      {
        id: 4,
        excerpt: "Thesis: installed base monetisation.",
        created_at: "2026-09-01T10:00:00Z",
      },
    ],
    forecast: {
      scenario_id: 2,
      scenario_name: "Base thesis",
      updated_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
      last_snapshot_at: new Date(Date.now() - 5 * 3_600_000).toISOString(),
      newest_filing_date: "2026-10-31",
      stale: false,
    },
    warnings: [],
    ...overrides,
  };
}
