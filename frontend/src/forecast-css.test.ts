/// <reference types="node" />
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// jsdom computes no stylesheets, so the M4 tokens are checked as text in both themes.
const css = readFileSync(path.resolve(import.meta.dirname, "index.css"), "utf8");
const block = (selector: string) =>
  css.match(new RegExp(`\\n${selector} \\{([\\s\\S]*?)\\n\\}`))?.[1] ?? "";
const themes = { light: block(":root"), dark: block("\\.dark") };

const token = (body: string, name: string) =>
  body.match(new RegExp(`${name}:\\s*([^;]+);`))?.[1]?.trim();

describe.each(Object.entries(themes))("%s theme", (_, body) => {
  it("defines the forecast column tint", () => {
    expect(token(body, "--forecast-tint")).toBeTruthy();
  });

  it("gives the five chart series distinct, coloured tokens", () => {
    const colors = [1, 2, 3, 4, 5].map((n) => token(body, `--chart-${n}`));
    expect(new Set(colors).size).toBe(5);
    for (const color of colors) {
      const chroma = Number(color?.match(/oklch\(\s*[\d.]+\s+([\d.]+)/)?.[1]);
      expect(chroma, color).toBeGreaterThan(0.05);
    }
  });
});

it("tints forecast cells with the token", () => {
  expect(css).toMatch(/\.cell-forecast\s*\{[^}]*background-color:\s*var\(--forecast-tint\)/);
});

it("styles forecast values as plain text, not as derived italics", () => {
  const rule = css.match(/\n\.prov-forecast\s*\{([^}]*)\}/)?.[1];
  expect(rule).toBeDefined();
  expect(rule).toMatch(/font-style:\s*normal/);
});

describe("cross-check mark (M6)", () => {
  it("defines --caution in each theme with the ERD's values", () => {
    expect(token(themes.light, "--caution")).toBe("oklch(0.68 0.16 70)");
    expect(token(themes.dark, "--caution")).toBe("oklch(0.78 0.15 75)");
  });

  it("underlines a value outside the engine's range, dotted, in the token", () => {
    const rule = css.match(/\n\.cell-check-outside\s*\{([^}]*)\}/)?.[1];
    expect(rule).toBeDefined();
    expect(rule).toMatch(/text-decoration-line:\s*underline/);
    expect(rule).toMatch(/text-decoration-style:\s*dotted/);
    expect(rule).toMatch(/text-decoration-color:\s*var\(--caution\)/);
    expect(rule).toMatch(/text-underline-offset:\s*3px/);
  });
});
