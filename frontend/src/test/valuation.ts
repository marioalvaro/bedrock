import type {
  DcfOut,
  GridAxisOut,
  SensitivityGridOut,
  TornadoBarOut,
  TornadoOut,
  ValuationInputRowOut,
  ValuationInputsOut,
  ValuationOut,
  ValuationResultOut,
  ValuationSummaryOut,
} from "@/api/generated/types.gen";

// Shapes of the M5 valuation routes for AAPL's Main scenario, taken from the recorded fixtures
// (a stub first year, WACC, Gordon growth, a manual P/E and an own-history EV/EBITDA error).

export function inputRow(overrides: Partial<ValuationInputRowOut> = {}): ValuationInputRowOut {
  return {
    code: "beta",
    label: "Beta",
    group: "Discount rate",
    unit: "x",
    kind: "number",
    choices: null,
    value: "1",
    source: "default",
    own: null,
    note: null,
    ...overrides,
  };
}

const SOURCES = ["off", "manual", "own_history", "peer_median"];

function targetRows(code: string, label: string, source: string): ValuationInputRowOut[] {
  return [
    inputRow({
      code: `${code}_source`,
      label: `${label} source`,
      group: "Multiples",
      unit: null,
      kind: "choice",
      choices: SOURCES,
      value: source,
    }),
    inputRow({
      code: `${code}_multiple`,
      label: `${label} multiple`,
      group: "Multiples",
      value: null,
    }),
    inputRow({
      code: `${code}_percentile`,
      label: `${label} percentile`,
      group: "Multiples",
      unit: "pct",
      value: "0.5",
    }),
    inputRow({
      code: `${code}_year`,
      label: `${label} year`,
      group: "Multiples",
      unit: "year",
      kind: "integer",
      value: "1",
    }),
  ];
}

/** GET …/valuation-inputs of Base at the defaults (the catalog in its order). */
export function valuationInputs(overrides: Partial<ValuationInputsOut> = {}): ValuationInputsOut {
  const pct = (code: string, label: string, value: string | null, group = "Discount rate") =>
    inputRow({ code, label, group, unit: "pct", value });
  return {
    scenario_id: 1,
    case: "base",
    forecast_years: [2026, 2027, 2028, 2029, 2030].map((year, i) => ({
      index: i + 1,
      fiscal_year: year,
      label: `FY${String(year).slice(2)}E`,
    })),
    rows: [
      inputRow({
        code: "discount_method",
        label: "Discount method",
        unit: null,
        kind: "choice",
        choices: ["wacc", "direct"],
        value: "wacc",
      }),
      pct("discount_rate", "Discount rate", "0.09"),
      pct("risk_free_rate", "Risk-free rate", "0.04"),
      pct("equity_risk_premium", "Equity risk premium", "0.05"),
      inputRow(),
      {
        ...pct("cost_of_debt", "Cost of debt", "0.03374198917305102049570611096"),
        source: "derived",
        note: "From the forecast's FY2026 interest rate",
      },
      {
        ...pct("tax_rate", "Tax rate", "0.1814012057593762787192619025"),
        source: "derived",
        note: "From the forecast's FY2026 tax rate",
      },
      {
        ...pct("debt_weight", "Debt weight", "0.01685954891865082102761682516"),
        source: "derived",
        note: "Market weights at the close of 2026-10-07",
      },
      inputRow({
        code: "terminal_method",
        label: "Terminal method",
        group: "Terminal value",
        unit: null,
        kind: "choice",
        choices: ["gordon", "exit_multiple"],
        value: "gordon",
      }),
      pct("terminal_growth", "Terminal growth", "0.025", "Terminal value"),
      inputRow({
        code: "exit_multiple",
        label: "Exit multiple (EV/EBITDA)",
        group: "Terminal value",
        value: "12",
      }),
      inputRow({
        code: "mid_year",
        label: "Mid-year discounting",
        group: "Terminal value",
        unit: null,
        kind: "bool",
        value: "true",
      }),
      ...targetRows("pe", "P/E", "own_history"),
      ...targetRows("ev_ebitda", "EV/EBITDA", "own_history"),
      ...targetRows("p_fcf", "P/FCF", "off"),
      ...targetRows("ev_sales", "EV/Sales", "off"),
      inputRow({
        code: "comps_set_id",
        label: "Comps set",
        group: "Multiples",
        unit: null,
        kind: "comps_set",
        value: null,
      }),
    ],
    warnings: [],
    ...overrides,
  };
}

/** `inputs` with the rows of `codes` replaced by `rows`' fields. */
export function withInputs(
  inputs: ValuationInputsOut,
  changes: Record<string, Partial<ValuationInputRowOut>>,
): ValuationInputsOut {
  return {
    ...inputs,
    rows: inputs.rows.map((row) => (changes[row.code] ? { ...row, ...changes[row.code] } : row)),
  };
}

export function dcf(overrides: Partial<DcfOut> = {}): DcfOut {
  return {
    valuation_date: "2026-10-07",
    discount: {
      method: "wacc",
      rate: "0.08894832075479352100520525373",
      cost_of_equity: "0.09",
      after_tax_cost_of_debt: "0.02762115165233974567648821593",
      risk_free_rate: "0.04",
      equity_risk_premium: "0.05",
      beta: "1",
      cost_of_debt: "0.03374198917305102049570611096",
      tax_rate: "0.1814012057593762787192619025",
      debt_weight: "0.01685954891865082102761682516",
      equity_weight: "0.9831404510813491789723831748",
    },
    mid_year: true,
    periods: [
      {
        period_key: "FY2026",
        label: "FY26E",
        start: "2026-06-28",
        end: "2026-09-27",
        stub: true,
        nopat: "26577954491.71100933986284523",
        d_and_a: "3042451439.609224008235451160",
        change_working_capital: "5830709865.469436507943679916",
        capex: "-2898845821.070789382691801379",
        fcff: "32552269975.71888047335017493",
        years: "0",
        discount_factor: "1",
        present_value: "32552269975.71888047335017493",
      },
      {
        period_key: "FY2027",
        label: "FY27E",
        start: "2026-09-28",
        end: "2027-09-27",
        stub: false,
        nopat: "121586312878.2239065218146602",
        d_and_a: "13918319138.08486181207554382",
        change_working_capital: "524529755.878947831207533949",
        capex: "-13261365734.38592537542596062",
        fcff: "122767796037.8017907896717773",
        years: "0.4859685147159479808350444901",
        discount_factor: "0.9594351652470847326411392113",
        present_value: "117787740678.5487554445263872",
      },
    ],
    terminal: {
      method: "gordon",
      growth: "0.025",
      exit_multiple: null,
      base_fcff: "129904962220.9454094301321009",
      base_ebitda: "171795396133.9165616755056659",
      value: "2082190504845.868384183767666",
      years: "3.972621492128678986995208761",
      discount_factor: "0.7128269744975370181786320946",
      present_value: "1484241557896.779551760858522",
      implied_exit_multiple: "12.12017639414956169476526611",
      implied_growth: "0.02500000000000000000000000001",
    },
    sum_present_value: "463651693660.3790743897270480",
    terminal_share: "0.7619727398871920352688326622",
    ...overrides,
  };
}

export function result(overrides: Partial<ValuationResultOut> = {}): ValuationResultOut {
  return {
    key: "dcf_fcff",
    method: "dcf_fcff",
    label: "DCF (FCFF)",
    enterprise_value: "1947893251557.158626150585570",
    equity_value: "1925948251557.158626150585570",
    value_per_share: "131.8333307817371175593083212",
    upside: "-0.6084197261955709817943139537",
    caveat: null,
    error: null,
    dcf: dcf(),
    multiple: null,
    ...overrides,
  };
}

export const peResult = (overrides: Partial<ValuationResultOut> = {}) =>
  result({
    key: "multiple:pe",
    method: "multiple_target",
    label: "P/E",
    enterprise_value: "3214512050263.220645713498925",
    equity_value: "3192567050263.220645713498925",
    value_per_share: "218.5348166234126710919521752",
    upside: "-0.3508931100976841682004569008",
    dcf: null,
    multiple: {
      ratio_code: "pe",
      metric_label: "net income to common",
      fiscal_year: 2026,
      period_label: "FY26E",
      metric_value: "127702682010.5288258285399570",
      multiple: "25",
      source: "manual",
      percentile: null,
      n: null,
      comps_set: null,
    },
    ...overrides,
  });

export const evEbitdaError = () =>
  result({
    key: "multiple:ev_ebitda",
    method: "multiple_target",
    label: "EV/EBITDA",
    enterprise_value: null,
    equity_value: null,
    value_per_share: null,
    upside: null,
    error: "EV/EBITDA: fewer than 3 years of history",
    dcf: null,
  });

/** GET …/cases/base/valuation: DCF, a manual P/E and an EV/EBITDA error. */
export function valuation(overrides: Partial<ValuationOut> = {}): ValuationOut {
  return {
    scenario_id: 1,
    case: "base",
    price: "336.67",
    price_date: "2026-10-07",
    valuation_date: "2026-10-07",
    shares: "14608963000",
    bridge: {
      total_debt: "84344000000",
      cash: "39544000000",
      short_term_investments: "22855000000",
      minority_interest: "0",
      temporary_equity: "0",
      net_claims: "21945000000",
    },
    results: [result(), peResult(), evEbitdaError()],
    warnings: [],
    ...overrides,
  };
}

/** GET …/scenarios/1/valuation: the three cases, base first as the API orders them. */
export function valuationSummary(
  overrides: Partial<ValuationSummaryOut> = {},
): ValuationSummaryOut {
  const error = { "multiple:ev_ebitda": "EV/EBITDA: fewer than 3 years of history" };
  const kase = (
    name: "base" | "bull" | "bear",
    label: string,
    dcfValue: string,
    dcfUpside: string,
  ) => ({
    case: name,
    label,
    value_per_share: { dcf_fcff: dcfValue, "multiple:pe": "218.53", "multiple:ev_ebitda": null },
    upside: { dcf_fcff: dcfUpside, "multiple:pe": "-0.3509", "multiple:ev_ebitda": null },
    errors: error,
    error: null,
  });
  return {
    scenario_id: 1,
    price: "336.67",
    price_date: "2026-10-07",
    methods: [
      { key: "dcf_fcff", label: "DCF (FCFF)" },
      { key: "multiple:pe", label: "P/E" },
      { key: "multiple:ev_ebitda", label: "EV/EBITDA" },
    ],
    cases: [
      kase("base", "Base", "131.83", "-0.6084"),
      kase("bull", "Bull", "353.15", "0.0490"),
      kase("bear", "Bear", "112.91", "-0.6646"),
    ],
    ...overrides,
  };
}

// ---- Sensitivity (AAPL Main Base, base value 132.47 against a 336.67 close) -----------------

export function tornadoBar(overrides: Partial<TornadoBarOut> = {}): TornadoBarOut {
  return {
    code: "revenue_growth",
    label: "Revenue growth",
    kind: "driver",
    unit: "pct",
    step: "0.01",
    mode: "add",
    low_value: "125.10",
    high_value: "140.20",
    low_change: "-7.37",
    high_change: "7.73",
    range: "15.10",
    error: null,
    ...overrides,
  };
}

/** GET …/cases/base/sensitivity/tornado: bars by range, an error bar last. */
export function tornado(overrides: Partial<TornadoOut> = {}): TornadoOut {
  return {
    scenario_id: 1,
    case: "base",
    base_value: "132.47",
    price: "336.67",
    bars: [
      tornadoBar({
        code: "discount_rate",
        label: "Discount rate",
        kind: "valuation",
        step: "0.005",
        low_value: "143.47",
        high_value: "123.17",
        low_change: "11.00",
        high_change: "-9.30",
        range: "20.30",
      }),
      tornadoBar(),
      tornadoBar({
        code: "terminal_growth",
        label: "Terminal growth",
        kind: "valuation",
        step: "0.005",
        low_value: "126.47",
        high_value: "139.67",
        low_change: "-6.00",
        high_change: "7.20",
        range: "13.20",
      }),
      tornadoBar({
        code: "receivable_days",
        label: "Receivable days",
        unit: "days",
        step: "5",
        low_value: "133.00",
        high_value: "131.94",
        low_change: "0.53",
        high_change: "-0.53",
        range: "1.06",
      }),
      tornadoBar({
        code: "buybacks",
        label: "Buybacks",
        unit: "USD",
        step: "0.1",
        mode: "scale",
        low_value: null,
        high_value: null,
        low_change: null,
        high_change: null,
        range: null,
        error: "r must exceed g",
      }),
    ],
    ...overrides,
  };
}

const FIVE = [0, 1, 2, 3, 4];

export function gridAxis(overrides: Partial<GridAxisOut> = {}): GridAxisOut {
  return {
    code: "discount_rate",
    label: "Discount rate",
    unit: "pct",
    step: "0.005",
    mode: "add",
    shifts: ["-0.01", "-0.005", "0", "0.005", "0.01"],
    points: ["0.0785", "0.0835", "0.0885", "0.0935", "0.0985"],
    ...overrides,
  };
}

/** GET …/sensitivity/grid?x=discount_rate&y=terminal_growth: rows are y, the center the base. */
export function sensitivityGrid(overrides: Partial<SensitivityGridOut> = {}): SensitivityGridOut {
  // The corner point (highest growth, highest rate) fails, as a point can.
  const failed = (i: number, j: number) => i === 4 && j === 4;
  const values = FIVE.map((i) =>
    FIVE.map((j) => (failed(i, j) ? null : (132.47 + (i - 2) * 6 - (j - 2) * 10).toFixed(2))),
  );
  return {
    scenario_id: 1,
    case: "base",
    base_value: "132.47",
    price: "140.00",
    x: gridAxis(),
    y: gridAxis({
      code: "terminal_growth",
      label: "Terminal growth",
      points: ["0.015", "0.02", "0.025", "0.03", "0.035"],
    }),
    values,
    upside: values.map((cells) =>
      cells.map((value) => (value === null ? null : (Number(value) / 140 - 1).toFixed(4))),
    ),
    errors: FIVE.map((i) =>
      FIVE.map((j) => (failed(i, j) ? "Discount rate must exceed growth" : null)),
    ),
    ...overrides,
  };
}
