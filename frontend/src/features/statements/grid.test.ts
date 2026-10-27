import { describe, expect, it } from "vitest";

import type { PeriodOut, StatementOut } from "@/api/generated/types.gen";
import { noteLink, noteLinks } from "@/test/context";
import { balanceStatement, customIncomeStatement, incomeStatement } from "@/test/statements";

import {
  canExplain,
  cellNoteCount,
  csvLabel,
  expandableCodes,
  lineNoteCount,
  noteIndex,
  provenanceClasses,
  provenanceMark,
  rowUnitHint,
  toGridRows,
} from "./grid";

const NONE: ReadonlySet<string> = new Set();
const OFF = { yoy: false, commonSize: false, expanded: NONE };
// Everything open: the detail rows are the subject of most tests.
const all = (payload: StatementOut) => new Set(expandableCodes(payload));
const OPEN = { ...OFF, expanded: all(incomeStatement()) };

describe("toGridRows", () => {
  it("makes one row per line item, keyed by period", () => {
    const rows = toGridRows(incomeStatement(), OPEN);

    expect(rows.map((row) => row.id)).toEqual([
      "revenue",
      "gross_profit",
      "cost_of_revenue",
      "eps_diluted",
    ]);
    expect(rows[0]).toMatchObject({
      code: "revenue",
      label: "Revenue",
      unit: "USD",
      depth: 0,
      kind: "line",
      values: { FY2023: "383285000000", FY2024: "391035000000" },
    });
  });

  it("carries provenance per period", () => {
    const [revenue] = toGridRows(incomeStatement(), OFF);

    expect(revenue?.provenance).toEqual({ FY2023: "reported", FY2024: "derived" });
  });

  it("drops line items with no value in any period", () => {
    const rows = toGridRows(incomeStatement(), OPEN);

    expect(rows.find((row) => row.code === "rnd")).toBeUndefined();
  });

  it("inserts a YoY sub-row under each line when toggled", () => {
    const rows = toGridRows(incomeStatement(), { ...OPEN, yoy: true });

    expect(rows.map((row) => row.id)).toEqual([
      "revenue",
      "revenue:yoy",
      "gross_profit",
      "gross_profit:yoy",
      "cost_of_revenue",
      "cost_of_revenue:yoy",
      "eps_diluted",
      "eps_diluted:yoy",
    ]);
    const yoy = rows[1];
    expect(yoy).toMatchObject({
      kind: "yoy",
      label: "YoY",
      unit: "%",
      depth: 1,
      values: { FY2023: null, FY2024: "0.020219" },
    });
  });

  it("inserts a common-size sub-row only for lines that have one", () => {
    const rows = toGridRows(incomeStatement(), { ...OPEN, commonSize: true });

    expect(rows.map((row) => row.id)).toEqual([
      "revenue",
      "revenue:common_size",
      "gross_profit",
      "gross_profit:common_size",
      "cost_of_revenue",
      "cost_of_revenue:common_size",
      "eps_diluted",
    ]);
    expect(rows[5]?.values).toEqual({ FY2023: "0.558700", FY2024: "0.537900" });
  });

  it("puts YoY before common-size when both are on", () => {
    const rows = toGridRows(incomeStatement(), { ...OPEN, yoy: true, commonSize: true });

    expect(rows.slice(0, 3).map((row) => row.id)).toEqual([
      "revenue",
      "revenue:yoy",
      "revenue:common_size",
    ]);
  });

  it("indents a sub-row one level below its line", () => {
    const rows = toGridRows(incomeStatement(), { ...OPEN, yoy: true });

    expect(rows.find((row) => row.id === "cost_of_revenue:yoy")?.depth).toBe(2);
  });

  it("labels a common-size sub-row with the row it divides by", () => {
    const rows = toGridRows(incomeStatement(), { ...OPEN, commonSize: true });

    expect(rows[1]).toMatchObject({ kind: "common_size", label: "% of Revenue" });
  });

  it("appends the balance check row for a balance sheet", () => {
    const rows = toGridRows(balanceStatement(), OFF);

    const check = rows.at(-1);
    expect(check).toMatchObject({
      id: "balance_check",
      kind: "balance_check",
      label: "Balance check",
      depth: 0,
      values: { FY2023: "0", FY2024: "-2000000" },
      ok: { FY2023: true, FY2024: false },
    });
  });

  it("has no balance check row for other statements", () => {
    expect(toGridRows(incomeStatement(), OFF).some((row) => row.kind === "balance_check")).toBe(
      false,
    );
  });
});

describe("toGridRows stability", () => {
  // AG Grid diffs rows by id: a toggle must add or remove rows, never rename the others.
  const ids = (rows: { id: string }[]) => rows.map((row) => row.id);

  it("keeps every line's id when YoY and common size are switched on", () => {
    const off = ids(toGridRows(incomeStatement(), OPEN));
    const on = ids(toGridRows(incomeStatement(), { ...OPEN, yoy: true, commonSize: true }));

    expect(on.filter((id) => !id.includes(":"))).toEqual(off);
    expect(on.filter((id) => id.includes(":")).every((id) => /:(yoy|common_size)$/.test(id))).toBe(
      true,
    );
  });

  it("keeps the other rows' ids when a breakdown opens", () => {
    const closed = ids(toGridRows(incomeStatement(), OFF));
    const open = ids(
      toGridRows(incomeStatement(), { ...OFF, expanded: new Set(["gross_profit"]) }),
    );

    expect(open.filter((id) => closed.includes(id))).toEqual(closed);
    expect(open).toEqual(["revenue", "gross_profit", "cost_of_revenue", "eps_diluted"]);
  });
});

describe("toGridRows hierarchy", () => {
  const ids = (rows: { id: string }[]) => rows.map((row) => row.id);

  it("shows only the top-level rows while everything is collapsed", () => {
    const rows = toGridRows(incomeStatement(), OFF);

    expect(ids(rows)).toEqual(["revenue", "gross_profit", "eps_diluted"]);
  });

  it("marks the rows that have a breakdown and whether it is open", () => {
    const closed = toGridRows(incomeStatement(), OFF);
    const open = toGridRows(incomeStatement(), { ...OFF, expanded: new Set(["gross_profit"]) });

    expect(closed.map((row) => [row.id, row.hasChildren, row.expanded])).toEqual([
      ["revenue", false, false],
      ["gross_profit", true, false],
      ["eps_diluted", false, false],
    ]);
    expect(open.find((row) => row.id === "gross_profit")).toMatchObject({
      hasChildren: true,
      expanded: true,
    });
    expect(ids(open)).toContain("cost_of_revenue");
  });

  it("opens a nested breakdown one level at a time", () => {
    const bs = balanceStatement();

    expect(ids(toGridRows(bs, OFF)).slice(0, 1)).toEqual(["total_assets"]);
    expect(ids(toGridRows(bs, { ...OFF, expanded: new Set(["total_assets"]) }))).toEqual([
      "total_assets",
      "total_current_assets",
      "total_noncurrent_assets",
      "balance_check",
    ]);
    expect(
      ids(toGridRows(bs, { ...OFF, expanded: new Set(["total_assets", "total_current_assets"]) })),
    ).toEqual([
      "total_assets",
      "total_current_assets",
      "cash",
      "total_noncurrent_assets",
      "balance_check",
    ]);
  });

  it("keeps a nested breakdown hidden when an ancestor is collapsed", () => {
    const rows = toGridRows(balanceStatement(), {
      ...OFF,
      expanded: new Set(["total_current_assets"]),
    });

    expect(ids(rows)).toEqual(["total_assets", "balance_check"]);
  });

  it("hides the sub-rows of a hidden line and keeps those of a visible one", () => {
    const rows = toGridRows(incomeStatement(), { ...OFF, yoy: true, commonSize: true });

    expect(ids(rows)).toContain("gross_profit:yoy");
    expect(ids(rows)).not.toContain("cost_of_revenue:yoy");
    expect(ids(rows)).not.toContain("cost_of_revenue:common_size");
  });

  it("lists the codes that can be expanded, ignoring rows that are not shown", () => {
    expect(expandableCodes(incomeStatement())).toEqual(["gross_profit"]);
    expect(expandableCodes(balanceStatement())).toEqual([
      "total_assets",
      "total_current_assets",
      "total_noncurrent_assets",
    ]);
  });
});

describe("canExplain", () => {
  const [revenue] = toGridRows(incomeStatement(), { ...OFF, yoy: true });
  const yoy = toGridRows(incomeStatement(), { ...OFF, yoy: true })[1];
  const annual = incomeStatement().periods[1]!;

  it("allows a value cell of a line item", () => {
    expect(canExplain(revenue!, annual)).toBe(true);
  });

  it("refuses sub-rows", () => {
    expect(canExplain(yoy!, annual)).toBe(false);
  });

  it("refuses an empty cell", () => {
    const empty = { ...revenue!, values: { ...revenue!.values, FY2024: null } };

    expect(canExplain(empty, annual)).toBe(false);
  });

  it("refuses a TTM column, which the cell endpoint does not cover", () => {
    expect(canExplain(revenue!, { ...annual, key: "TTM-FY2024Q3" })).toBe(false);
  });

  it("refuses the balance check row", () => {
    const check = toGridRows(balanceStatement(), OFF).at(-1)!;
    expect(canExplain(check, annual)).toBe(false);
  });
});

describe("rowUnitHint", () => {
  it("marks per-share and share-count rows, not USD ones", () => {
    expect(rowUnitHint("USD", "M")).toBeNull();
    expect(rowUnitHint("USD/shares", "M")).toBe("USD/share");
    expect(rowUnitHint("shares", "M")).toBe("shares millions");
    expect(rowUnitHint("%", "M")).toBeNull();
  });
});

describe("csvLabel", () => {
  it("names a sub-row after its line item, so the export is self-describing", () => {
    const rows = toGridRows(incomeStatement(), { ...OPEN, yoy: true, commonSize: true });

    expect(csvLabel(rows[0]!)).toBe("Revenue");
    expect(csvLabel(rows[1]!)).toBe("Revenue YoY");
    expect(csvLabel(rows[2]!)).toBe("Revenue % of Revenue");
  });
});

describe("adjustable", () => {
  it("carries adjustable from the payload on line rows", () => {
    const payload = incomeStatement();
    payload.rows[0]!.adjustable = true;
    const rows = toGridRows(payload, OPEN);

    expect(rows.find((r) => r.code === "revenue")?.adjustable).toBe(true);
    expect(rows.find((r) => r.code === "gross_profit")?.adjustable).toBe(false);
  });

  it("marks YoY and common-size sub-rows and the balance check as not adjustable", () => {
    const payload = incomeStatement();
    payload.rows.forEach((r) => (r.adjustable = true));
    const subs = toGridRows(payload, { ...OPEN, yoy: true, commonSize: true }).filter(
      (r) => r.kind === "yoy" || r.kind === "common_size",
    );
    expect(subs.length).toBeGreaterThan(0);
    expect(subs.every((r) => r.adjustable === false)).toBe(true);

    const check = toGridRows(balanceStatement(), OFF).at(-1);
    expect(check).toMatchObject({ kind: "balance_check", adjustable: false });
  });
});

describe("canExplain on an empty cell of an adjustable line", () => {
  const annual = incomeStatement().periods[1]!;
  const quarter = { ...annual, key: "FY2024Q2", label: "Q2 FY2024", fiscal_period: "Q2" };
  const [revenue] = toGridRows(incomeStatement(), OFF);
  const emptyLine = (adjustable: boolean) => ({
    ...revenue!,
    adjustable,
    values: { ...revenue!.values, FY2024: null, FY2024Q2: null },
  });

  it("allows an empty FY cell so an adjustment can be added there", () => {
    expect(canExplain(emptyLine(true), annual)).toBe(true);
  });

  it("allows an empty quarter cell", () => {
    expect(canExplain(emptyLine(true), quarter)).toBe(true);
  });

  it("refuses an empty cell of a non-adjustable line", () => {
    expect(canExplain(emptyLine(false), annual)).toBe(false);
  });

  it("refuses a TTM column even on an adjustable line", () => {
    const ttm = { ...annual, key: "TTM-FY2024Q3" };
    expect(canExplain(emptyLine(true), ttm)).toBe(false);
    expect(canExplain({ ...revenue!, adjustable: true }, ttm)).toBe(false);
  });

  it("refuses empty sub-row cells and the balance check, even when marked adjustable", () => {
    const empty = (kind: "yoy" | "common_size" | "balance_check") => ({
      ...emptyLine(true),
      id: `revenue:${kind}`,
      kind,
    });

    expect(canExplain(empty("yoy"), annual)).toBe(false);
    expect(canExplain(empty("common_size"), annual)).toBe(false);
    expect(canExplain(empty("balance_check"), annual)).toBe(false);
  });

  it("still allows a value cell of a non-adjustable line", () => {
    expect(canExplain({ ...revenue!, adjustable: false }, annual)).toBe(true);
  });
});

describe("showEmpty", () => {
  // `rnd` (depth 1, under gross_profit) has no value in any period.
  const withEmptyRnd = (adjustable: boolean): StatementOut => {
    const payload = incomeStatement();
    payload.rows = payload.rows.map((r) => (r.code === "rnd" ? { ...r, adjustable } : r));
    return payload;
  };

  it("drops an all-empty adjustable line while off", () => {
    const payload = withEmptyRnd(true);
    const rows = toGridRows(payload, { ...OFF, expanded: all(payload) });

    expect(rows.find((r) => r.code === "rnd")).toBeUndefined();
  });

  it("keeps an all-empty adjustable line, in display order, while on", () => {
    const payload = withEmptyRnd(true);
    const rows = toGridRows(payload, {
      ...OFF,
      expanded: new Set(expandableCodes(payload, true)),
      showEmpty: true,
    });

    expect(rows.map((r) => r.id)).toEqual([
      "revenue",
      "gross_profit",
      "cost_of_revenue",
      "rnd",
      "eps_diluted",
    ]);
    expect(rows.find((r) => r.code === "rnd")).toMatchObject({
      adjustable: true,
      values: { FY2023: null, FY2024: null },
    });
  });

  it("still drops an all-empty non-adjustable line while on", () => {
    const payload = withEmptyRnd(false);
    const rows = toGridRows(payload, {
      ...OFF,
      expanded: new Set(expandableCodes(payload, true)),
      showEmpty: true,
    });

    expect(rows.find((r) => r.code === "rnd")).toBeUndefined();
  });

  // eps_diluted gets an empty adjustable breakdown line of its own.
  const withEmptyChild = (): StatementOut => {
    const payload = incomeStatement();
    const rnd = payload.rows.find((r) => r.code === "rnd")!;
    payload.rows = [
      ...payload.rows,
      { ...rnd, code: "eps_adj", label: "EPS adj", adjustable: true },
    ];
    return payload;
  };

  it("makes a parent whose only breakdown is an empty adjustable line expandable only while on", () => {
    const payload = withEmptyChild();

    expect(expandableCodes(payload)).not.toContain("eps_diluted");
    expect(expandableCodes(payload, false)).not.toContain("eps_diluted");
    expect(expandableCodes(payload, true)).toContain("eps_diluted");
    const eps = toGridRows(payload, { ...OFF, showEmpty: true }).find(
      (r) => r.code === "eps_diluted",
    );
    expect(eps).toMatchObject({ hasChildren: true, expanded: false });
    const epsOff = toGridRows(payload, OFF).find((r) => r.code === "eps_diluted");
    expect(epsOff?.hasChildren).toBe(false);
  });

  it("hides a shown empty line under a collapsed parent", () => {
    const payload = withEmptyChild();
    const collapsed = toGridRows(payload, { ...OFF, showEmpty: true });
    const open = toGridRows(payload, {
      ...OFF,
      expanded: new Set(["eps_diluted"]),
      showEmpty: true,
    });

    expect(collapsed.find((r) => r.code === "eps_adj")).toBeUndefined();
    expect(open.at(-1)?.code).toBe("eps_adj");
  });
});

describe("showEmpty with a hidden ancestor", () => {
  // Lines built from the fixture: `revenue` has values, `rnd` has none in any period.
  const line = (code: string, depth: number, adjustable: boolean, empty: boolean) => {
    const template = incomeStatement().rows.find((r) => r.code === (empty ? "rnd" : "revenue"))!;
    return { ...template, code, label: code, depth, adjustable };
  };
  const payloadOf = (rows: StatementOut["rows"]): StatementOut => ({ ...incomeStatement(), rows });

  // X has values; S is a computed, all-empty subtotal; c is its empty adjustable breakdown.
  const xsc = () =>
    payloadOf([line("x", 0, false, false), line("s", 0, false, true), line("c", 1, true, true)]);
  const ON = { ...OFF, showEmpty: true };

  it("shows the hidden ancestor and keeps the empty line under it", () => {
    const payload = xsc();
    const rows = toGridRows(payload, { ...ON, expanded: new Set(["s"]) });

    expect(rows.map((r) => r.id)).toEqual(["x", "s", "c"]);
    expect(rows.find((r) => r.code === "x")?.hasChildren).toBe(false);
    expect(rows.find((r) => r.code === "s")).toMatchObject({
      hasChildren: true,
      expanded: true,
      adjustable: false,
      values: { FY2023: null, FY2024: null },
    });
  });

  it("lists the shown ancestor, not the preceding line, as expandable", () => {
    const payload = xsc();

    expect(expandableCodes(payload, true)).toEqual(["s"]);
    expect(expandableCodes(payload)).toEqual([]);
  });

  it("hides the empty line while the shown ancestor is collapsed", () => {
    const rows = toGridRows(xsc(), ON);

    expect(rows.map((r) => r.id)).toEqual(["x", "s"]);
  });

  it("changes nothing while off", () => {
    const payload = xsc();
    const rows = toGridRows(payload, { ...OFF, expanded: new Set(["x", "s"]) });

    expect(rows.map((r) => r.id)).toEqual(["x"]);
  });

  it("shows every level of hidden ancestors", () => {
    const payload = payloadOf([
      line("x", 0, false, false),
      line("s0", 0, false, true),
      line("s1", 1, false, true),
      line("c", 2, true, true),
    ]);
    const rows = toGridRows(payload, { ...ON, expanded: new Set(["s0", "s1"]) });

    expect(rows.map((r) => [r.id, r.depth, r.hasChildren])).toEqual([
      ["x", 0, false],
      ["s0", 0, true],
      ["s1", 1, true],
      ["c", 2, false],
    ]);
    expect(expandableCodes(payload, true)).toEqual(["s0", "s1"]);
  });

  it("keeps a hidden empty line hidden when nothing in its subtree is shown", () => {
    const payload = payloadOf([
      line("x", 0, false, false),
      line("s", 0, false, true),
      line("n", 1, false, true),
      line("y", 0, false, false),
      line("c", 1, true, true),
    ]);
    const rows = toGridRows(payload, { ...ON, expanded: new Set(["y"]) });

    expect(rows.map((r) => r.id)).toEqual(["x", "y", "c"]);
  });

  it("leaves the shown ancestor's cells inert while the empty line's open", () => {
    const rows = toGridRows(xsc(), { ...ON, expanded: new Set(["s"]) });
    const annual = incomeStatement().periods[1]!;

    expect(
      canExplain(
        rows.find((r) => r.code === "s")!,
        annual,
      ),
    ).toBe(false);
    expect(
      canExplain(
        rows.find((r) => r.code === "c")!,
        annual,
      ),
    ).toBe(true);
  });
});

describe("note markers", () => {
  const index = noteIndex(noteLinks());
  const rows = toGridRows(incomeStatement(), { ...OFF, yoy: true });
  const revenue = rows[0]!;
  const yoy = rows[1]!;
  const [fy2023, fy2024] = incomeStatement().periods as [PeriodOut, PeriodOut];

  it("counts the notes of a cell by code, year and period", () => {
    expect(cellNoteCount(index, revenue, fy2024)).toBe(2);
    expect(cellNoteCount(index, revenue, fy2023)).toBe(0);
  });

  it("counts the line-only notes of a line", () => {
    const sga = { ...revenue, code: "sga" };
    expect(lineNoteCount(index, sga)).toBe(1);
    expect(lineNoteCount(index, revenue)).toBe(0);
  });

  it("does not mix a cell note into the line count or the reverse", () => {
    const sga = { ...revenue, code: "sga" };
    expect(cellNoteCount(index, sga, fy2024)).toBe(0);
  });

  it("never marks a TTM column", () => {
    const ttm = { ...fy2024, key: "TTM-FY2024Q3", fiscal_period: "FY" };
    expect(cellNoteCount(index, revenue, ttm)).toBe(0);
  });

  it("marks a quarter cell", () => {
    const quarterly = noteIndex([
      noteLink({ canonical_code: "revenue", fiscal_year: 2024, fiscal_period: "Q4" }),
    ]);
    expect(
      cellNoteCount(quarterly, revenue, { ...fy2024, key: "Q42024", fiscal_period: "Q4" }),
    ).toBe(1);
  });

  it("never marks a sub-row", () => {
    expect(cellNoteCount(index, yoy, fy2024)).toBe(0);
    expect(lineNoteCount(index, { ...yoy, code: "sga" })).toBe(0);
  });

  it("ignores period-only links", () => {
    const periodOnly = noteIndex([noteLink({ fiscal_year: 2024, fiscal_period: "FY", count: 4 })]);
    expect(cellNoteCount(periodOnly, revenue, fy2024)).toBe(0);
  });

  it("marks nothing without links", () => {
    expect(cellNoteCount(noteIndex([]), revenue, fy2024)).toBe(0);
    expect(lineNoteCount(noteIndex([]), revenue)).toBe(0);
  });
});

describe("provenance display", () => {
  it("styles derived and approximated cells alike, so what is not a hard fact stands out", () => {
    expect(provenanceClasses("derived")).toEqual(["prov-derived"]);
    expect(provenanceClasses("approximated")).toEqual(["prov-derived"]);
  });

  it("styles an imported value apart from the SEC ones", () => {
    expect(provenanceClasses("imported")).toEqual(["prov-imported"]);
  });

  it("mutes an inferred zero and styles normalized cells apart", () => {
    expect(provenanceClasses("zero_inferred")).toEqual(["prov-zero"]);
    expect(provenanceClasses("normalized")).toEqual(["prov-normalized"]);
  });

  it("leaves reported and empty cells plain", () => {
    expect(provenanceClasses("reported")).toEqual([]);
    expect(provenanceClasses(null)).toEqual([]);
    expect(provenanceClasses(undefined)).toEqual([]);
  });

  it("marks only an approximated value with a tilde", () => {
    expect(provenanceMark("approximated")).toBe("~");
    for (const other of [
      "reported",
      "derived",
      "normalized",
      "zero_inferred",
      "imported",
      null,
    ] as const) {
      expect(provenanceMark(other)).toBe("");
    }
  });
});

describe("custom lines", () => {
  const payload = customIncomeStatement();
  const open = { ...OFF, expanded: new Set(["gross_profit", "cost_of_revenue"]) };
  const period = payload.periods[1]!;

  it("hides the breakdown under a collapsed parent and opens it with the parent", () => {
    expect(toGridRows(payload, OFF).map((row) => row.id)).not.toContain("custom:products");
    expect(expandableCodes(payload)).toContain("cost_of_revenue");
    const rows = toGridRows(payload, open);
    expect(rows.map((row) => row.id)).toEqual([
      "revenue",
      "gross_profit",
      "cost_of_revenue",
      "custom:products",
      "custom:services",
      "other:cost_of_revenue",
      "eps_diluted",
    ]);
  });

  it("flags custom lines, indents them under the parent and keeps their imported provenance", () => {
    const rows = toGridRows(payload, open);
    const parent = rows.find((row) => row.id === "cost_of_revenue")!;
    const products = rows.find((row) => row.id === "custom:products")!;
    expect(products.custom).toBe(true);
    expect(products.depth).toBe(parent.depth + 1);
    expect(products.provenance.FY2024).toBe("imported");
    expect(parent.custom).toBe(false);
    expect(rows.find((row) => row.id === "other:cost_of_revenue")!.custom).toBe(false);
  });

  it("explains a custom line but not the Other row", () => {
    const rows = toGridRows(payload, open);
    const products = rows.find((row) => row.id === "custom:products")!;
    const other = rows.find((row) => row.id === "other:cost_of_revenue")!;
    expect(canExplain(products, period)).toBe(true);
    expect(canExplain(other, period)).toBe(false);
  });
});
