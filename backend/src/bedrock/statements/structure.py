"""Structure rules from the face of a filing's statements (M7b S7, docs/erd/data-coverage.md
"Structure rules"). Pure: no DB, no network.

With the lines a filing presents on each statement and their calculation parents, an empty cell
can be filled when the face proves its value: R8 sums the face lines that are, by definition,
parts of the item; R9 infers 0 when a 10-K's face has no line for it. Both need the item's block
(the lines under its parent's line) to hold no line nobody has classified, and both only fill
empty cells (`cells.py::_fill`). The anchor filing of a period is the source of the statement's
anchor cell, as for the NCI zero rule (R1b)."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import (
    SUPPORT_CODES,
    CanonicalItemDef,
    covered_codes,
    signed_members,
)
from bedrock.mapping.vintage import BALANCE_DATE_TOLERANCE
from bedrock.statements.cell_types import (
    EMPTY,
    IMPORT_PREFIX,
    Cell,
    CellKey,
    Derivation,
    DerivationInput,
    FactRef,
)
from bedrock.statements.periods import START_TOLERANCE, Period
from bedrock.statements.records import records

Concept = tuple[str, str]  # (taxonomy, concept)

# The frame of `repositories/filing_lines.py::lines_for`
LINE_COLUMNS = [
    "accession_no",
    "form",
    "filed_at",
    "statement",
    "position",
    "taxonomy",
    "concept",
    "label",
    "calc_parent_taxonomy",
    "calc_parent_concept",
    "calc_weight",
]
# The line whose source names a statement's filing for a period, in order of preference
ANCHOR_CODES: dict[str, tuple[str, ...]] = {
    "BS": ("total_assets",),
    "IS": ("net_income", "net_income_common"),
    "CF": ("cfo",),
}
STATEMENT_NAMES = {"IS": "income statement", "BS": "balance sheet", "CF": "cash flow statement"}
# A memo line R9 may infer 0 although it has no parent (an impairment is on the face when taken)
ZERO_MEMOS = frozenset({"goodwill_impairment"})
DIVIDENDS_PER_SHARE = "dividends_per_share"
DIVIDENDS_PAID = "dividends_paid"


@dataclass(frozen=True)
class FaceLines:
    """What the structure rules read for one company (`Rules.filing_lines`).

    `lines`: the face lines of its parsed filings (`LINE_COLUMNS`). `facts`: the facts of those
    lines' concepts, every vintage, with their accession (the columns of a fact frame); a line's
    amount in a period is its fact from the same filing. `mappings`: the company's mapping frame
    (`canonical_code`, `taxonomy`, `concept`, `is_override`, `covers`). `verdicts`: the triage
    verdicts, (taxonomy, concept) -> the canonical codes each names. `other_lines`: the extension
    lines the override file assigns to a residual. `classified` (M7d S4): the company's effective
    classifications, concept -> the codes it names (docs/erd/face-tree.md "Use in statements")."""

    lines: pd.DataFrame
    facts: pd.DataFrame
    mappings: pd.DataFrame
    verdicts: Mapping[Concept, tuple[str, ...]] = field(default_factory=dict)
    other_lines: frozenset[Concept] = frozenset()
    classified: Mapping[Concept, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class _Line:
    concept: Concept
    parent: Concept | None


@dataclass(frozen=True)
class _Amount:
    start: date | None
    end: date
    value: Decimal


def face_concepts(lines: pd.DataFrame, items: Sequence[CanonicalItemDef]) -> set[Concept]:
    """The concepts whose facts `FaceLines.facts` must hold: every line's, and every default
    member and face member of an item (R9 reads them off the face too)."""
    concepts = set(zip(lines["taxonomy"], lines["concept"], strict=True))
    for item in items:
        concepts |= {(t, c) for entry in item.concepts for _, t, c in signed_members(entry)}
        concepts |= {_concept(m) for m in item.face_members}
    return concepts


def concept_text(concept: Concept) -> str:
    return f"{concept[0]}:{concept[1]}"


class FaceIndex:
    """`FaceLines` indexed for the rules, built once per solve."""

    def __init__(self, face: FaceLines, items: Sequence[CanonicalItemDef]) -> None:
        self.lines: dict[tuple[str, str], list[_Line]] = defaultdict(list)
        self.forms: dict[str, str] = {}
        for r in records(face.lines.sort_values(["accession_no", "statement", "position"])):
            parent = (
                None
                if r["calc_parent_concept"] is None or pd.isna(r["calc_parent_concept"])
                else (r["calc_parent_taxonomy"], r["calc_parent_concept"])
            )
            self.lines[(r["accession_no"], r["statement"])].append(
                _Line((r["taxonomy"], r["concept"]), parent)
            )
            self.forms[r["accession_no"]] = r["form"]
        self.parents = {i.code: i.parent for i in items}
        # code -> the members of its default entries (also those a company excludes)
        self.defaults_of: dict[str, set[Concept]] = {
            i.code: {(t, c) for entry in i.concepts for _, t, c in signed_members(entry)}
            for i in items
        }
        self.mapped_of: dict[str, set[Concept]] = defaultdict(set)  # filled with `mapped`
        self.face_members: dict[str, set[Concept]] = {
            i.code: {_concept(m) for m in i.face_members} for i in items
        }
        wanted = {line.concept for group in self.lines.values() for line in group}
        wanted |= {c for group in self.defaults_of.values() for c in group}
        wanted |= {c for group in self.face_members.values() for c in group}
        self.amounts: dict[tuple[str, Concept], list[_Amount]] = defaultdict(list)
        for r in records(face.facts):
            concept = (r["taxonomy"], r["concept"])
            if concept in wanted and r["accession_no"] in self.forms:
                start = None if pd.isna(r["period_start"]) else r["period_start"]
                self.amounts[(r["accession_no"], concept)].append(
                    _Amount(start, r["period_end"], r["value"])
                )
        self.mapped: dict[Concept, set[str]] = defaultdict(set)  # concept -> codes
        self.overrides: dict[str, set[Concept]] = defaultdict(set)  # code -> concepts
        self.covers: dict[Concept, set[str]] = defaultdict(set)  # concept -> covered codes
        # a combined line that covers no row: concept -> its carrier codes
        self.open_carriers: dict[Concept, set[str]] = defaultdict(set)
        for r in records(face.mappings):
            concept = (r["taxonomy"], r["concept"])
            self.mapped[concept].add(r["canonical_code"])
            self.mapped_of[r["canonical_code"]].add(concept)
            if r["is_override"]:
                self.overrides[r["canonical_code"]].add(concept)
            covers = r.get("covers")
            if isinstance(covers, str):
                self.covers[concept] |= set(covered_codes(covers) or ())
                if not covers:
                    self.open_carriers[concept].add(r["canonical_code"])
        defaults = {c for group in self.defaults_of.values() for c in group}
        self.known: set[Concept] = (
            set(self.mapped)
            | defaults
            | {m for members in self.face_members.values() for m in members}
            | set(face.verdicts)
            | set(face.other_lines)
        )
        self.verdicts: dict[Concept, tuple[str, ...]] = dict(face.verdicts)
        # code -> the concepts that are its face members only through a classification
        self.classified_members: dict[str, set[Concept]] = defaultdict(set)
        self._classify(face.classified)
        self._blocks: dict[tuple[str, str, str | None], list[_Line]] = {}
        self._own: dict[str, set[Concept]] = {}

    def _classify(self, classified: Mapping[Concept, tuple[str, ...]]) -> None:
        """M7d S4: a classification applies only to a line nothing else classifies (a stored
        answer goes stale once the line is mapped or given a verdict; the mapping wins). Such a
        concept becomes known; with one code it is a face member of that item, with several a
        verdict naming them. A code that is not an item is ignored."""
        for concept, named in classified.items():
            if concept in self.known:
                continue
            codes = tuple(c for c in dict.fromkeys(named) if c in self.parents)
            self.known.add(concept)
            if len(codes) == 1:
                self.face_members[codes[0]].add(concept)
                self.classified_members[codes[0]].add(concept)
            elif codes:
                self.verdicts[concept] = codes

    def statement_lines(self, accession: str, statement: str) -> list[_Line]:
        return self.lines.get((accession, statement), [])

    def block(self, accession: str, statement: str, parent_code: str | None) -> list[_Line]:
        """The lines whose calculation ancestors include the line mapped to `parent_code`; the
        whole statement when there is no parent, no such line or it has no calculation child."""
        key = (accession, statement, parent_code)
        if key not in self._blocks:
            self._blocks[key] = self._block(accession, statement, parent_code)
        return self._blocks[key]

    def _block(self, accession: str, statement: str, parent_code: str | None) -> list[_Line]:
        lines = self.statement_lines(accession, statement)
        if parent_code is None:
            return lines
        children: dict[Concept, list[_Line]] = defaultdict(list)
        for line in lines:
            if line.parent is not None:
                children[line.parent].append(line)
        pending = [ln.concept for ln in lines if parent_code in self.mapped.get(ln.concept, ())]
        found: list[_Line] = []
        seen: set[Concept] = set(pending)
        while pending:
            for child in children.get(pending.pop(), []):
                if child.concept not in seen:
                    seen.add(child.concept)
                    found.append(child)
                    pending.append(child.concept)
        return found or lines

    def value(self, accession: str, concept: Concept, period: Period, kind: str) -> Decimal | None:
        """The line's fact of `accession` for the period: the instant at its end (the nearest
        within a week), or the duration that ends on it and starts within a week of its start."""
        amounts = self.amounts.get((accession, concept), [])
        if kind == "instant":
            near = [
                a
                for a in amounts
                if a.start is None and abs(a.end - period.end) <= BALANCE_DATE_TOLERANCE
            ]
            best = min(near, key=lambda a: abs(a.end - period.end), default=None)
            return None if best is None else best.value
        near = [
            a
            for a in amounts
            if a.start is not None
            and a.end == period.end
            and abs(a.start - period.start) <= START_TOLERANCE
        ]
        found = min(near, key=lambda a: abs((a.start or period.start) - period.start), default=None)
        return None if found is None else found.value

    def has_amount(self, accession: str, concept: Concept, period: Period) -> bool:
        """The filing gives the line a non-zero value for a period ending on the period's end
        (an instant, a quarter or a year to date): a line with none hides nothing."""
        return any(
            a.value != 0 and abs(a.end - period.end) <= timedelta(days=0 if a.start else 7)
            for a in self.amounts.get((accession, concept), [])
        )

    def unclassified(
        self, accession: str, statement: str, item: CanonicalItemDef, period: Period
    ) -> tuple[str, ...]:
        """The lines of the item's block that nobody classified and that hold an amount."""
        return tuple(
            concept_text(line.concept)
            for line in self.block(accession, statement, item.parent)
            if line.concept not in self.known and self.has_amount(accession, line.concept, period)
        )

    def names(self, concept: Concept, item: CanonicalItemDef) -> bool:
        """The line is, or may hold, the item: mapped to it, a face member, a combined line that
        covers it (or covers no row and sits beside it, under the same parent), or a triage
        verdict that names it."""
        code = item.code
        return (
            code in self.mapped.get(concept, ())
            or concept in self.face_members.get(code, ())
            or code in self.covers.get(concept, ())
            or code in self.verdicts.get(concept, ())
            or any(self.parents.get(c) == item.parent for c in self.open_carriers.get(concept, ()))
        )

    def tags_item(self, accession: str, item: CanonicalItemDef, period: Period) -> bool:
        """The filing gives one of the item's own concepts (a default, mapped or face member) a
        non-zero value for the period, on the face or off it."""
        return any(self.has_amount(accession, c, period) for c in self.own_concepts(item.code))

    def excludes_default(self, code: str) -> bool:
        """The company switches off a default of the item (its tag is a different measure), so
        the face cannot prove the line is 0. A company without mappings excludes nothing."""
        if not self.mapped:
            return False
        return bool(self.defaults_of.get(code, set()) - self.mapped_of.get(code, set()))

    def own_concepts(self, code: str) -> set[Concept]:
        if code not in self._own:
            self._own[code] = (
                self.defaults_of.get(code, set())
                | self.face_members.get(code, set())
                | self.mapped_of.get(code, set())
            )
        return self._own[code]


def _concept(entry: str) -> Concept:
    taxonomy, _, concept = entry.partition(":")
    return (taxonomy, concept)


def anchor_filing(cells: Mapping[CellKey, Cell], statement: str, period: Period) -> FactRef | None:
    """The filing that carries the statement for the period: the source of its anchor cell (no
    source, or an imported one, gives none)."""
    for code in ANCHOR_CODES[statement]:
        source = cells.get((code, period.key), EMPTY).source
        if source is not None:
            return None if source.accession_no.startswith(IMPORT_PREFIX) else source
    return None


def structure_cells(
    cells: Mapping[CellKey, Cell],
    items: Sequence[CanonicalItemDef],
    periods: Sequence[Period],
    face: FaceIndex,
) -> list[tuple[CellKey, Cell]]:
    """One sweep of R8, R9 and the dividends-per-share zero over every empty cell (FY and Q1-Q3;
    Q4 follows from the Q4 close), all read against the same `cells`."""
    parents = {i.parent for i in items if i.parent is not None}
    out: list[tuple[CellKey, Cell]] = []
    for period in periods:
        if period.fiscal_period == "Q4":
            continue
        anchors = {s: anchor_filing(cells, s, period) for s in ANCHOR_CODES}
        for item in items:
            key = (item.code, period.key)
            cell_now = cells.get(key)
            if cell_now is None or cell_now.value is not None or cell_now.included_in is not None:
                continue
            if item.code == DIVIDENDS_PER_SHARE:
                paid = cells.get((DIVIDENDS_PAID, period.key), EMPTY)
                if paid.value == 0:
                    out.append((key, _zero("dividends paid is 0 in the period")))
                continue
            anchor = anchors.get(item.statement)
            if anchor is None or not face.statement_lines(anchor.accession_no, item.statement):
                continue
            cell = face_sum(item, period, anchor, face)
            if cell is None and _zero_eligible(item, item.code in parents):
                cell = face_zero(item, period, anchor, face, cells)
            if cell is not None:
                out.append((key, cell))
    return out


def face_sum(
    item: CanonicalItemDef, period: Period, anchor: FactRef, face: FaceIndex
) -> Cell | None:
    """R8: the sum of the anchor filing's face lines that are face members of the item or mapped
    to it by an override, less any whose calculation ancestor is among them, when each has a fact
    of that filing for the period and the block holds no unclassified line."""
    accession, statement = anchor.accession_no, item.statement
    wanted = face.face_members.get(item.code, set()) | face.overrides.get(item.code, set())
    lines = [ln for ln in face.statement_lines(accession, statement) if ln.concept in wanted]
    if not lines:
        return None
    by_concept = {ln.concept: ln for ln in face.statement_lines(accession, statement)}
    members = [
        ln for ln in lines if not _has_ancestor_in(ln, {m.concept for m in lines}, by_concept)
    ]
    if face.unclassified(accession, statement, item, period):
        return None
    values = [face.value(accession, ln.concept, period, item.kind) for ln in members]
    if any(v is None for v in values):
        return None
    parts = [(ln.concept, v) for ln, v in zip(members, values, strict=True) if v is not None]
    total = item.sign * sum((v for _, v in parts), Decimal(0))
    formula = f"face lines of {anchor.form} {accession}: " + " + ".join(
        concept_text(c) for c, _ in parts
    )
    inputs = tuple(DerivationInput(concept_text(c), period.fiscal_period, v) for c, v in parts)
    through = face.classified_members.get(item.code, set())
    marks = tuple(concept_text(c) for c, _ in parts if c in through)
    return Cell(
        total, "derived", derivation=Derivation(formula, inputs), classified_by=marks or None
    )


def _has_ancestor_in(
    line: _Line, concepts: set[Concept], by_concept: Mapping[Concept, _Line]
) -> bool:
    seen: set[Concept] = set()
    parent = line.parent
    while parent is not None and parent not in seen:
        if parent in concepts:
            return True
        seen.add(parent)
        node = by_concept.get(parent)
        parent = None if node is None else node.parent
    return False


def _zero_eligible(item: CanonicalItemDef, has_children: bool) -> bool:
    """A reported leaf line in USD under a parent, or a memo of `ZERO_MEMOS`, not opted out."""
    if not item.zero_when_absent:
        return False
    if item.code in ZERO_MEMOS:
        return True
    return (
        item.parent is not None
        and not has_children
        and item.derive is None
        and not item.residual
        and not item.custom
        and item.code not in SUPPORT_CODES
        and item.unit == "USD"
    )


def face_zero(
    item: CanonicalItemDef,
    period: Period,
    anchor: FactRef,
    face: FaceIndex,
    cells: Mapping[CellKey, Cell],
) -> Cell | None:
    """R9: 0 when the anchor filing's statement has no line naming the item and its block holds
    no unclassified line. A year needs a 10-K; a quarter a 10-Q and a year (a flow) or the year
    ends around it that have a value (an instant) at 0."""
    accession, statement = anchor.accession_no, item.statement
    if period.fiscal_period == "FY":
        if not anchor.form.startswith("10-K"):
            return None
    elif not anchor.form.startswith("10-Q") or not _years_zero(item, period, cells):
        return None
    if any(face.names(ln.concept, item) for ln in face.statement_lines(accession, statement)):
        return None
    if face.tags_item(accession, item, period) or face.excludes_default(item.code):
        return None
    if face.unclassified(accession, statement, item, period):
        return None
    return _zero(
        f"no {item.label} line on the {STATEMENT_NAMES[statement]} of {anchor.form} {accession}"
    )


def _years_zero(item: CanonicalItemDef, period: Period, cells: Mapping[CellKey, Cell]) -> bool:
    years = (
        [period.fiscal_year]
        if item.kind != "instant"
        else [period.fiscal_year - 1, period.fiscal_year]
    )
    values = [
        cell.value
        for year in years
        if (cell := cells.get((item.code, f"FY{year}"), EMPTY)).value is not None
    ]
    if item.kind != "instant" and len(values) != 1:
        return False
    return bool(values) and all(v == 0 for v in values)


def _zero(formula: str) -> Cell:
    return Cell(Decimal(0), "zero_inferred", derivation=Derivation(formula, ()))


def unclassified_marks(
    cells: Mapping[CellKey, Cell],
    items: Sequence[CanonicalItemDef],
    periods: Iterable[Period],
    face: FaceIndex,
) -> list[tuple[CellKey, tuple[str, ...]]]:
    """Every empty cell of a reported or computed line (not a residual or a support line) whose
    block, in the period's anchor filing, holds unclassified lines: those lines. A Q4 cell takes
    the marks of its year."""
    out: list[tuple[CellKey, tuple[str, ...]]] = []
    by_year: dict[CellKey, tuple[str, ...]] = {}
    ordered = sorted(periods, key=lambda p: p.fiscal_period == "Q4")
    for period in ordered:
        anchors = {s: anchor_filing(cells, s, period) for s in ANCHOR_CODES}
        for item in items:
            key = (item.code, period.key)
            cell = cells.get(key, EMPTY)
            if item.residual or item.code in SUPPORT_CODES or key not in cells:
                continue
            if cell.value is not None or cell.included_in is not None:
                continue
            if period.fiscal_period == "Q4":
                marks = by_year.get((item.code, f"FY{period.fiscal_year}"), ())
            else:
                anchor = anchors.get(item.statement)
                marks = (
                    ()
                    if anchor is None
                    else face.unclassified(anchor.accession_no, item.statement, item, period)
                )
            if marks:
                out.append((key, marks))
                by_year[key] = marks
    return out
