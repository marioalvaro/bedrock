/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Gotcha G39: the production build turns a default import of the CommonJS
// `echarts-for-react/lib/core` into the module object, and React throws #130 (the tab goes
// blank). Vitest resolves it fine and the view tests mock it, so only the source can be checked.
const src = import.meta.dirname;
const files = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? files(path.join(dir, entry.name))
      : /\.tsx?$/.test(entry.name) && entry.name !== "echarts-import.test.ts"
        ? [path.join(dir, entry.name)]
        : [],
  );

describe("echarts-for-react imports", () => {
  it("use the ES module build, never the CommonJS lib/", () => {
    const offenders = files(src).filter((file) =>
      /["']echarts-for-react(?:\/lib\/[^"']*)?["']/.test(readFileSync(file, "utf8")),
    );
    expect(offenders.map((file) => path.relative(src, file))).toEqual([]);
  });
});
