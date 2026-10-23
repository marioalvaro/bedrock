/// <reference types="node" />
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Vitest turns a `?raw` import of a .css file into an empty string, so read the files.
const read = (file: string) => readFileSync(path.resolve(import.meta.dirname, file), "utf8");
const css = read("index.css");

// jsdom computes no stylesheets, so the motion rules are checked as text: one token drives
// every expander, and the OS "reduce motion" setting zeroes it.

const reducedBlock = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/)?.[1];

describe("motion tokens", () => {
  it("defines --motion-fast between 120 and 150 ms", () => {
    const ms = Number(css.match(/--motion-fast:\s*(\d+)ms/)?.[1]);

    expect(ms).toBeGreaterThanOrEqual(120);
    expect(ms).toBeLessThanOrEqual(150);
  });

  it("zeroes --motion-fast when the OS asks to reduce motion", () => {
    expect(reducedBlock).toMatch(/--motion-fast:\s*0ms/);
  });

  it("shortens AG Grid's 400 ms row slide to the token", () => {
    expect(css).toMatch(
      /\.ag-row-animation\s+\.ag-row\s*\{[^}]*transition-duration:\s*var\(--motion-fast\)/,
    );
  });

  it("fades the body of an opened <details> with the token", () => {
    expect(css).toMatch(/details\[open\][^{]*\{[^}]*animation:[^;}]*var\(--motion-fast\)/);
  });

  it("sets tabular digits on every grid cell, not only the .num ones", () => {
    expect(css).toMatch(/\.ag-cell\s*\{[^}]*font-variant-numeric:\s*tabular-nums/);
  });

  it.each(["sheet.tsx", "alert-dialog.tsx"])("%s takes its duration from the token", (file) => {
    const source = read(`components/ui/${file}`);

    expect(source).toContain("duration-(--motion-fast)");
    expect(source).not.toMatch(/\bduration-\d+/);
  });
});
