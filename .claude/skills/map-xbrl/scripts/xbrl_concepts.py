#!/usr/bin/env python3
"""Explore SEC companyfacts JSON to choose XBRL concepts for canonical line items.

Usage:
  xbrl_concepts.py fetch TICKER                   download companyfacts into data/raw/edgar/<cik>/<date>.json
                                                  (needs env SEC_USER_AGENT, e.g. "Bedrock you@example.com")
  xbrl_concepts.py search FILE REGEX [--form 10-K] [--years 5]
                                                  concepts whose name or label matches REGEX, with coverage
                                                  and the latest annual values
  xbrl_concepts.py show FILE CONCEPT [--form 10-K|10-Q|any] [--all-vintages]
                                                  values by period for one concept (latest filing per period
                                                  unless --all-vintages)

FILE is a companyfacts JSON (fixture or cache). CONCEPT may be "Revenues" or "us-gaap:Revenues".
Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _get(url: str) -> bytes:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        sys.exit("SEC_USER_AGENT is not set (SEC requires an identifying User-Agent).")
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch(ticker: str) -> None:
    tickers = json.loads(_get("https://www.sec.gov/files/company_tickers.json"))
    match = [v for v in tickers.values() if v["ticker"].upper() == ticker.upper()]
    if not match:
        sys.exit(f"Ticker {ticker} not found in SEC company_tickers.json")
    cik = f"{match[0]['cik_str']:010d}"
    body = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    out = ROOT / "data/raw/edgar" / cik / f"{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    print(out)


def load(path: str) -> dict:
    return json.loads(Path(path).read_text())["facts"]


def facts_of(concept: dict) -> list[tuple[str, dict]]:
    return [(unit, f) for unit, rows in concept.get("units", {}).items() for f in rows]


def latest_per_period(rows: list[tuple[str, dict]]) -> dict[tuple, tuple[str, dict]]:
    """Latest-filed value for each (unit, start, end): the default 'latest view'."""
    best: dict[tuple, tuple[str, dict]] = {}
    for unit, f in rows:
        key = (unit, f.get("start"), f["end"])
        if key not in best or f["filed"] > best[key][1]["filed"]:
            best[key] = (unit, f)
    return best


def is_annual(f: dict) -> bool:
    if "start" not in f:
        return f.get("fp") == "FY"
    days = (dt.date.fromisoformat(f["end"]) - dt.date.fromisoformat(f["start"])).days
    return 350 <= days <= 380


def search(path: str, pattern: str, form: str, years: int) -> None:
    rx = re.compile(pattern, re.I)
    for tax, concepts in load(path).items():
        for name, c in sorted(concepts.items()):
            if not (rx.search(name) or rx.search(c.get("label") or "")):
                continue
            rows = [(u, f) for u, f in facts_of(c) if form == "any" or f.get("form", "").startswith(form)]
            if not rows:
                continue
            annual = sorted(
                (f["end"], u, f["val"]) for u, f in latest_per_period(rows).values() if is_annual(f)
            )
            ends = [f["end"] for _, f in rows]
            print(f"{tax}:{name}  [{', '.join(sorted({u for u, _ in rows}))}]  {c.get('label')!r}")
            print(f"    facts={len(rows)}  period_end {min(ends)} .. {max(ends)}")
            for end, unit, val in annual[-years:]:
                print(f"    FY end {end}: {val:>20,} {unit}")


def show(path: str, concept: str, form: str, all_vintages: bool) -> None:
    tax, _, name = concept.rpartition(":")
    facts = load(path)
    taxes = [tax] if tax else list(facts)
    found = [facts[t][name] for t in taxes if name in facts.get(t, {})]
    if not found:
        sys.exit(f"{concept} not found")
    rows = [(u, f) for u, f in facts_of(found[0]) if form == "any" or f.get("form", "").startswith(form)]
    if not all_vintages:
        rows = list(latest_per_period(rows).values())
    print(f"{'start':<11} {'end':<11} {'fy':<5} {'fp':<3} {'form':<7} {'filed':<11} {'accn':<21} value")
    for u, f in sorted(rows, key=lambda r: (r[1]["end"], r[1].get("start") or "", r[1]["filed"])):
        print(
            f"{f.get('start', '-'):<11} {f['end']:<11} {f.get('fy', ''):<5} {f.get('fp', ''):<3} "
            f"{f.get('form', ''):<7} {f['filed']:<11} {f['accn']:<21} {f['val']:,} {u}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("ticker")
    p = sub.add_parser("search")
    p.add_argument("file")
    p.add_argument("regex")
    p.add_argument("--form", default="10-K")
    p.add_argument("--years", type=int, default=5)
    p = sub.add_parser("show")
    p.add_argument("file")
    p.add_argument("concept")
    p.add_argument("--form", default="any")
    p.add_argument("--all-vintages", action="store_true")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.ticker)
    elif a.cmd == "search":
        search(a.file, a.regex, a.form, a.years)
    else:
        show(a.file, a.concept, a.form, a.all_vintages)


if __name__ == "__main__":
    main()
