"""Pure parser for one filing's XBRL files: no DB, no network (docs/erd/data-coverage.md "Parser").

`parse_filing` reads the instance's non-dimensional numeric facts and the lines on the face of the
three statements (presentation order, label, calculation parent and weight). Linkbases and role
types are read from every non-instance file given, so linkbases inside the schema parse the same
way as separate `_pre`/`_cal`/`_lab` files. Namespaces are matched by URI, never by prefix."""

import io
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from bedrock.ingest.parse import FactRecord

# Raise it when the parse result changes; `backfill-filings --reparse` then rebuilds the lines.
XBRL_PARSER_VERSION = 1

_XBRLI = "{http://www.xbrl.org/2003/instance}"
_LINK = "{http://www.xbrl.org/2003/linkbase}"
_XLINK = "{http://www.w3.org/1999/xlink}"
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
_XSD = "{http://www.w3.org/2001/XMLSchema}"
_STANDARD_LABEL = "http://www.xbrl.org/2003/role/label"
_STANDARD_HOSTS = {"fasb.org", "xbrl.fasb.org", "xbrl.sec.gov", "xbrl.us"}
_STANDARD_TAXONOMIES = {"us-gaap", "dei", "srt", "ifrs-full"}
_STATEMENT = re.compile(r"^\s*\d+\s*-\s*Statement\s*-\s*(.+)$", re.IGNORECASE)
_NOT_A_LINE = ("Abstract", "Axis", "Domain", "Member", "Table", "LineItems")
_CONCEPT_ENTRY = re.compile(r"([A-Za-z][\w-]*):([A-Za-z_]\w*)")

Concept = tuple[str, str]  # (taxonomy, concept name)


class XbrlError(ValueError):
    """The files are not a readable XBRL filing (no instance, malformed XML)."""


@dataclass(frozen=True)
class StatementAnchors:
    """The concepts that identify each statement's role. Passed in by the caller (built from the
    canonical items), so the parser imports nothing from `mapping/`."""

    liabilities_and_equity: frozenset[Concept]
    cfo: frozenset[Concept]
    net_income: frozenset[Concept]
    revenue_or_eps: frozenset[Concept]

    @classmethod
    def from_concepts(cls, concepts_by_code: Mapping[str, Iterable[str]]) -> "StatementAnchors":
        """From canonical codes to their concept entries (`taxonomy:Concept`, possibly a group
        such as `us-gaap:A+us-gaap:B`): every concept named in an entry of the code counts."""

        def of(*codes: str) -> frozenset[Concept]:
            return frozenset(
                (taxonomy, name)
                for code in codes
                for entry in concepts_by_code.get(code, ())
                for taxonomy, name in _CONCEPT_ENTRY.findall(entry)
            )

        return cls(
            liabilities_and_equity=of("total_liabilities_and_equity"),
            cfo=of("cfo"),
            net_income=of("net_income", "net_income_common"),
            revenue_or_eps=of("revenue", "eps_basic", "eps_diluted"),
        )


@dataclass(frozen=True)
class FilingLine:
    """One line on the face of one statement: `position` counts from 1 in presentation order."""

    statement: str  # IS | BS | CF
    position: int
    taxonomy: str
    concept: str
    label: str
    calc_parent_taxonomy: str | None
    calc_parent_concept: str | None
    calc_weight: Decimal | None


@dataclass(frozen=True)
class ParsedFiling:
    facts: list[FactRecord]
    lines: list[FilingLine]


def parse_filing(
    files: Mapping[str, bytes],
    anchors: StatementAnchors,
    *,
    accession_no: str,
    fiscal_year: int | None = None,
    fiscal_period: str | None = None,
) -> ParsedFiling:
    """Facts and statement lines of one filing. `fiscal_year`/`fiscal_period` are the filing's
    (as `raw_fact` stores them); facts carry no frame. Raises XbrlError."""
    instance: tuple[ET.Element, dict[str, str]] | None = None
    others: list[ET.Element] = []
    for name, body in files.items():
        root, prefixes = _read(name, body)
        if root.tag == f"{_XBRLI}xbrl":
            if instance is None:
                instance = (root, prefixes)
        else:
            others.append(root)
    if instance is None:
        raise XbrlError("no XBRL instance among the files")
    root, prefixes = instance
    try:
        facts = _facts(root, prefixes, accession_no, fiscal_year, fiscal_period)
        lines = _lines(others, prefixes, anchors)
    except (ValueError, ArithmeticError) as error:  # a malformed date, order or weight
        raise XbrlError(f"unreadable XBRL value: {error}") from error
    return ParsedFiling(facts=facts, lines=lines)


def _read(name: str, body: bytes) -> tuple[ET.Element, dict[str, str]]:
    """The document's root and its namespace URI → prefix map (the first declaration wins)."""
    prefixes: dict[str, str] = {}
    try:
        for _, (prefix, uri) in ET.iterparse(io.BytesIO(body), events=("start-ns",)):
            prefixes.setdefault(uri, prefix)
        return ET.fromstring(body), prefixes
    except ET.ParseError as error:
        raise XbrlError(f"{name}: {error}") from error


def _taxonomy(uri: str, prefixes: Mapping[str, str]) -> str:
    """`us-gaap`, `dei`, `srt` (any year, `fasb.org`, `xbrl.sec.gov` or the 2009 `xbrl.us`),
    `ifrs-full`, else the filer's prefix lowercased."""
    parsed = urlparse(uri)
    host = parsed.netloc.lower()
    segments = [s for s in parsed.path.split("/") if s]
    if host in _STANDARD_HOSTS and segments:
        return segments[0].lower()
    if "ifrs-full" in segments:
        return "ifrs-full"
    return prefixes.get(uri, uri).lower()


# --- facts ---------------------------------------------------------------------------------------


def _facts(
    root: ET.Element,
    prefixes: Mapping[str, str],
    accession_no: str,
    fiscal_year: int | None,
    fiscal_period: str | None,
) -> list[FactRecord]:
    periods = _plain_contexts(root)
    units = _units(root)
    # Natural key -> (precision, fact). Of two facts with one key the more precise wins (the
    # higher `decimals`, INF highest), else the first: what companyfacts keeps.
    kept: dict[tuple[str, str, str, date | None, date], tuple[float, FactRecord]] = {}
    for element in root:
        context, unit = element.get("contextRef"), element.get("unitRef")
        if context not in periods or unit not in units or element.get(_XSI_NIL) == "true":
            continue
        value = _decimal(element.text)
        if value is None or not element.tag.startswith("{"):
            continue
        precision = _precision(element.get("decimals"))
        uri, concept = element.tag[1:].split("}", 1)
        taxonomy = _taxonomy(uri, prefixes)
        start, end = periods[context]
        key = (taxonomy, concept, units[unit], start, end)
        if key in kept and kept[key][0] >= precision:
            continue
        fact = FactRecord(
            accession_no=accession_no,
            taxonomy=taxonomy,
            concept=concept,
            unit=units[unit],
            period_start=start,
            period_end=end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            frame=None,
            value=value,
        )
        # A replaced fact keeps its place, so the facts stay in document order.
        kept[key] = (precision, fact)
    return [fact for _, fact in kept.values()]


def _precision(decimals: str | None) -> float:
    if decimals is None or decimals.strip().upper() == "INF":
        return math.inf
    try:
        return int(decimals)
    except ValueError:
        return math.inf


def _plain_contexts(root: ET.Element) -> dict[str, tuple[date | None, date]]:
    """Context id → (start or None, end), for the contexts with no dimension (nothing inside a
    `segment` or `scenario`) and a dated period."""
    periods: dict[str, tuple[date | None, date]] = {}
    for context in root.iter(f"{_XBRLI}context"):
        if any(len(part) for part in context.iter(f"{_XBRLI}segment")) or any(
            len(part) for part in context.iter(f"{_XBRLI}scenario")
        ):
            continue
        period = context.find(f"{_XBRLI}period")
        if period is None:
            continue
        instant = period.findtext(f"{_XBRLI}instant")
        start, end = period.findtext(f"{_XBRLI}startDate"), period.findtext(f"{_XBRLI}endDate")
        context_id = context.get("id")
        if context_id is None:
            continue
        if instant:
            periods[context_id] = (None, _date(instant))
        elif start and end:
            # A duration that starts and ends on one day is an instant to companyfacts.
            first, last = _date(start), _date(end)
            periods[context_id] = (None if first == last else first, last)
    return periods


def _units(root: ET.Element) -> dict[str, str]:
    """Unit id → the companyfacts spelling: the measure's local name (`USD`, `shares`, `pure`),
    or `numerator/denominator` (`USD/shares`)."""
    units: dict[str, str] = {}
    for unit in root.iter(f"{_XBRLI}unit"):
        unit_id = unit.get("id")
        if unit_id is None:
            continue
        divide = unit.find(f"{_XBRLI}divide")
        if divide is not None:
            numerator = _measures(divide.find(f"{_XBRLI}unitNumerator"))
            denominator = _measures(divide.find(f"{_XBRLI}unitDenominator"))
            units[unit_id] = f"{numerator}/{denominator}"
        else:
            units[unit_id] = _measures(unit)
    return units


def _measures(parent: ET.Element | None) -> str:
    if parent is None:
        return ""
    names = [(m.text or "").strip().rsplit(":", 1)[-1] for m in parent.findall(f"{_XBRLI}measure")]
    return "*".join(names)


def _decimal(text: str | None) -> Decimal | None:
    try:
        value = Decimal((text or "").strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError as error:
        raise ValueError(f"date {text.strip()!r}: {error}") from error


# --- statements ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Element:
    concept: Concept
    is_line: bool  # not abstract, not an axis, domain, member, table or line-items element


@dataclass
class _Role:
    title: str
    edges: list[tuple[Concept, Concept, float, str | None]]  # parent, child, order, preferredLabel


def _lines(
    documents: list[ET.Element], prefixes: Mapping[str, str], anchors: StatementAnchors
) -> list[FilingLine]:
    local = _local_elements(documents, prefixes)
    line_flags = {element.concept: element.is_line for element in local.values()}
    titles = _statement_roles(documents)
    roles: dict[str, _Role] = {uri: _Role(title, []) for uri, title in titles.items()}
    calc: dict[str, dict[Concept, tuple[Concept, Decimal]]] = {}
    labels: dict[Concept, dict[str, str]] = {}
    for document in documents:
        for link in document.iter(f"{_LINK}presentationLink"):
            role = roles.get(link.get(f"{_XLINK}role", ""))
            if role is not None:
                role.edges.extend(_presentation_edges(link, local))
        for link in document.iter(f"{_LINK}calculationLink"):
            role_uri = link.get(f"{_XLINK}role", "")
            if role_uri in roles:
                parents = calc.setdefault(role_uri, {})
                for summed, item, item_weight in _calculation_edges(link, local):
                    parents.setdefault(item, (summed, item_weight))
        for link in document.iter(f"{_LINK}labelLink"):
            for concept, role_name, text in _label_entries(link, local):
                labels.setdefault(concept, {}).setdefault(role_name, text)

    chosen: dict[str, tuple[str, list[tuple[Concept, str | None]]]] = {}
    for uri, role in roles.items():
        ordered = [(c, label) for c, label in _walk(role.edges) if _is_line(c, line_flags)]
        statement = _classify({c for c, _ in ordered}, anchors)
        if statement is None:
            continue
        if statement not in chosen or len(ordered) > len(chosen[statement][1]):
            chosen[statement] = (uri, ordered)

    lines: list[FilingLine] = []
    for statement in ("IS", "BS", "CF"):
        if statement not in chosen:
            continue
        uri, ordered = chosen[statement]
        parents = calc.get(uri, {})
        for position, (concept, preferred) in enumerate(ordered, start=1):
            parent: Concept | None = None
            weight: Decimal | None = None
            if concept in parents:
                parent, weight = parents[concept]
            lines.append(
                FilingLine(
                    statement=statement,
                    position=position,
                    taxonomy=concept[0],
                    concept=concept[1],
                    label=_label(labels.get(concept, {}), preferred, concept[1]),
                    calc_parent_taxonomy=parent[0] if parent else None,
                    calc_parent_concept=parent[1] if parent else None,
                    calc_weight=weight,
                )
            )
    return lines


def _local_elements(
    documents: list[ET.Element], prefixes: Mapping[str, str]
) -> dict[str, _Element]:
    """The filer's own schema elements, by id: their concept and whether they can be a line."""
    elements: dict[str, _Element] = {}
    for document in documents:
        if document.tag != f"{_XSD}schema":
            continue
        taxonomy = _taxonomy(document.get("targetNamespace", ""), prefixes)
        for element in document.iter(f"{_XSD}element"):
            element_id, name = element.get("id"), element.get("name")
            if not element_id or not name:
                continue
            group = element.get("substitutionGroup", "")
            is_line = (
                element.get("abstract", "false").lower() != "true"
                and not group.endswith(("dimensionItem", "hypercubeItem"))
                and not name.endswith(_NOT_A_LINE)
            )
            elements[element_id] = _Element((taxonomy, name), is_line)
    return elements


def _statement_roles(documents: list[ET.Element]) -> dict[str, str]:
    """Role URI → title, for `<n> - Statement - <title>` roles that are not parenthetical."""
    roles: dict[str, str] = {}
    for document in documents:
        for role_type in document.iter(f"{_LINK}roleType"):
            match = _STATEMENT.match(role_type.findtext(f"{_LINK}definition") or "")
            uri = role_type.get("roleURI")
            if match and uri and "parenthetical" not in match.group(1).lower():
                roles[uri] = match.group(1).strip()
    return roles


def _concept(href: str, local: Mapping[str, _Element]) -> Concept | None:
    """The concept a locator points at: a filer element by its schema id, else a standard one by
    its conventional `prefix_Name` id."""
    fragment = href.rsplit("#", 1)[-1]
    if fragment in local:
        return local[fragment].concept
    prefix, _, name = fragment.partition("_")
    if not name:
        return None
    return (prefix.lower(), name)


def _locators(link: ET.Element, local: Mapping[str, _Element]) -> dict[str, Concept]:
    found: dict[str, Concept] = {}
    for loc in link.iter(f"{_LINK}loc"):
        label, concept = loc.get(f"{_XLINK}label"), _concept(loc.get(f"{_XLINK}href", ""), local)
        if label and concept:
            found[label] = concept
    return found


def _arcs(link: ET.Element, tag: str) -> Iterable[ET.Element]:
    return (arc for arc in link.iter(f"{_LINK}{tag}") if arc.get("use") != "prohibited")


def _presentation_edges(
    link: ET.Element, local: Mapping[str, _Element]
) -> list[tuple[Concept, Concept, float, str | None]]:
    locs = _locators(link, local)
    edges = []
    for arc in _arcs(link, "presentationArc"):
        parent, child = locs.get(arc.get(f"{_XLINK}from", "")), locs.get(arc.get(f"{_XLINK}to", ""))
        if parent and child:
            edges.append((parent, child, float(arc.get("order", "1")), arc.get("preferredLabel")))
    return edges


def _calculation_edges(
    link: ET.Element, local: Mapping[str, _Element]
) -> list[tuple[Concept, Concept, Decimal]]:
    locs = _locators(link, local)
    edges = []
    for arc in _arcs(link, "calculationArc"):
        if not arc.get(f"{_XLINK}arcrole", "").endswith("summation-item"):
            continue
        parent, child = locs.get(arc.get(f"{_XLINK}from", "")), locs.get(arc.get(f"{_XLINK}to", ""))
        weight = _decimal(arc.get("weight"))
        if parent and child and weight is not None:
            edges.append((parent, child, weight.normalize()))
    return edges


def _label_entries(
    link: ET.Element, local: Mapping[str, _Element]
) -> list[tuple[Concept, str, str]]:
    locs = _locators(link, local)
    resources: dict[str, list[tuple[str, str]]] = {}
    for label in link.iter(f"{_LINK}label"):
        key = label.get(f"{_XLINK}label")
        if key:
            text = " ".join("".join(label.itertext()).split())
            resources.setdefault(key, []).append(
                (label.get(f"{_XLINK}role", _STANDARD_LABEL), text)
            )
    entries = []
    for arc in _arcs(link, "labelArc"):
        concept = locs.get(arc.get(f"{_XLINK}from", ""))
        if concept:
            for role, text in resources.get(arc.get(f"{_XLINK}to", ""), []):
                entries.append((concept, role, text))
    return entries


def _walk(
    edges: list[tuple[Concept, Concept, float, str | None]],
) -> list[tuple[Concept, str | None]]:
    """Depth-first presentation order from the roots; a concept is listed once (its first
    place), with the preferred label of that place."""
    children: dict[Concept, list[tuple[float, int, Concept, str | None]]] = {}
    seen_parents: list[Concept] = []
    child_set: set[Concept] = set()
    for index, (parent, child, order, preferred) in enumerate(edges):
        children.setdefault(parent, []).append((order, index, child, preferred))
        if parent not in seen_parents:
            seen_parents.append(parent)
        child_set.add(child)
    ordered: list[tuple[Concept, str | None]] = []
    listed: set[Concept] = set()
    visited: set[Concept] = set()

    def visit(concept: Concept, preferred: str | None) -> None:
        if concept not in listed:
            listed.add(concept)
            ordered.append((concept, preferred))
        if concept in visited:
            return
        visited.add(concept)
        for _, _, child, child_label in sorted(children.get(concept, [])):
            visit(child, child_label)

    for root in (p for p in seen_parents if p not in child_set):
        visit(root, None)
    return ordered


def _is_line(concept: Concept, line_flags: Mapping[Concept, bool]) -> bool:
    """A filer element by its schema attributes; a standard one by the us-gaap naming rules
    (abstracts end in `Abstract`, axes in `Axis`, and so on)."""
    if concept in line_flags:
        return line_flags[concept]
    return not concept[1].endswith(_NOT_A_LINE)


def _classify(concepts: set[Concept], anchors: StatementAnchors) -> str | None:
    if ("us-gaap", "Assets") in concepts and concepts & anchors.liabilities_and_equity:
        return "BS"
    if concepts & anchors.cfo:
        return "CF"
    if concepts & anchors.net_income and concepts & anchors.revenue_or_eps:
        return "IS"
    return None


def _label(labels: Mapping[str, str], preferred: str | None, name: str) -> str:
    if preferred and preferred in labels:
        return labels[preferred]
    return labels.get(_STANDARD_LABEL) or next(iter(labels.values()), name)


def is_standard_taxonomy(taxonomy: str) -> bool:
    """us-gaap, dei, srt or ifrs-full: the taxonomies companyfacts already carries."""
    return taxonomy in _STANDARD_TAXONOMIES
