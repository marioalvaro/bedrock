"""The projection of a filing's face lines on the canonical rows (M7d S1, docs/erd/face-tree.md
"Projection"). Pure: no DB, no network."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.records import records
from bedrock.statements.structure import Concept, FaceIndex, FaceLines, concept_text

Kind = Literal["mapped", "other", "open"]
STATEMENT_ORDER = ("IS", "BS", "CF")
# A total foots when |sum - value| <= max(FOOT_ABSOLUTE, FOOT_RELATIVE x |value|)
FOOT_ABSOLUTE = Decimal(1)
FOOT_RELATIVE = Decimal("0.000001")


@dataclass(frozen=True)
class FacePeriod:
    start: date | None
    end: date


@dataclass(frozen=True)
class PlacedLine:
    position: int
    taxonomy: str
    concept: str
    label: str
    unit: str | None
    depth: int
    parent: Concept | None
    weight: Decimal | None
    kind: Kind
    codes: tuple[str, ...]
    block_code: str | None
    in_tree: bool
    is_total: bool  # has a calculation child
    values: tuple[Decimal | None, ...]  # aligned with the face periods
    foots: tuple[bool | None, ...]  # aligned with the face periods; None where not checked
    missing_children: tuple[str, ...]  # `taxonomy:Concept` of children with no value in any period


@dataclass(frozen=True)
class ProjectedStatement:
    accession_no: str
    form: str
    filed_at: date
    statement: str
    periods: tuple[FacePeriod, ...]
    lines: tuple[PlacedLine, ...]
    foots: bool | None


def project(
    face: FaceLines, items: Sequence[CanonicalItemDef], accession: str, statement: str
) -> ProjectedStatement | None:
    """One filing's statement placed against the canonical rows; None when the filing has no
    line for the statement."""
    return _Projector(face, items, {accession}).project(accession, statement)


def project_all(face: FaceLines, items: Sequence[CanonicalItemDef]) -> list[ProjectedStatement]:
    """Every statement of every filing in `face`: filings oldest first (filed date, then
    accession), statements IS, BS, CF within a filing."""
    filings = sorted(
        {
            (r["filed_at"], r["accession_no"])
            for r in records(face.lines[["filed_at", "accession_no"]])
        }
    )
    projector = _Projector(face, items, {a for _, a in filings})
    out: list[ProjectedStatement] = []
    for _, accession in filings:
        for statement in STATEMENT_ORDER:
            projected = projector.project(accession, statement)
            if projected is not None:
                out.append(projected)
    return out


@dataclass(frozen=True)
class _Fact:
    start: date | None
    end: date
    unit: str
    value: Decimal


@dataclass(frozen=True)
class _Row:
    position: int
    concept: Concept
    label: str
    parent: Concept | None
    weight: Decimal | None


class _Projector:
    """The indexes `project` needs, built once for the filings of `accessions`."""

    def __init__(
        self, face: FaceLines, items: Sequence[CanonicalItemDef], accessions: set[str]
    ) -> None:
        self.items = items
        self.index = FaceIndex(face, items)
        self.rows: dict[tuple[str, str], list[_Row]] = defaultdict(list)
        self.filings: dict[str, tuple[str, date]] = {}
        for r in records(face.lines):
            if r["accession_no"] not in accessions:
                continue
            parent = (
                None
                if _missing(r["calc_parent_concept"])
                else (r["calc_parent_taxonomy"], r["calc_parent_concept"])
            )
            self.rows[(r["accession_no"], r["statement"])].append(
                _Row(
                    int(r["position"]),
                    (r["taxonomy"], r["concept"]),
                    str(r["label"]),
                    parent,
                    None if _missing(r["calc_weight"]) else Decimal(r["calc_weight"]),
                )
            )
            self.filings[r["accession_no"]] = (str(r["form"]), r["filed_at"])
        wanted = {row.concept for group in self.rows.values() for row in group}
        self.facts: dict[tuple[str, Concept], list[_Fact]] = defaultdict(list)
        for r in records(face.facts):
            concept = (r["taxonomy"], r["concept"])
            if r["accession_no"] in accessions and concept in wanted:
                start = None if _missing(r["period_start"]) else r["period_start"]
                self.facts[(r["accession_no"], concept)].append(
                    _Fact(start, r["period_end"], str(r["unit"]), r["value"])
                )
        self._kinds: dict[Concept, tuple[Kind, tuple[str, ...]]] = {}

    def kind(self, concept: Concept) -> tuple[Kind, tuple[str, ...]]:
        if concept not in self._kinds:
            self._kinds[concept] = self._kind(concept)
        return self._kinds[concept]

    def _kind(self, concept: Concept) -> tuple[Kind, tuple[str, ...]]:
        index = self.index
        mapped = index.mapped.get(concept, set())
        codes = tuple(
            i.code
            for i in self.items
            if i.code in mapped or concept in index.face_members.get(i.code, ())
        )
        if codes:
            return "mapped", codes
        if concept in index.known:
            return "other", tuple(index.verdicts.get(concept, ()))
        return "open", ()

    def project(self, accession: str, statement: str) -> ProjectedStatement | None:
        rows = sorted(self.rows.get((accession, statement), []), key=lambda r: r.position)
        if not rows:
            return None
        form, filed_at = self.filings[accession]
        facts = {row.concept: self.facts.get((accession, row.concept), []) for row in rows}
        periods = _face_periods(facts.values())
        by_concept: dict[Concept, _Row] = {}
        for row in rows:
            by_concept.setdefault(row.concept, row)
        children: dict[Concept, list[_Row]] = defaultdict(list)
        for row in rows:
            if row.parent is not None:
                children[row.parent].append(row)
        values = {row.concept: _values(facts[row.concept], periods) for row in rows}
        placed = [
            self._place(row, by_concept, children.get(row.concept, []), facts, values, periods)
            for row in rows
        ]
        checks = [f for line in placed for f in line.foots if f is not None]
        return ProjectedStatement(
            accession,
            form,
            filed_at,
            statement,
            periods,
            tuple(placed),
            all(checks) if checks else None,
        )

    def _place(
        self,
        row: _Row,
        by_concept: Mapping[Concept, _Row],
        kids: Sequence[_Row],
        facts: Mapping[Concept, Sequence[_Fact]],
        values: Mapping[Concept, tuple[Decimal | None, ...]],
        periods: Sequence[FacePeriod],
    ) -> PlacedLine:
        kind, codes = self.kind(row.concept)
        ancestors = _ancestors(row, by_concept)
        block = next((a for a in ancestors if self.kind(a)[0] == "mapped"), None)
        own = values[row.concept]
        foots = tuple(
            None if not kids or value is None else _foots(value, kids, values, n)
            for n, value in enumerate(own)
        )
        missing = tuple(
            concept_text(kid.concept) for kid in kids if all(v is None for v in values[kid.concept])
        )
        return PlacedLine(
            position=row.position,
            taxonomy=row.concept[0],
            concept=row.concept[1],
            label=row.label,
            unit=_unit(facts[row.concept]),
            depth=len(ancestors),
            parent=row.parent,
            weight=row.weight,
            kind=kind,
            codes=codes,
            block_code=None if block is None else self.kind(block)[1][0],
            in_tree=row.parent is not None or bool(kids),
            is_total=bool(kids),
            values=own,
            foots=foots,
            missing_children=missing,
        )


def _missing(value: Any) -> bool:
    return value is None or bool(pd.isna(value))


def _ancestors(row: _Row, by_concept: Mapping[Concept, _Row]) -> list[Concept]:
    """The calculation ancestors, nearest first. A parent that is not a line of the statement is
    one ancestor, and the chain stops there (its own parent is not known)."""
    out: list[Concept] = []
    parent = row.parent
    while parent is not None and parent not in out and parent != row.concept:
        out.append(parent)
        node = by_concept.get(parent)
        parent = None if node is None else node.parent
    return out


def _face_periods(per_line: Iterable[Sequence[_Fact]]) -> tuple[FacePeriod, ...]:
    """The periods more than half of the lines with a fact have a fact for: newest end first,
    then longest first."""
    having = [{(f.start, f.end) for f in facts} for facts in per_line if facts]
    counts = Counter(period for periods in having for period in periods)
    kept = [p for p, n in counts.items() if 2 * n > len(having)]
    kept.sort(key=lambda p: (-p[1].toordinal(), (p[0] or p[1]).toordinal()))
    return tuple(FacePeriod(start, end) for start, end in kept)


def _unit(facts: Sequence[_Fact]) -> str | None:
    """The unit of the line's facts in the filing: the most frequent, then the first by name."""
    counts = Counter(f.unit for f in facts)
    return min(counts, key=lambda u: (-counts[u], u)) if counts else None


def _values(facts: Sequence[_Fact], periods: Sequence[FacePeriod]) -> tuple[Decimal | None, ...]:
    """The line's fact for exactly each period, in its own unit first."""
    unit = _unit(facts)
    ordered = sorted(facts, key=lambda f: f.unit != unit)
    out: list[Decimal | None] = []
    for period in periods:
        found = next(
            (f.value for f in ordered if f.start == period.start and f.end == period.end), None
        )
        out.append(found)
    return tuple(out)


def _foots(
    value: Decimal,
    kids: Sequence[_Row],
    values: Mapping[Concept, tuple[Decimal | None, ...]],
    n: int,
) -> bool:
    total = sum(
        (
            (kid.weight if kid.weight is not None else Decimal(1)) * (values[kid.concept][n] or 0)
            for kid in kids
        ),
        Decimal(0),
    )
    return abs(total - value) <= max(FOOT_ABSOLUTE, FOOT_RELATIVE * abs(value))
