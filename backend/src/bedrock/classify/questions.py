"""The open lines of a company and the question for each (docs/erd/face-tree.md "Open lines and
questions"). Pure: no DB, no network."""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.classify.types import Candidate, LineQuestion
from bedrock.mapping.config import SUPPORT_CODES, CanonicalItemDef
from bedrock.statements.projection import (
    STATEMENT_ORDER,
    PlacedLine,
    ProjectedStatement,
    project_all,
)
from bedrock.statements.records import records
from bedrock.statements.structure import Concept, FaceLines

MAX_SIBLINGS = 12


@dataclass(frozen=True)
class AskedLine:
    """A face line with its question: `line` as the newest filing that presents it places it."""

    line: PlacedLine
    question: LineQuestion


@dataclass(frozen=True)
class _Amount:
    start: date | None
    end: date
    value: Decimal


def build(face: FaceLines, items: Sequence[CanonicalItemDef]) -> list[LineQuestion]:
    """The question for every open line, in statement (IS, BS, CF) then presentation order."""
    return [asked.question for asked in open_lines(face, items)]


def open_lines(face: FaceLines, items: Sequence[CanonicalItemDef]) -> list[AskedLine]:
    """Over every parsed filing, the lines nothing classifies that have a non-zero amount in
    their filing, distinct by (statement, taxonomy, concept)."""
    return select(face, items, lambda line: line.kind == "open")


def select(
    face: FaceLines, items: Sequence[CanonicalItemDef], wanted: Callable[[PlacedLine], bool]
) -> list[AskedLine]:
    """The `wanted` lines with a non-zero amount in their filing, distinct by (statement,
    taxonomy, concept), each with its question. The newest filing that presents a line with an
    amount gives its label, form, values and neighbours. Order: statement (IS, BS, CF), then the
    newest filing's lines as presented, then the lines only older filings present."""
    amounts = _amounts(face)
    labels = {i.code: i.label for i in items}
    newest_first = sorted(
        project_all(face, items), key=lambda p: (p.filed_at, p.accession_no), reverse=True
    )
    newest_first.sort(key=lambda p: STATEMENT_ORDER.index(p.statement))  # stable
    found: dict[tuple[str, str, str], AskedLine] = {}
    for projected in newest_first:
        for line in projected.lines:
            key = (projected.statement, line.taxonomy, line.concept)
            own = amounts.get((projected.accession_no, (line.taxonomy, line.concept)), [])
            if key in found or not own or not wanted(line):
                continue
            found[key] = AskedLine(line, _question(projected, line, own, amounts, items, labels))
    return list(found.values())


def candidates(
    items: Sequence[CanonicalItemDef], statement: str, block_code: str | None
) -> tuple[Candidate, ...]:
    """The rows a line of `statement` may be: not residual, not custom, not a support line, with
    no child row, and under `block_code`; the whole statement when there is no block or it holds
    no such row. Canonical file order."""
    parents = {i.code: i.parent for i in items}
    with_children = {i.parent for i in items if i.parent is not None}
    rows = [
        i
        for i in items
        if i.statement == statement
        and not i.residual
        and not i.custom
        and i.code not in SUPPORT_CODES
        and i.code not in with_children
    ]
    in_block = [i for i in rows if block_code is not None and block_code in _ancestors(i, parents)]
    return tuple(Candidate(i.code, i.label) for i in in_block or rows)


def _ancestors(item: CanonicalItemDef, parents: dict[str, str | None]) -> list[str]:
    out: list[str] = []
    parent = item.parent
    while parent is not None and parent not in out:
        out.append(parent)
        parent = parents.get(parent)
    return out


def _amounts(face: FaceLines) -> dict[tuple[str, Concept], list[_Amount]]:
    """The non-zero facts of each filing's concepts."""
    out: dict[tuple[str, Concept], list[_Amount]] = defaultdict(list)
    for r in records(face.facts):
        if r["value"]:
            start = None if pd.isna(r["period_start"]) else r["period_start"]
            out[(r["accession_no"], (r["taxonomy"], r["concept"]))].append(
                _Amount(start, r["period_end"], r["value"])
            )
    return out


def _question(
    projected: ProjectedStatement,
    line: PlacedLine,
    own: Sequence[_Amount],
    amounts: dict[tuple[str, Concept], list[_Amount]],
    items: Sequence[CanonicalItemDef],
    labels: dict[str, str],
) -> LineQuestion:
    # the newest fact, the longest period on that date (as `mapping/gaps.py` reads it)
    latest = max(own, key=lambda a: (a.end, -(a.start or a.end).toordinal()))
    parent = next((ln for ln in projected.lines if (ln.taxonomy, ln.concept) == line.parent), None)
    siblings: tuple[str, ...] = ()
    parent_value = None
    if parent is not None:
        siblings = tuple(
            ln.label for ln in projected.lines if ln.parent == line.parent and ln is not line
        )[:MAX_SIBLINGS]
        parent_value = next(
            (
                a.value
                for a in amounts.get(
                    (projected.accession_no, (parent.taxonomy, parent.concept)), []
                )
                if (a.start, a.end) == (latest.start, latest.end)
            ),
            None,
        )
    return LineQuestion(
        key=f"{projected.statement}|{line.taxonomy}|{line.concept}",
        statement=projected.statement,
        taxonomy=line.taxonomy,
        concept=line.concept,
        label=line.label,
        form=projected.form,
        period_end=latest.end,
        value=latest.value,
        parent_label=None if parent is None else parent.label,
        parent_value=parent_value,
        sibling_labels=siblings,
        block_label=None if line.block_code is None else labels.get(line.block_code),
        candidates=candidates(items, projected.statement, line.block_code),
    )
