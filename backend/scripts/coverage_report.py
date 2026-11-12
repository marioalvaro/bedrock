"""Coverage and the cause of every empty statement cell, for a set of companies (M7b S1).

Usage (from backend/):
  uv run python scripts/coverage_report.py --fixtures AAPL MSFT ...   recorded fixtures
  uv run python scripts/coverage_report.py --db PATH                  every company of a database
  uv run python scripts/coverage_report.py --holdout                  DATA_DIR/holdout.db
Options:
  --totals-only    print the totals and buckets only (implied by --holdout)
  --json OUT       also write the report (and the sweep or evidence) as JSON
  --evidence CODE  every candidate concept of one canonical line, by company and fiscal year, with
                   its value and its us-gaap label and description
  --sweep          the us-gaap concepts of each latest 10-K that no mapping uses (companies carrying
                   them, median size against revenue or total assets) and each residual's median
                   share of its parent

--holdout prints totals only and refuses --evidence; its --sweep shows pooled counts and medians.
A database is read from a copy, never in place: do not point --db at the file of a running Docker
stack (docs/Gotcha.md G44). The holdout set is read for its aggregate numbers only
(docs/erd/data-coverage.md, "Principles").
"""

import argparse
import gzip
import json
import shutil
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:  # `tests` is a package of backend/, not of the installed app
    sys.path.insert(0, str(BACKEND))

from bedrock.core.config import load_settings  # noqa: E402
from bedrock.core.db import make_engine, make_sessionmaker  # noqa: E402
from bedrock.repositories import companies as companies_repo  # noqa: E402
from bedrock.services.coverage import CompanyCoverage, company_coverage  # noqa: E402
from bedrock.services.statements import candidate_index  # noqa: E402
from bedrock.statements.build import RATIO_PLACES, StatementTable  # noqa: E402
from bedrock.statements.census import ANNUAL_DAYS, END_TOLERANCE  # noqa: E402

STATEMENTS = ("IS", "BS", "CF")
FREQS = ("annual", "quarterly")
TOP_LINES = 40
# buckets of cells that cannot exist: not gaps, so not among the top empty lines
NOT_GAPS = frozenset({"statement_not_presented", "not_applicable"})
Labels = dict[str, tuple[str, str]]  # us-gaap concept -> (label, description)


@dataclass(frozen=True)
class Entry:
    ticker: str
    coverage: CompanyCoverage
    labels: Labels


# --- sources ---------------------------------------------------------------------------------


def fixture_companies(tickers: Sequence[str]) -> list[Entry]:
    from tests.statements_pipeline import FIXTURES, fixture_coverage

    entries = []
    for ticker in dict.fromkeys(t.upper() for t in tickers):
        with gzip.open(FIXTURES / f"{ticker}.json.gz", "rt") as handle:
            labels = _labels(json.load(handle))
        entries.append(Entry(ticker, fixture_coverage(ticker), labels))
    return entries


def db_companies(path: Path, data_dir: Path) -> list[Entry]:
    """Every company of the database at `path`, read from a copy of the file (and its WAL)."""
    with _copy(path) as copy:
        engine = make_engine(f"sqlite:///{copy}")
        try:
            with make_sessionmaker(engine)() as session:
                return [
                    Entry(c.ticker, company_coverage(session, c), _cached_labels(data_dir, c.cik))
                    for c in sorted(companies_repo.list_all(session), key=lambda c: c.ticker)
                ]
        finally:
            engine.dispose()


@contextmanager
def _copy(path: Path) -> Iterator[Path]:
    if not path.is_file():
        raise FileNotFoundError(f"no database at {path}")
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / path.name
        for suffix in ("", "-wal"):
            source = path.with_name(path.name + suffix)
            if source.is_file():
                shutil.copyfile(source, copy.with_name(copy.name + suffix))
        yield copy


def _labels(companyfacts: dict[str, Any]) -> Labels:
    concepts = companyfacts.get("facts", {}).get("us-gaap", {})
    return {
        name: (str(body.get("label") or ""), str(body.get("description") or ""))
        for name, body in concepts.items()
    }


def _cached_labels(data_dir: Path, cik: str | None) -> Labels:
    """From the newest companyfacts JSON the app cached for the company (`RawCache`)."""
    folder = data_dir / "raw" / "edgar" / (cik or "")
    files = sorted(folder.glob("*.json")) if cik else []
    return _labels(json.loads(files[-1].read_text())) if files else {}


# --- the report ------------------------------------------------------------------------------


def _ratio(filled: int, applicable: int) -> str | None:
    return (
        str((Decimal(filled) / Decimal(applicable)).quantize(RATIO_PLACES)) if applicable else None
    )


def report(entries: Sequence[Entry]) -> dict[str, Any]:
    """JSON-native: counts are ints, ratios are decimal strings (or null)."""
    companies: dict[str, dict[str, Any]] = {}
    totals: dict[str, dict[str, Any]] = {
        f: {
            "cells": 0,
            "filled": 0,
            "strict_cells": 0,
            "applicable_cells": 0,
            "buckets": Counter[str](),
        }
        for f in FREQS
    }
    empty_lines: dict[str, Counter[str]] = defaultdict(Counter)
    for entry in entries:
        rows: dict[str, Any] = {}
        for (statement, freq), table in entry.coverage.census.tables.items():
            cov = table.coverage
            causes = cov.empty_by_cause
            strict_cells = cov.cells - causes["no_filing_data"]
            applicable_cells = strict_cells - causes["not_applicable"] - causes["included_in"]
            rows[f"{statement}/{freq}"] = {
                "cells": cov.cells,
                "filled": cov.filled,
                "strict_cells": strict_cells,
                "applicable_cells": applicable_cells,
                "strict": _ratio(cov.filled, strict_cells),
                "applicable": _ratio(cov.filled, applicable_cells),
                "buckets": dict(table.counts),
            }
            total = totals[freq]
            total["cells"] += cov.cells
            total["filled"] += cov.filled
            total["strict_cells"] += strict_cells
            total["applicable_cells"] += applicable_cells
            total["buckets"].update(table.counts)
            if freq == "annual":
                for (code, _), bucket in table.buckets.items():
                    if bucket not in NOT_GAPS:
                        empty_lines[code][entry.ticker] += 1
        companies[entry.ticker] = rows
    top = sorted(empty_lines.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:TOP_LINES]
    return {
        "companies": companies,
        "totals": {
            f: {
                "cells": t["cells"],
                "filled": t["filled"],
                "strict_cells": t["strict_cells"],
                "applicable_cells": t["applicable_cells"],
                "strict": _ratio(t["filled"], t["strict_cells"]),
                "applicable": _ratio(t["filled"], t["applicable_cells"]),
                "buckets": dict(t["buckets"]),
            }
            for f, t in totals.items()
        },
        "top_lines": [
            {"code": code, "empty": sum(by.values()), "companies": dict(sorted(by.items()))}
            for code, by in top
        ],
    }


def _pct(ratio: str | None) -> str:
    return "  n/a" if ratio is None else f"{Decimal(ratio) * 100:5.1f}"


def _both(row: dict[str, Any]) -> str:
    return f"{_pct(row['strict']).strip()}/{_pct(row['applicable']).strip()}"


def render(result: dict[str, Any], totals_only: bool = False) -> str:
    """`totals_only` leaves out every company and every line: what the holdout may show."""
    lines = [
        "Coverage, % strict / applicable (strict: filled / cells of periods with the statement;",
        "applicable also leaves out cells that cannot exist)",
        "",
    ]
    if not totals_only:
        keys = [f"{s}/{f}" for f in FREQS for s in STATEMENTS]
        lines.append(f"{'company':<8}" + "".join(f"{k:>14}" for k in keys))
        for ticker, rows in result["companies"].items():
            lines.append(
                f"{ticker:<8}" + "".join(f"{_both(rows[k]) if k in rows else '':>14}" for k in keys)
            )
        lines.append("")
    for freq, total in result["totals"].items():
        lines.append(
            f"Total {freq}: strict {_pct(total['strict']).strip()}% "
            f"({total['filled']} of {total['strict_cells']}), "
            f"applicable {_pct(total['applicable']).strip()}% "
            f"({total['filled']} of {total['applicable_cells']}), {total['cells']} cells"
        )
        empty = sum(total["buckets"].values()) or 1
        for bucket, n in total["buckets"].items():
            share = Decimal(n) / Decimal(total["strict_cells"] or 1) * 100
            lines.append(
                f"  {bucket:<24}{n:>8}  {share:5.1f}% of strict cells"
                f"  ({n * 100 // empty}% of empty)"
            )
    if totals_only:
        return "\n".join(lines)
    lines += ["", f"Top empty lines (annual, cells that cannot exist left out, top {TOP_LINES})"]
    for line in result["top_lines"]:
        names = ", ".join(f"{t} {n}" for t, n in line["companies"].items())
        lines.append(f"  {line['code']:<40}{line['empty']:>5}  {names}")
    return "\n".join(lines)


# --- evidence --------------------------------------------------------------------------------


def evidence(entries: Sequence[Entry], code: str) -> list[dict[str, Any]]:
    """For one canonical code: each concept mapped to it or given it by the candidate index, by
    company and fiscal year (annual facts of 350-380 days, or instants, at a fiscal year end), the
    latest vintage, with its us-gaap label and description."""
    indexed = {c for (t, c), codes in candidate_index().items() if t == "us-gaap" and code in codes}
    rows: list[dict[str, Any]] = []
    for entry in entries:
        mappings = entry.coverage.mappings
        mine = mappings[mappings["canonical_code"] == code]
        mapped = set(mine["concept"][mine["taxonomy"] == "us-gaap"])
        facts = entry.coverage.facts
        facts = facts[(facts["taxonomy"] == "us-gaap") & facts["concept"].isin(mapped | indexed)]
        ends = _year_ends(entry.coverage.tables)
        latest: dict[tuple[str, int], tuple[date, Any]] = {}
        for concept, start, end, value, filed in zip(
            facts["concept"],
            facts["period_start"],
            facts["period_end"],
            facts["value"],
            facts["filed_at"],
            strict=True,
        ):
            if not _annual(start, end):
                continue
            year = _fiscal_year(ends, end)
            if year is None:
                continue
            if (concept, year) not in latest or filed > latest[(concept, year)][0]:
                latest[(concept, year)] = (filed, value)
        for (concept, year), (_, value) in sorted(latest.items()):
            label, description = entry.labels.get(concept, ("", ""))
            rows.append(
                {
                    "ticker": entry.ticker,
                    "concept": concept,
                    "mapped": concept in mapped,
                    "fiscal_year": year,
                    "value": str(value),
                    "label": label,
                    "description": description,
                }
            )
    return rows


def render_evidence(rows: Sequence[dict[str, Any]]) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row["concept"] not in seen:
            seen.add(row["concept"])
            out += ["", f"{row['concept']}: {row['label']}", f"  {row['description']}"]
        flag = "mapped" if row["mapped"] else "candidate"
        out.append(f"  {row['ticker']:<6} FY{row['fiscal_year']}  {row['value']:>20}  {flag}")
    return "\n".join(out)


def _annual(start: Any, end: date) -> bool:
    if start is None or pd.isna(start):
        return True
    days: int = (end - start).days
    return ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]


def _year_ends(tables: dict[tuple[str, str], StatementTable]) -> dict[int, date]:
    return {p.fiscal_year: p.end for t in tables.values() if t.freq == "annual" for p in t.periods}


def _fiscal_year(ends: dict[int, date], end: date) -> int | None:
    return next((y for y, e in ends.items() if abs(e - end) <= END_TOLERANCE), None)


# --- sweep -----------------------------------------------------------------------------------


def sweep(entries: Sequence[Entry]) -> dict[str, Any]:
    """Unmapped us-gaap concepts of each latest 10-K, sized at the 10-K's own fiscal year end in
    USD against `revenue` (a flow) or `total_assets` (an instant); each residual's share of its
    parent at the same year; and every canonical value of that year, per company."""
    shares: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(dict)
    residual_shares: dict[str, list[Decimal]] = defaultdict(list)
    values: dict[str, dict[str, str]] = {}
    items = {i.code: i for e in entries for i in e.coverage.items}
    for entry in entries:
        end, latest = _latest_year(entry.coverage)
        values[entry.ticker] = {k: str(v) for k, v in latest.items()}
        tenk = entry.coverage.latest_10k
        if tenk.empty or end is None:
            continue
        mappings = entry.coverage.mappings
        mapped = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))
        for taxonomy, concept, unit, start, fact_end, value in zip(
            tenk["taxonomy"],
            tenk["concept"],
            tenk["unit"],
            tenk["period_start"],
            tenk["period_end"],
            tenk["value"],
            strict=True,
        ):
            if (
                taxonomy != "us-gaap"
                or ("us-gaap", concept) in mapped
                or unit != "USD"
                or abs(fact_end - end) > END_TOLERANCE
            ):
                continue
            if not _annual(start, fact_end):
                continue
            anchor = "total_assets" if start is None or pd.isna(start) else "revenue"
            base = latest.get(anchor)
            if base:
                shares[(concept, anchor)][entry.ticker] = abs(Decimal(value)) / abs(base)
        for code, item in items.items():
            if item.residual and item.parent and latest.get(item.parent) and code in latest:
                residual_shares[code].append(abs(latest[code]) / abs(latest[item.parent]))
    concepts: list[dict[str, Any]] = [
        {
            "concept": concept,
            "anchor": anchor,
            "companies": len(by),
            "median_share": str(_median(by.values())),
            "shares": {t: str(s.quantize(RATIO_PLACES)) for t, s in sorted(by.items())},
        }
        for (concept, anchor), by in shares.items()
    ]
    concepts.sort(key=lambda r: (-r["companies"], -Decimal(r["median_share"]), r["concept"]))
    residuals = [
        {
            "code": code,
            "parent": items[code].parent,
            "companies": len(residual_shares.get(code, [])),
            "median_share": str(_median(residual_shares[code]))
            if residual_shares.get(code)
            else None,
        }
        for code, item in items.items()
        if item.residual and item.parent
    ]
    return {"concepts": concepts, "residuals": residuals, "values": values}


def _median(values: Any) -> Decimal:
    return Decimal(statistics.median(list(values))).quantize(RATIO_PLACES)


def _latest_year(coverage: CompanyCoverage) -> tuple[date | None, dict[str, Decimal]]:
    """The end of the newest fiscal year with an income statement value, and every canonical
    value of that year."""
    income = coverage.tables.get(("IS", "annual"))
    if income is None:
        return None, {}
    filled = [
        p for n, p in enumerate(income.periods) if any(r.values[n] is not None for r in income.rows)
    ]
    if not filled:
        return None, {}
    newest = max(filled, key=lambda p: p.fiscal_year)
    out: dict[str, Decimal] = {}
    for statement in STATEMENTS:
        table = coverage.tables[(statement, "annual")]
        at = next((n for n, p in enumerate(table.periods) if p.key == newest.key), None)
        if at is None:
            continue
        for row in table.rows:
            if row.values[at] is not None:
                out[row.code] = Decimal(row.values[at])
    return newest.end, out


def render_sweep(result: dict[str, Any], limit: int = 80) -> str:
    out = [f"Unmapped us-gaap concepts in the latest 10-K (top {limit} by companies)"]
    for row in result["concepts"][:limit]:
        pct = Decimal(row["median_share"]) * 100
        out.append(f"  {row['concept']:<70}{row['companies']:>4}  {pct:6.2f}% of {row['anchor']}")
    out += ["", "Residuals: median share of their parent"]
    for row in result["residuals"]:
        share = (
            "n/a" if row["median_share"] is None else f"{Decimal(row['median_share']) * 100:.1f}%"
        )
        out.append(
            f"  {row['code']:<32} of {row['parent']:<30} {share:>7}  ({row['companies']} companies)"
        )
    return "\n".join(out)


# --- main ------------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="coverage_report.py", add_help=True)
    parser.add_argument("--fixtures", nargs="+", metavar="TICKER")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--json", type=Path, metavar="OUT")
    parser.add_argument("--evidence", metavar="CODE")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--totals-only", action="store_true")
    args = parser.parse_args(argv)
    if sum(bool(x) for x in (args.fixtures, args.db, args.holdout)) != 1:
        print(__doc__)
        return 2
    if args.evidence and args.holdout:
        print(
            "--evidence is per company and concept: the holdout shows totals only", file=sys.stderr
        )
        return 2
    if args.evidence and args.sweep:
        print("--evidence and --sweep are separate runs", file=sys.stderr)
        return 2
    settings = load_settings()
    try:
        if args.fixtures:
            entries = fixture_companies(args.fixtures)
        else:
            path = args.db or settings.data_dir / "holdout.db"
            entries = db_companies(path, settings.data_dir)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2

    output: dict[str, Any] = report(entries)
    if args.evidence:
        known = {i.code for e in entries for i in e.coverage.items}
        if args.evidence not in known:
            print(f"unknown canonical code: {args.evidence}", file=sys.stderr)
            return 2
        output["evidence"] = evidence(entries, args.evidence)
        print(render_evidence(output["evidence"]))
    elif args.sweep:
        output["sweep"] = sweep(entries)
        print(render_sweep(output["sweep"]))
    else:
        print(render(output, totals_only=args.totals_only or args.holdout))
    if args.holdout:  # aggregates only: no company and no line leaves the holdout run
        output = {k: v for k, v in output.items() if k not in ("companies", "top_lines")}
    if args.json:
        args.json.write_text(json.dumps(output, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
