import { describe, expect, it } from "vitest";

import business from "../../../../backend/tests/fixtures/segments/template_business.csv?raw";
import geo from "../../../../backend/tests/fixtures/segments/template_geo.csv?raw";
import kpi from "../../../../backend/tests/fixtures/segments/template_kpi.csv?raw";
import { FORMAT_RULES, templateCsv, templateFileName, templateRows } from "./importFormat";

// The backend test_segments_engine.py proves `parse_import` accepts these exact files, so a
// download equal to its fixture is a download the import accepts.
describe("the import template", () => {
  it.each([
    ["business", business],
    ["geo", geo],
    ["kpi", kpi],
  ] as const)("the %s download equals the backend fixture", (dimension, fixture) => {
    expect(templateCsv(dimension)).toBe(fixture);
  });

  it("quotes a cell holding a comma or a quote and leaves the rest bare", () => {
    expect(templateCsv("geo")).toContain('Americas,revenue,USD,"162,560","167,045"');
    expect(templateCsv("kpi")).toContain("Same-store sales (U.S.),same_store_sales_us,pct,4.1%");
  });

  it("the example rows start with the header name,metric,unit and then periods", () => {
    for (const dimension of ["business", "geo", "kpi"] as const) {
      const [header] = templateRows(dimension);
      expect(header!.slice(0, 3)).toEqual(["name", "metric", "unit"]);
      expect(header!.slice(3).every((cell) => /^(Q[1-4] )?FY\d{4}$/.test(cell))).toBe(true);
    }
  });

  it("names the file after the dimension", () => {
    expect(templateFileName("geo")).toBe("segments_template_geo.csv");
    expect(templateFileName("kpi")).toBe("segments_template_kpi.csv");
  });

  it("states every rule the parser enforces", () => {
    const text = FORMAT_RULES.join("\n");
    for (const word of [
      "FY2024",
      "Q1 FY2024",
      "FY24",
      "USD",
      "scale",
      "5.2%",
      "blank",
      "parentheses",
      "tab",
      "all or nothing",
    ]) {
      expect(text.toLowerCase()).toContain(word.toLowerCase());
    }
  });
});
