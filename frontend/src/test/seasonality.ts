import type { SeasonalityOut } from "@/api/generated/types.gen";

// The shape of GET /companies/{ticker}/seasonality, cut from a recorded COST revenue payload
// (S4, 2026-11-07): the last 12 quarters of its run (the full run is Q1 FY09–Q4 FY26), rounded
// to thousands of USD; factors and strength as recorded.

const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;

const periods = [2024, 2025, 2026].flatMap((year) =>
  QUARTERS.map((quarter) => ({
    fiscal_year: year,
    fiscal_period: quarter,
    label: `${quarter} FY${String(year % 100).padStart(2, "0")}`,
  })),
);

export function seasonality(overrides: Partial<SeasonalityOut> = {}): SeasonalityOut {
  return {
    code: "revenue",
    label: "Revenue",
    unit: "USD",
    lines: [
      { code: "revenue", label: "Revenue" },
      { code: "net_income", label: "Net income" },
      { code: "eps_diluted", label: "EPS (diluted)" },
      { code: "cfo", label: "Cash from operations" },
    ],
    periods,
    observed: [
      57799000000, 58442000000, 58515000000, 79697000000, 62151000000, 63723000000, 63205000000,
      86156000000, 67307000000, 69597000000, 70527000000, 95723000000,
    ],
    trend: [
      61928550000, 62946740000, 64233665000, 65577330000, 67003554000, 68494211000, 70019371000,
      71583359000, 73195871000, 74809648000, 76439517000, 78085065000,
    ],
    seasonal: [
      -4222578000, -4229733000, -5494616000, 14891521000, -4937989000, -4754920000, -5753105000,
      16228830000, -5607965000, -5229810000, -5954268000, 17600543000,
    ],
    residual: [
      93028000, -275007000, -224048000, -771851000, 85436000, -16292000, -1061266000, -1656189000,
      -280905000, 17162000, 41751000, 37392000,
    ],
    factors: [
      { fiscal_period: "Q1", value: -5134170000, pct: -0.0738 },
      { fiscal_period: "Q2", value: -4949480000, pct: -0.0712 },
      { fiscal_period: "Q3", value: -5945322000, pct: -0.0855 },
      { fiscal_period: "Q4", value: 16028972000, pct: 0.2305 },
    ],
    strength: 0.9769,
    ...overrides,
  };
}
