"""The counting behind `scripts/projection_report.py` (M7d S1, docs/erd/face-tree.md "Report").
Pure: no DB, no network."""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.cell_types import Cell, CellKey
from bedrock.statements.periods import Period
from bedrock.statements.projection import ProjectedStatement
from bedrock.statements.structure import (
    ANCHOR_CODES,
    Concept,
    FaceIndex,
    FaceLines,
    anchor_filing,
)

FORM_GROUPS = ("10-K", "10-Q")


@dataclass
class StatementStats:
    """One (form group, statement): its filings' lines and their parent checks."""

    statements: int = 0
    lines: int = 0
    kinds: Counter[str] = field(default_factory=Counter)
    in_tree: int = 0
    open_lines: int = 0
    open_with_block: int = 0
    # parent checks in each statement's newest face period
    foot: int = 0
    foot_missing_child: int = 0
    not_foot: int = 0
    with_checks: int = 0  # statements with at least one check in any face period
    all_foot: int = 0  # of those, the ones where every check foots


def form_group(form: str) -> str | None:
    """10-K or 10-Q, an amendment with its form; None for any other form."""
    return next((g for g in FORM_GROUPS if form.startswith(g)), None)


def tally(projected: Iterable[ProjectedStatement]) -> dict[tuple[str, str], StatementStats]:
    """The counts by (form group, statement), in the order they are first met."""
    out: dict[tuple[str, str], StatementStats] = {}
    for statement in projected:
        group = form_group(statement.form)
        if group is None:
            continue
        stats = out.setdefault((group, statement.statement), StatementStats())
        stats.statements += 1
        stats.lines += len(statement.lines)
        for line in statement.lines:
            stats.kinds[line.kind] += 1
            stats.in_tree += line.in_tree
            if line.kind == "open":
                stats.open_lines += 1
                stats.open_with_block += line.block_code is not None
        _newest_checks(statement, stats)
        if statement.foots is not None:
            stats.with_checks += 1
            stats.all_foot += statement.foots
    return out


def _newest_checks(statement: ProjectedStatement, stats: StatementStats) -> None:
    if not statement.periods:
        return
    newest: dict[Concept, Decimal | None] = {
        (ln.taxonomy, ln.concept): ln.values[0] for ln in statement.lines
    }
    for line in statement.lines:
        foots = line.foots[0]
        if foots is None:
            continue
        if not foots:
            stats.not_foot += 1
            continue
        concept = (line.taxonomy, line.concept)
        kids = [(ln.taxonomy, ln.concept) for ln in statement.lines if ln.parent == concept]
        if any(newest[kid] is None for kid in kids):
            stats.foot_missing_child += 1
        else:
            stats.foot += 1


def face_disagreements(
    cells: Mapping[CellKey, Cell],
    periods: Sequence[Period],
    face: FaceLines,
    items: Sequence[CanonicalItemDef],
) -> Counter[str]:
    """Per canonical code, the FY cells with a reported value whose anchor filing is parsed,
    whose source concept is not a face line of that filing's statement while another concept
    among the item's defaults or the company's mappings is (idea D11's "choose the concept the
    face shows", measured, not built)."""
    index = FaceIndex(face, items)
    found: Counter[str] = Counter()
    for period in periods:
        if period.fiscal_period != "FY":
            continue
        anchors = {s: anchor_filing(cells, s, period) for s in ANCHOR_CODES}
        for item in items:
            cell = cells.get((item.code, period.key))
            anchor = anchors.get(item.statement)
            if cell is None or cell.provenance != "reported" or cell.source is None:
                continue
            if anchor is None:
                continue
            on_face = {
                ln.concept for ln in index.statement_lines(anchor.accession_no, item.statement)
            }
            source = (cell.source.taxonomy, cell.source.concept)
            if not on_face or source in on_face:
                continue
            if (
                index.defaults_of.get(item.code, set()) | index.mapped_of.get(item.code, set())
            ) & on_face:
                found[item.code] += 1
    return found
