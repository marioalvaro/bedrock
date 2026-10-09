"""Loading and validating the canonical item list and the per-company overrides.

Pure apart from reading the YAML files it is given.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ITEMS_PATH = Path(__file__).parent / "canonical_items.yaml"
DEFAULT_OVERRIDES_DIR = Path(__file__).parent / "overrides"

STATEMENTS = ("IS", "BS", "CF")
KINDS = ("flow", "instant", "average")
UNITS = ("USD", "USD/shares", "shares")
DEFAULT_TAXONOMY = "us-gaap"

_CODE = r"[a-z][a-z0-9_]*"
_FORMULA = re.compile(rf"^\s*({_CODE})(\s*[+-]\s*{_CODE})*\s*$")
_TERM = re.compile(rf"([+-]?)\s*({_CODE})")


class MappingConfigError(ValueError):
    """The mapping configuration is invalid; `code` is the offending canonical code."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(f"{code}: {message}" if code else message)
        self.code = code


@dataclass(frozen=True)
class CanonicalItemDef:
    code: str
    statement: str
    label: str
    kind: str
    unit: str
    sign: int
    parent: str | None
    concepts: tuple[str, ...]  # "taxonomy:Concept", in priority order
    derive: str | None
    residual: bool


def split_concept(text: str) -> tuple[str, str]:
    """`Revenues` -> (`us-gaap`, `Revenues`); `ifrs-full:Revenue` -> (`ifrs-full`, `Revenue`)."""
    taxonomy, sep, concept = text.partition(":")
    return (taxonomy, concept) if sep else (DEFAULT_TAXONOMY, text)


def split_group(entry: str) -> list[tuple[str, str]]:
    """A concept entry `A + B` -> [(taxonomy, A), (taxonomy, B)]: the members of a summed concept,
    anchor first. A plain concept is a group of one."""
    return [split_concept(member.strip()) for member in entry.split("+")]


def parse_formula(text: str) -> list[tuple[int, str]]:
    """`a - b + c` -> [(1, "a"), (-1, "b"), (1, "c")]."""
    if not _FORMULA.match(text):
        raise MappingConfigError(f"malformed formula {text!r}")
    return [(-1 if sign == "-" else 1, code) for sign, code in _TERM.findall(text)]


def load_canonical_items(path: Path = DEFAULT_ITEMS_PATH) -> list[CanonicalItemDef]:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise MappingConfigError(f"{path.name} must be a list of items")
    items = [_item(entry) for entry in raw]
    _validate(items)
    return items


def load_overrides(
    directory: Path, ticker: str, items: Sequence[CanonicalItemDef] | None = None
) -> dict[str, list[str]]:
    """`<ticker>.yaml` maps `code: [concepts...]`. Concepts come back as `taxonomy:Concept`."""
    path = directory / f"{ticker.upper()}.yaml"
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise MappingConfigError(f"{path.name} must map codes to concept lists")
    by_code = {i.code: i for i in items} if items is not None else None
    overrides: dict[str, list[str]] = {}
    for code, concepts in raw.items():
        if by_code is not None:
            if code not in by_code:
                raise MappingConfigError(f"override for unknown code in {path.name}", code)
            if by_code[code].residual:
                raise MappingConfigError("residual items cannot be overridden", code)
        if not isinstance(concepts, list) or not all(isinstance(c, str) for c in concepts):
            raise MappingConfigError(f"override must be a list of concepts in {path.name}", code)
        overrides[code] = _qualify(code, concepts)
    return overrides


def formula_order(items: Sequence[CanonicalItemDef]) -> list[CanonicalItemDef]:
    """Items with a `derive` formula, operands before the items that use them."""
    by_code = {i.code: i for i in items}
    ordered: list[CanonicalItemDef] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(code: str) -> None:
        item = by_code.get(code)
        if item is None or item.derive is None or code in done:
            return
        if code in visiting:
            raise MappingConfigError("formula cycle", code)
        visiting.add(code)
        for _, operand in parse_formula(item.derive):
            visit(operand)
        visiting.discard(code)
        done.add(code)
        ordered.append(item)

    for item in items:
        visit(item.code)
    return ordered


def _item(entry: Any) -> CanonicalItemDef:
    if not isinstance(entry, dict) or not isinstance(entry.get("code"), str):
        raise MappingConfigError(f"item without a code: {entry!r}")
    code = entry["code"]
    for field in ("statement", "label", "kind", "unit", "sign"):
        if field not in entry:
            raise MappingConfigError(f"missing field {field!r}", code)
    for field, allowed in (("statement", STATEMENTS), ("kind", KINDS), ("unit", UNITS)):
        if entry[field] not in allowed:
            raise MappingConfigError(
                f"{field} must be one of {allowed}, got {entry[field]!r}", code
            )
    if entry["sign"] not in (1, -1) or isinstance(entry["sign"], bool):
        raise MappingConfigError(f"sign must be 1 or -1, got {entry['sign']!r}", code)
    concepts = entry.get("concepts") or []
    if not isinstance(concepts, list) or not all(isinstance(c, str) for c in concepts):
        raise MappingConfigError("concepts must be a list of strings", code)
    return CanonicalItemDef(
        code=code,
        statement=entry["statement"],
        label=str(entry["label"]),
        kind=entry["kind"],
        unit=entry["unit"],
        sign=entry["sign"],
        parent=entry.get("parent"),
        concepts=tuple(_qualify(code, concepts)),
        derive=entry.get("derive"),
        residual=bool(entry.get("residual", False)),
    )


def _qualify(code: str, concepts: list[str]) -> list[str]:
    """Each entry as `taxonomy:Concept`, or `taxonomy:A + taxonomy:B` for a summed concept. The
    members of a sum are distinct and share one taxonomy; no entry may repeat (a concept may recur
    as a member of another entry, which is how a sum falls back to its anchor alone)."""
    qualified = [_qualify_entry(code, c) for c in concepts]
    if len(set(qualified)) != len(qualified):
        raise MappingConfigError("duplicate concept", code)
    return qualified


def _qualify_entry(code: str, entry: str) -> str:
    members = split_group(entry)
    if any(not concept for _, concept in members):
        raise MappingConfigError(f"empty member in {entry!r}", code)
    if len(set(members)) != len(members):
        raise MappingConfigError(f"duplicate member in {entry!r}", code)
    if len({taxonomy for taxonomy, _ in members}) > 1:
        raise MappingConfigError(f"members of {entry!r} must share a taxonomy", code)
    return " + ".join(f"{taxonomy}:{concept}" for taxonomy, concept in members)


def _validate(items: list[CanonicalItemDef]) -> None:
    by_code: dict[str, CanonicalItemDef] = {}
    for item in items:
        if item.code in by_code:
            raise MappingConfigError("duplicate code", item.code)
        by_code[item.code] = item

    for item in items:
        if item.parent is not None:
            parent = by_code.get(item.parent)
            if parent is None:
                raise MappingConfigError(f"unknown parent {item.parent!r}", item.code)
            if parent.statement != item.statement:
                raise MappingConfigError(
                    f"parent {item.parent!r} is on another statement", item.code
                )
        if item.residual and (item.derive is None or item.concepts):
            raise MappingConfigError("a residual needs `derive` and no concepts", item.code)
        if item.derive is not None:
            for _, operand in parse_formula(item.derive):
                if operand not in by_code:
                    raise MappingConfigError(
                        f"formula references unknown code {operand!r}", item.code
                    )
                if by_code[operand].statement != item.statement:
                    raise MappingConfigError(
                        f"formula operand {operand!r} is on another statement", item.code
                    )

    for item in items:  # walk each parent chain: a cycle never reaches a root
        seen = {item.code}
        node = item
        while node.parent is not None:
            if node.parent in seen:
                raise MappingConfigError("parent cycle", item.code)
            seen.add(node.parent)
            node = by_code[node.parent]

    formula_order(items)  # raises on a formula cycle
