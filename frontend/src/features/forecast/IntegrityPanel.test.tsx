import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { IntegrityOut, PeriodOut } from "@/api/generated/types.gen";

import { IntegrityPanel } from "./IntegrityPanel";

function period(key: string, label: string): PeriodOut {
  return {
    key,
    label,
    fiscal_year: 2026,
    fiscal_period: "FY",
    period_start: "2025-09-28",
    period_end: "2026-09-26",
    is_forecast: true,
  };
}

const PERIODS = [period("FY2025", "FY2025"), period("FY2026", "FY26E"), period("FY2027", "FY27E")];

function check(overrides: Partial<IntegrityOut> = {}): IntegrityOut {
  return {
    period_key: "FY2026",
    balance_diff: "0",
    cash_diff: "0",
    re_diff: "0",
    quarters_diff: null,
    ok: true,
    ...overrides,
  };
}

const row = (label: string) => screen.getByRole("row", { name: new RegExp(`^${label}\\b`) });
const cells = (label: string) =>
  within(row(label))
    .getAllByRole("cell")
    .map((cell) => cell.textContent);

describe("IntegrityPanel", () => {
  it("says every check passes and marks each check of each forecast period", () => {
    render(
      <IntegrityPanel
        integrity={[check(), check({ period_key: "FY2027" })]}
        periods={PERIODS}
        warnings={[]}
        scale="M"
      />,
    );

    expect(screen.getByText("All checks pass")).toBeInTheDocument();
    expect(cells("FY26E")).toEqual(["✓", "✓", "✓"]);
    expect(cells("FY27E")).toEqual(["✓", "✓", "✓"]);
    expect(screen.queryByRole("row", { name: /^FY2025\b/ })).toBeNull();
  });

  it("names each check in its column header", () => {
    render(<IntegrityPanel integrity={[check()]} periods={PERIODS} warnings={[]} scale="M" />);

    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Period",
      "Balance sheet",
      "Cash roll-forward",
      "Retained earnings roll-forward",
    ]);
  });

  it("shows a failing check's difference in the page scale, in red", () => {
    const failing = check({ ok: false, balance_diff: "-2500000000", re_diff: "0" });

    const { rerender } = render(
      <IntegrityPanel integrity={[failing]} periods={PERIODS} warnings={[]} scale="M" />,
    );

    expect(screen.getByText("1 check fails")).toBeInTheDocument();
    expect(cells("FY26E")).toEqual(["(2,500)", "✓", "✓"]);
    expect(within(row("FY26E")).getByText("(2,500)")).toHaveClass("text-negative");

    rerender(<IntegrityPanel integrity={[failing]} periods={PERIODS} warnings={[]} scale="B" />);
    expect(cells("FY26E")).toEqual(["(2.5)", "✓", "✓"]);
  });

  it("counts every failing check across periods", () => {
    render(
      <IntegrityPanel
        integrity={[
          check({ ok: false, balance_diff: "5000000", cash_diff: "5000000" }),
          check({ period_key: "FY2027", ok: false, re_diff: "1000000" }),
        ]}
        periods={PERIODS}
        warnings={[]}
        scale="M"
      />,
    );

    expect(screen.getByText("3 checks fail")).toBeInTheDocument();
  });

  it("adds Quarters = FY only for the years built from their quarters", () => {
    render(
      <IntegrityPanel
        integrity={[check({ quarters_diff: "0" }), check({ period_key: "FY2027" })]}
        periods={PERIODS}
        warnings={[]}
        scale="M"
      />,
    );

    expect(screen.getByRole("columnheader", { name: "Quarters = FY" })).toBeInTheDocument();
    expect(cells("FY26E")).toEqual(["✓", "✓", "✓", "✓"]);
    expect(cells("FY27E")).toEqual(["✓", "✓", "✓", ""]);
  });

  it("lists the engine's warnings under the checks", () => {
    render(
      <IntegrityPanel
        integrity={[check()]}
        periods={PERIODS}
        warnings={["Debt repaid capped at the opening balance in FY2027"]}
        scale="M"
      />,
    );

    expect(
      screen.getByText("Debt repaid capped at the opening balance in FY2027"),
    ).toBeInTheDocument();
  });

  it("says so when there is no forecast period to check", () => {
    render(<IntegrityPanel integrity={[]} periods={PERIODS} warnings={[]} scale="M" />);

    expect(screen.getByText("No forecast periods to check.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
