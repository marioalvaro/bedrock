/// <reference types="node" />
import { readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Gotcha G46: on macOS's case-insensitive disk `./GuidanceChart` resolves to `guidanceChart.ts`
// (`.ts` is tried before `.tsx`), so a component and a helper whose names differ only by case
// import the wrong module and render `undefined`.
const stem = (name: string) => name.replace(/(\.test)?\.tsx?$/, "").toLowerCase();

function clashes(dir: string): string[] {
  const entries = readdirSync(dir, { withFileTypes: true });
  const byStem = new Map<string, Set<string>>();
  for (const entry of entries.filter((e) => e.isFile() && /\.tsx?$/.test(e.name))) {
    const base = entry.name.replace(/(\.test)?\.tsx?$/, "");
    byStem.set(stem(entry.name), (byStem.get(stem(entry.name)) ?? new Set()).add(base));
  }
  const here = [...byStem.values()]
    .filter((bases) => bases.size > 1)
    .map((bases) => path.join(path.relative(import.meta.dirname, dir), [...bases].join(" / ")));
  return [
    ...here,
    ...entries.filter((e) => e.isDirectory()).flatMap((e) => clashes(path.join(dir, e.name))),
  ];
}

describe("source file names", () => {
  it("never differ only by case within one folder", () => {
    expect(clashes(import.meta.dirname)).toEqual([]);
  });
});
