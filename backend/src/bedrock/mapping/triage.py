"""The concept triage file (FR-DATA-13): one verdict per concept nothing maps. Pure apart from
reading the YAML file it is given.

A verdict records why a concept an open table suggests is *not* a canonical line (a note schedule,
a component, a different measure, a total of another scope), so Data gaps shows only what is still
undecided. It never feeds `map_facts`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bedrock.mapping.config import (
    CanonicalItemDef,
    MappingConfigError,
    split_concept,
    split_group,
)

DEFAULT_TRIAGE_PATH = Path(__file__).parent / "concept_triage.yaml"

TRIAGE_TYPES = ("disclosure", "component", "rejected", "scope", "candidate")
_KEYS = {"type", "reason", "codes"}

ConceptKey = tuple[str, str]  # (taxonomy, concept)


@dataclass(frozen=True)
class ConceptVerdict:
    type: str  # one of TRIAGE_TYPES
    reason: str
    codes: tuple[str, ...]  # the canonical codes it is about; empty for a disclosure


class _UniqueKeyLoader(yaml.SafeLoader):
    """`safe_load` keeps the last of two equal keys; a triage file must name a concept once."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise MappingConfigError(f"duplicate concept {key!r}")
            seen.add(key)
        return super().construct_mapping(node, deep)


def load_concept_triage(
    path: Path, items: Sequence[CanonicalItemDef]
) -> dict[ConceptKey, ConceptVerdict]:
    """(taxonomy, concept) -> verdict. Keys are concepts, bare names meaning `us-gaap:`. Raises
    `MappingConfigError` for an unknown type or key, a missing or blank reason, missing or unknown
    codes, a duplicate concept (also under two spellings), and a concept that is a default concept
    of an item: a verdict on a mapped concept contradicts the mapping. A concept only some
    company's override maps may have a verdict (the others do not map it)."""
    raw = yaml.load(path.read_text(), Loader=_UniqueKeyLoader) or {}  # noqa: S506 (safe subclass)
    if not isinstance(raw, dict):
        raise MappingConfigError(f"{path.name} must map concepts to verdicts")
    known = {i.code for i in items}
    defaults = {m for i in items for entry in i.concepts for m in split_group(entry)}
    triage: dict[ConceptKey, ConceptVerdict] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise MappingConfigError(f"a triage key must be a concept name, got {key!r}")
        concept = split_concept(key.strip())
        label = key.strip()
        if concept in triage:
            raise MappingConfigError(f"duplicate concept {label!r}")
        if concept in defaults:
            raise MappingConfigError(
                f"{label!r} is a default concept of an item: a verdict on a mapped concept "
                "contradicts the mapping"
            )
        triage[concept] = _verdict(label, entry, known)
    return triage


def _verdict(label: str, entry: Any, known: set[str]) -> ConceptVerdict:
    if not isinstance(entry, dict):
        raise MappingConfigError(f"{label}: a verdict must be a mapping with type and reason")
    extra = sorted(str(k) for k in set(entry) - _KEYS)
    if extra:
        raise MappingConfigError(
            f"{label}: unknown key {extra[0]!r} (allowed: type, reason, codes)"
        )
    kind = entry.get("type")
    if kind not in TRIAGE_TYPES:
        raise MappingConfigError(f"{label}: type must be one of {TRIAGE_TYPES}, got {kind!r}")
    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise MappingConfigError(f"{label}: a verdict needs a reason")
    codes = entry.get("codes")
    if codes is None:
        codes = []
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise MappingConfigError(f"{label}: codes must be a list of canonical codes")
    if kind != "disclosure" and not codes:
        raise MappingConfigError(f"{label}: a {kind} verdict needs codes")
    for code in codes:
        if code not in known:
            raise MappingConfigError(f"{label}: unknown code {code!r}")
    return ConceptVerdict(kind, reason.strip(), tuple(codes))
