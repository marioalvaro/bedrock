// The names a QoE formula may use (FR-ANL-10): what the backend's
// `analysis/qoe.py::formula_names()` accepts, i.e. the canonical lines
// (`mapping/canonical_items.yaml`), the metrics and the ratios (`ratios/registry.py`).
// Display only: the API validates every formula, so a name missing here still works and a stale
// one is rejected with its position. Keep it in step when a line or ratio is added.

export interface FormulaGroup {
  title: string;
  names: { code: string; unit?: string }[];
}

const codes = (text: string) => text.split(/\s+/).map((code) => ({ code }));

export const FORMULA_GROUPS: FormulaGroup[] = [
  {
    title: "Income statement lines",
    names: codes(
      "revenue cost_of_revenue gross_profit total_operating_costs rnd sga other_operating_expenses operating_income pretax_income interest_expense other_nonoperating_income net_income income_tax net_income_common net_income_nci eps_basic eps_diluted dividends_per_share shares_basic shares_diluted goodwill_impairment",
    ),
  },
  {
    title: "Balance sheet lines",
    names: codes(
      "total_assets total_current_assets cash short_term_investments receivables inventory other_current_assets total_noncurrent_assets ppe_net operating_lease_rou goodwill intangibles long_term_investments other_noncurrent_assets total_liabilities total_current_liabilities accounts_payable short_term_debt deferred_revenue_current accrued_liabilities other_current_liabilities total_noncurrent_liabilities long_term_debt operating_lease_liabilities_noncurrent other_noncurrent_liabilities temporary_equity total_equity equity_parent common_stock_apic retained_earnings aoci other_equity nci total_liabilities_and_equity total_debt net_debt shares_outstanding",
    ),
  },
  {
    title: "Cash flow lines",
    names: codes(
      "cfo cf_net_income d_and_a sbc deferred_taxes change_receivables change_inventory change_payables other_operating_activities cfi capex acquisitions purchases_of_investments sales_maturities_of_investments other_investing_activities cff debt_issued debt_repaid buybacks dividends_paid other_financing_activities fx_effect net_change_in_cash free_cash_flow",
    ),
  },
  { title: "Metrics", names: codes("ebitda tax_rate nopat invested_capital") },
  {
    title: "Ratios",
    names: [
      ...["gross_margin", "operating_margin", "ebitda_margin", "net_margin", "fcf_margin"],
      ...["roe", "roa", "roic", "dupont_net_margin"],
    ]
      .map((code) => ({ code, unit: "pct" }))
      .concat(
        [
          "dupont_asset_turnover",
          "dupont_equity_multiplier",
          "current_ratio",
          "quick_ratio",
          "debt_to_ebitda",
          "net_debt_to_ebitda",
          "interest_coverage",
          "debt_to_equity",
          "asset_turnover",
        ].map((code) => ({ code, unit: "x" })),
        ["dso", "dio", "dpo", "ccc"].map((code) => ({ code, unit: "days" })),
        ["eps_diluted", "fcf_per_share", "bvps", "dps"].map((code) => ({
          code,
          unit: "USD/shares",
        })),
      ),
  },
];
