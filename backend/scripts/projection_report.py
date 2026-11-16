"""Where every face line of every parsed filing lands against the canonical rows, and whether the
filings' own sums foot (M7d S1, docs/erd/face-tree.md "Report").

Usage (from backend/):
  uv run python scripts/projection_report.py --fixtures AAPL MSFT ...   recorded fixtures
  uv run python scripts/projection_report.py --db PATH                  every company of a database
  uv run python scripts/projection_report.py --holdout                  DATA_DIR/holdout.db
Options:
  --json OUT   also write the report as JSON

--holdout prints totals only. A database is read from a copy, never in place: do not point --db at
the file of a running Docker stack (docs/Gotcha.md G44). The holdout set is read for its aggregate
numbers only (docs/erd/data-coverage.md, "Principles"). The counting is
`statements/projection_stats.py`; this script only loads and prints.
"""

import argparse
import json
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:  # `tests` is a package of backend/, not of the installed app
    sys.path.insert(0, str(BACKEND))

from bedrock.core.config import load_settings  # noqa: E402
from bedrock.core.db import make_engine, make_sessionmaker  # noqa: E402
from bedrock.mapping.config import CanonicalItemDef  # noqa: E402
from bedrock.repositories import companies as companies_repo  # noqa: E402
from bedrock.services.statements import load_inputs  # noqa: E402
from bedrock.statements.build import RATIO_PLACES  # noqa: E402
from bedrock.statements.cells import solve_cells  # noqa: E402
from bedrock.statements.imports import company_calendar  # noqa: E402
from bedrock.statements.periods import annual_periods  # noqa: E402
from bedrock.statements.projection import project_all  # noqa: E402
from bedrock.statements.projection_stats import (  # noqa: E402
    StatementStats,
    face_disagreements,
    tally,
)
from bedrock.statements.rules import Rules  # noqa: E402

GROUPS = ("10-K", "10-Q")
STATEMENTS = ("IS", "BS", "CF")
KINDS = ("mapped", "other", "open")


@dataclass(frozen=True)
class Entry:
    ticker: str
    stats: dict[tuple[str, str], StatementStats]
    disagreements: Counter[str]


def _entry(
    ticker: str,
    canonical: pd.DataFrame,
    items: Sequence[CanonicalItemDef],
    rules: Rules,
) -> Entry | None:
    """None for a company with no parsed filing."""
    face = rules.filing_lines
    if face is None:
        return None
    calendar = company_calendar(canonical, rules.imported)
    cells = solve_cells(canonical, items, calendar, rules).cells
    return Entry(
        ticker,
        tally(project_all(face, items)),
        face_disagreements(cells, annual_periods(calendar), face, items),
    )


# --- sources ---------------------------------------------------------------------------------


def fixture_companies(tickers: Sequence[str]) -> list[Entry]:
    from tests.statements_pipeline import run_pipeline

    entries = []
    for ticker in dict.fromkeys(t.upper() for t in tickers):
        pipeline = run_pipeline(ticker)
        entry = _entry(ticker, pipeline.canonical, pipeline.items, pipeline.rules)
        if entry is not None:
            entries.append(entry)
    return entries


def db_companies(path: Path) -> list[Entry]:
    """Every company of the database at `path` with a parsed filing, read from a copy."""
    with _copy(path) as copy:
        engine = make_engine(f"sqlite:///{copy}")
        try:
            with make_sessionmaker(engine)() as session:
                entries = []
                for company in sorted(companies_repo.list_all(session), key=lambda c: c.ticker):
                    loaded = load_inputs(session, company)
                    entry = _entry(company.ticker, loaded.canonical, loaded.lines, loaded.rules)
                    if entry is not None:
                        entries.append(entry)
                return entries
        finally:
            engine.dispose()


@contextmanager
def _copy(path: Path) -> Iterator[Path]:
    """The same copy as `coverage_report.py`: the file and its WAL, in a temporary folder."""
    if not path.is_file():
        raise FileNotFoundError(f"no database at {path}")
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / path.name
        for suffix in ("", "-wal"):
            source = path.with_name(path.name + suffix)
            if source.is_file():
                shutil.copyfile(source, copy.with_name(copy.name + suffix))
        yield copy


# --- the report ------------------------------------------------------------------------------


def _ratio(part: int, whole: int) -> str | None:
    return str((Decimal(part) / Decimal(whole)).quantize(RATIO_PLACES)) if whole else None


def _group(stats: StatementStats) -> dict[str, Any]:
    checks = stats.foot + stats.foot_missing_child + stats.not_foot
    return {
        "statements": stats.statements,
        "lines": stats.lines,
        "kinds": {k: stats.kinds[k] for k in KINDS},
        "kind_shares": {k: _ratio(stats.kinds[k], stats.lines) for k in KINDS},
        "in_tree": stats.in_tree,
        "in_tree_share": _ratio(stats.in_tree, stats.lines),
        "open_lines": stats.open_lines,
        "open_with_block_share": _ratio(stats.open_with_block, stats.open_lines),
        "checks": checks,
        "foot": stats.foot,
        "foot_missing_child": stats.foot_missing_child,
        "not_foot": stats.not_foot,
        "statements_with_checks": stats.with_checks,
        "statements_all_foot": stats.all_foot,
        "all_foot_share": _ratio(stats.all_foot, stats.with_checks),
    }


def _merge(parts: Sequence[StatementStats]) -> StatementStats:
    total = StatementStats()
    for part in parts:
        for name in (
            "statements",
            "lines",
            "in_tree",
            "open_lines",
            "open_with_block",
            "foot",
            "foot_missing_child",
            "not_foot",
            "with_checks",
            "all_foot",
        ):
            setattr(total, name, getattr(total, name) + getattr(part, name))
        total.kinds.update(part.kinds)
    return total


def report(entries: Sequence[Entry]) -> dict[str, Any]:
    """JSON-native: counts are ints, shares are decimal strings (or null)."""
    groups: dict[str, Any] = {}
    for group in GROUPS:
        for statement in STATEMENTS:
            parts = [e.stats[(group, statement)] for e in entries if (group, statement) in e.stats]
            if parts:
                groups[f"{group}/{statement}"] = _group(_merge(parts))
    disagreements: Counter[str] = Counter()
    by_company: dict[str, dict[str, int]] = {}
    for entry in entries:
        disagreements.update(entry.disagreements)
        by_company[entry.ticker] = dict(sorted(entry.disagreements.items()))
    return {
        "companies": [e.ticker for e in entries],
        "groups": groups,
        "face_disagreements": dict(sorted(disagreements.items(), key=lambda kv: (-kv[1], kv[0]))),
        "face_disagreements_by_company": by_company,
    }


def _pct(ratio: str | None) -> str:
    return "  n/a" if ratio is None else f"{Decimal(ratio) * 100:5.1f}"


def render(result: Mapping[str, Any], totals_only: bool = False) -> str:
    """`totals_only` leaves out every company: what the holdout may show."""
    out: list[str] = []
    if not totals_only:
        out += [f"Companies: {', '.join(result['companies'])}", ""]
    groups = result["groups"]
    out.append("Lines by kind, % (and the tree)")
    out.append(
        f"{'':<8}{'statements':>11}{'lines':>8}{'mapped':>8}{'other':>8}{'open':>8}"
        f"{'in tree':>9}{'open w/ block':>15}"
    )
    for key, g in groups.items():
        out.append(
            f"{key:<8}{g['statements']:>11}{g['lines']:>8}"
            + "".join(f"{_pct(g['kind_shares'][k]):>8}" for k in KINDS)
            + f"{_pct(g['in_tree_share']):>9}{_pct(g['open_with_block_share']):>15}"
        )
    out += ["", "Parent checks in the newest face period, and statements where every parent foots"]
    out.append(
        f"{'':<8}{'checks':>8}{'foot':>8}{'+missing':>10}{'not foot':>10}"
        f"{'statements':>12}{'all foot %':>12}"
    )
    for key, g in groups.items():
        out.append(
            f"{key:<8}{g['checks']:>8}{g['foot']:>8}{g['foot_missing_child']:>10}"
            f"{g['not_foot']:>10}{g['statements_with_checks']:>12}{_pct(g['all_foot_share']):>12}"
        )
    disagreements = result["face_disagreements"]
    out += [
        "",
        "Face disagreements (FY cells whose source concept is off the anchor filing's face while "
        "another concept of the item is on it), per code: "
        f"{sum(disagreements.values())} cells",
    ]
    for code, n in disagreements.items():
        out.append(f"  {code:<40}{n:>6}")
    if not totals_only:
        out += ["", "Face disagreements by company"]
        for ticker, codes in result["face_disagreements_by_company"].items():
            names = ", ".join(f"{c} {n}" for c, n in codes.items()) or "none"
            out.append(f"  {ticker:<8}{names}")
    return "\n".join(out)


# --- main ------------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="projection_report.py", add_help=True)
    parser.add_argument("--fixtures", nargs="+", metavar="TICKER")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--json", type=Path, metavar="OUT")
    args = parser.parse_args(argv)
    if sum(bool(x) for x in (args.fixtures, args.db, args.holdout)) != 1:
        print(__doc__)
        return 2
    try:
        if args.fixtures:
            entries = fixture_companies(args.fixtures)
        else:
            entries = db_companies(args.db or load_settings().data_dir / "holdout.db")
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
    output = report(entries)
    print(render(output, totals_only=args.holdout))
    if args.holdout:  # aggregates only: no company leaves the holdout run
        output = {
            k: v
            for k, v in output.items()
            if k not in ("companies", "face_disagreements_by_company")
        }
    if args.json:
        args.json.write_text(json.dumps(output, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
