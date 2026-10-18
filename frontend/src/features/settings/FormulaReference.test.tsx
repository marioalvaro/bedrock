import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { FormulaReference } from "./FormulaReference";
import { FORMULA_GROUPS } from "./formulaNames";

describe("FormulaReference", () => {
  it("is collapsed until its summary is clicked", async () => {
    render(<FormulaReference />);
    const details = screen.getByText("Formula reference").closest("details");
    expect(details).not.toHaveAttribute("open");
    await userEvent.click(screen.getByText("Formula reference"));
    expect(details).toHaveAttribute("open");
  });

  it("lists the functions and the operators", () => {
    render(<FormulaReference />);
    for (const fn of ["avg(x)", "yoy(x)", "prev(x)"]) {
      expect(screen.getByText(fn)).toBeInTheDocument();
    }
    expect(screen.getByText("+ − × ÷ ( )")).toBeInTheDocument();
  });

  it("shows every group with its names", () => {
    render(<FormulaReference />);
    for (const group of FORMULA_GROUPS) {
      const section = screen.getByRole("region", { name: group.title });
      for (const name of group.names) {
        const text = name.unit ? `${name.code} (${name.unit})` : name.code;
        expect(within(section).getByText(text)).toBeInTheDocument();
      }
    }
  });

  it("covers a line of each statement, a metric and a ratio with its unit", () => {
    render(<FormulaReference />);
    const codes = (title: string) =>
      within(screen.getByRole("region", { name: title }))
        .getAllByRole("listitem")
        .map((li) => li.textContent);
    expect(codes("Income statement lines")).toContain("revenue");
    expect(codes("Balance sheet lines")).toContain("total_assets");
    expect(codes("Cash flow lines")).toContain("cfo");
    expect(codes("Metrics")).toContain("ebitda");
    expect(codes("Metrics")).toContain("enterprise_value");
    expect(codes("Ratios")).toContain("pe (x)");
    expect(codes("Ratios")).toContain("dividend_yield (pct)");
    expect(codes("Ratios")).toContain("roe (pct)");
    expect(codes("Ratios")).toContain("dso (days)");
  });

  it("has no duplicate code inside a group", () => {
    for (const group of FORMULA_GROUPS) {
      const codes = group.names.map((n) => n.code);
      expect(new Set(codes).size).toBe(codes.length);
    }
  });

  it("states the unit and naming notes", () => {
    render(<FormulaReference />);
    expect(screen.getByText(/numbers inside a formula are fractions/i)).toBeInTheDocument();
    expect(screen.getByText(/rule codes .* are not names/i)).toBeInTheDocument();
  });
});
