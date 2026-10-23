import type {
  NoteLinkOut,
  NoteOut,
  SegmentsOut,
  SegmentPeriodOut,
} from "@/api/generated/types.gen";

// Shapes of GET …/segments, …/notes and …/notes/links.

export function segmentPeriods(): SegmentPeriodOut[] {
  return [
    {
      key: "FY2023",
      label: "FY2023",
      fiscal_year: 2023,
      fiscal_period: "FY",
      period_start: "2022-10-01",
      period_end: "2023-09-30",
      is_forecast: false,
    },
    {
      key: "FY2024",
      label: "FY2024",
      fiscal_year: 2024,
      fiscal_period: "FY",
      period_start: "2023-10-01",
      period_end: "2024-09-28",
      is_forecast: false,
    },
  ];
}

// AAPL: a geographic revenue block (Americas, Europe) with its Unallocated row, and one KPI.
export function segments(overrides: Partial<SegmentsOut> = {}): SegmentsOut {
  return {
    ticker: "AAPL",
    freq: "annual",
    periods: segmentPeriods(),
    blocks: [
      {
        dimension: "geo",
        metric: "revenue",
        series: [
          {
            id: 1,
            name: "Americas",
            metric: "revenue",
            unit: "USD",
            display_order: 1,
            values: [null, "167045000000"],
          },
          {
            id: 2,
            name: "Europe",
            metric: "revenue",
            unit: "USD",
            display_order: 2,
            values: ["94294000000", "101328000000"],
          },
        ],
        unallocated: [null, "122662000000"],
      },
      {
        dimension: "kpi",
        metric: null,
        series: [
          {
            id: 3,
            name: "Gross margin target",
            metric: "gm_target",
            unit: "pct",
            display_order: 3,
            values: [null, "0.46"],
          },
        ],
        unallocated: null,
      },
    ],
    ...overrides,
  };
}

export function note(overrides: Partial<NoteOut> = {}): NoteOut {
  return {
    id: 1,
    body_md: "Services **mix** is rising.",
    canonical_code: "revenue",
    metric_kind: null,
    metric_code: null,
    label: "Revenue",
    fiscal_year: 2024,
    fiscal_period: "FY",
    note_date: "2024-11-01",
    created_at: "2024-11-01T10:00:00Z",
    updated_at: "2024-11-01T10:00:00Z",
    ...overrides,
  };
}

// A link to a line (the default), a metric, or a period only; the period defaults to none.
export function noteLink(overrides: Partial<NoteLinkOut> = {}): NoteLinkOut {
  return {
    canonical_code: null,
    metric_kind: null,
    metric_code: null,
    fiscal_year: null,
    fiscal_period: null,
    count: 1,
    ...overrides,
  };
}

export function noteLinks(): NoteLinkOut[] {
  return [
    noteLink({ canonical_code: "revenue", fiscal_year: 2024, fiscal_period: "FY", count: 2 }),
    noteLink({ canonical_code: "sga" }),
    noteLink({ fiscal_year: 2024, fiscal_period: "Q4" }),
  ];
}
