import type {
  CompsOut,
  CompsRowOut,
  CompsSetOut,
  GuidanceEntryOut,
  GuidanceOut,
  MetricChoiceOut,
  NoteLinkOut,
  NoteOut,
  PeerSuggestionOut,
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

// Shapes of GET …/comps-sets, …/peer-suggestions and …/comps-sets/{id}/comparison.

export function compsSets(): CompsSetOut[] {
  return [
    {
      id: 1,
      name: "Hardware & industrials",
      members: [
        { ticker: "COST", name: "Costco Wholesale Corp" },
        { ticker: "DE", name: "Deere & Co" },
      ],
    },
    { id: 2, name: "Software", members: [{ ticker: "MSFT", name: "Microsoft Corp" }] },
  ];
}

export function peerSuggestions(): PeerSuggestionOut[] {
  return [
    {
      ticker: "DE",
      name: "Deere & Co",
      sic: "3523",
      match: "major group",
      market_cap: "120000000000",
      in_set: true,
    },
  ];
}

export function compsRow(overrides: Partial<CompsRowOut> = {}): CompsRowOut {
  return {
    code: "pe",
    label: "P/E",
    category: "Valuation",
    unit: "x",
    target: "34.2",
    peers: ["52.1", "16.3"],
    peer_median: "34.2",
    peer_min: "16.3",
    peer_max: "52.1",
    n: 2,
    target_vs_median: "0.123",
    target_rank: 2,
    caveats: [],
    ...overrides,
  };
}

// AAPL vs {COST, DE}: P/E, EV/EBITDA (a DE caveat) and gross margin.
export function comparison(overrides: Partial<CompsOut> = {}): CompsOut {
  return {
    ticker: "AAPL",
    set_id: 1,
    name: "Hardware & industrials",
    basis: "reported",
    companies: [
      { ticker: "AAPL", name: "Apple Inc.", price_date: "2026-10-07", ttm_period: "TTM Q4 FY2025" },
      { ticker: "COST", name: "Costco", price_date: "2026-10-07", ttm_period: "TTM Q4 FY2025" },
      { ticker: "DE", name: "Deere", price_date: "2026-10-07", ttm_period: "TTM Q3 FY2025" },
    ],
    rows: [
      compsRow(),
      compsRow({
        code: "ev_ebitda",
        label: "EV / EBITDA",
        target: "26.0",
        peers: ["33.0", "-4.0"],
        peer_median: "33.0",
        peer_min: "33.0",
        peer_max: "33.0",
        n: 1,
        target_vs_median: "-0.2121",
        target_rank: 2,
        caveats: [{ ticker: "DE", text: "EBITDA includes financial services interest." }],
      }),
      compsRow({
        code: "gross_margin",
        label: "Gross margin",
        category: "Profitability",
        unit: "pct",
        target: "0.462",
        peers: ["0.126", "0.37"],
        peer_median: "0.248",
        peer_min: "0.126",
        peer_max: "0.37",
        target_vs_median: "0.214",
        target_rank: 1,
      }),
    ],
    ...overrides,
  };
}

// Shapes of GET …/guidance and …/guidance/metrics.

export function guidanceEntry(overrides: Partial<GuidanceEntryOut> = {}): GuidanceEntryOut {
  return {
    id: 1,
    metric: "revenue",
    label: "Revenue",
    unit: "USD",
    fiscal_year: 2024,
    fiscal_period: "FY",
    low: "380000000000",
    high: "390000000000",
    basis: "reported",
    direction: "higher",
    given_on: "2023-11-02",
    source_note: null,
    actual: "391035000000",
    verdict: "beat",
    surprise: "0.015675",
    latest: true,
    created_at: "2026-10-23T10:00:00Z",
    updated_at: "2026-10-23T10:00:00Z",
    ...overrides,
  };
}

export function guidance(overrides: Partial<GuidanceOut> = {}): GuidanceOut {
  return {
    ticker: "AAPL",
    entries: [
      guidanceEntry({ id: 1, latest: false, verdict: "beat", given_on: "2023-11-02" }),
      guidanceEntry({
        id: 3,
        low: "395000000000",
        high: "400000000000",
        given_on: "2024-05-02",
        verdict: "miss",
        surprise: "-0.0123",
      }),
      guidanceEntry({
        id: 4,
        metric: "gross_margin",
        label: "Gross margin",
        unit: "pct",
        fiscal_period: "Q4",
        low: "0.45",
        high: "0.46",
        actual: "0.4622",
        verdict: "beat",
        surprise: "0.015",
      }),
      guidanceEntry({
        id: 5,
        metric: "kpi:stores",
        label: "Stores",
        unit: null,
        fiscal_year: 2025,
        low: "900",
        high: "910",
        actual: null,
        verdict: "pending",
        surprise: null,
      }),
    ],
    summary: { beat: 1, in_range: 0, miss: 1, pending: 1, hit_rate: "0.500000" },
    by_metric: [
      {
        metric: "gross_margin",
        label: "Gross margin",
        beat: 1,
        in_range: 0,
        miss: 0,
        pending: 0,
        hit_rate: "1.000000",
      },
      {
        metric: "revenue",
        label: "Revenue",
        beat: 0,
        in_range: 0,
        miss: 1,
        pending: 0,
        hit_rate: "0.000000",
      },
    ],
    ...overrides,
  };
}

export function guidanceMetrics(): MetricChoiceOut[] {
  return [
    {
      metric: "revenue",
      label: "Revenue",
      group: "line",
      unit: "USD",
      default_direction: "higher",
      quarterly: true,
    },
    {
      metric: "sga",
      label: "SG&A",
      group: "line",
      unit: "USD",
      default_direction: "lower",
      quarterly: true,
    },
    {
      metric: "gross_margin",
      label: "Gross margin",
      group: "ratio",
      unit: "pct",
      default_direction: "higher",
      quarterly: true,
    },
    {
      metric: "roe",
      label: "Return on equity",
      group: "ratio",
      unit: "pct",
      default_direction: "higher",
      quarterly: false,
    },
    {
      metric: "kpi:stores",
      label: "Stores",
      group: "kpi",
      unit: "count",
      default_direction: "higher",
      quarterly: true,
    },
  ];
}
