#!/usr/bin/env python3
r"""Structural integrity check for Bedrock docs. Exit 1 on any problem.

Checks:
  1. Every relative markdown link and #anchor resolves.
  2. Every FR-* requirement is defined exactly once (as a table row in docs/prd/*.md),
     and every FR-* referenced anywhere is defined.
  3. Every ERD table (a `| \`name\` |` row in docs/erd/*.md) is defined exactly once
     and listed in the docs/ERD.md table index.
  4. Every split file names its origin ("Split of [PRD.md]" / "Split of [ERD.md]").
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", "node_modules", ".venv", "dist", "build"}
FR = re.compile(r"\bFR-[A-Z]+-\d{2}\b")


def md_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.md") if not SKIP & set(p.relative_to(ROOT).parts)]


def slug(heading: str) -> str:
    h = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return h.replace(" ", "-")


def check_links(files: list[Path]) -> list[str]:
    errors = []
    for p in files:
        text = re.sub(r"^```.*?^```", "", p.read_text(), flags=re.M | re.S)  # skip code blocks
        for m in re.finditer(r"\]\(([^)#\s]*)(#[^)\s]+)?\)", text):
            target, anchor = m.group(1), m.group(2)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            tgt = (p.parent / target).resolve() if target else p
            if not tgt.exists():
                errors.append(f"{p.relative_to(ROOT)}: broken link {target}")
            elif anchor and tgt.is_file():
                heads = {slug(h) for h in re.findall(r"^#+ (.*)$", tgt.read_text(), re.M)}
                if anchor[1:] not in heads:
                    errors.append(f"{p.relative_to(ROOT)}: missing anchor {target}{anchor}")
    return errors


def check_requirements(files: list[Path]) -> list[str]:
    errors = []
    defined: dict[str, list[str]] = {}
    for p in sorted((ROOT / "docs/prd").glob("*.md")):
        for rid in re.findall(r"^\| (FR-[A-Z]+-\d{2}) \|", p.read_text(), re.M):
            defined.setdefault(rid, []).append(p.name)
    for rid, where in defined.items():
        if len(where) > 1:
            errors.append(f"{rid} defined {len(where)}x: {where}")
    for p in files:
        for rid in set(FR.findall(p.read_text())) - defined.keys():
            errors.append(f"{p.relative_to(ROOT)}: references undefined {rid}")
    return errors


def check_tables() -> list[str]:
    errors = []
    defined: dict[str, list[str]] = {}
    for p in sorted((ROOT / "docs/erd").glob("*.md")):
        for row in re.findall(r"^\| (`[a-z_]+`(?: / `[a-z_]+`)?) \|", p.read_text(), re.M):
            for name in re.findall(r"`([a-z_]+)`", row):
                defined.setdefault(name, []).append(p.name)
    index = (ROOT / "docs/ERD.md").read_text()
    for name, where in defined.items():
        if len(where) > 1:
            errors.append(f"table `{name}` defined {len(where)}x: {where}")
        if f"`{name}`" not in index:
            errors.append(f"table `{name}` ({where[0]}) missing from ERD.md index")
    return errors


def check_split_headers() -> list[str]:
    errors = []
    for kind in ("prd", "erd"):
        for p in sorted((ROOT / "docs" / kind).glob("*.md")):
            if f"Split of [{kind.upper()}.md]" not in p.read_text():
                errors.append(f"docs/{kind}/{p.name}: missing 'Split of [{kind.upper()}.md]' header")
    return errors


def main() -> int:
    files = md_files()
    errors = check_links(files) + check_requirements(files) + check_tables() + check_split_headers()
    for e in errors:
        print(f"FAIL {e}")
    print(f"{'FAIL' if errors else 'OK'}: {len(files)} markdown files, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
