"""Candidate canonical codes for a concept, from the vendored edgartools table. Pure.

The table (`vendor/edgartools_gaap_mappings.json`, MIT) maps about 2,900 concepts to coarser
"standard" concepts, and `crosswalk.yaml` maps those to Bedrock codes. The result is a *hint*: it is
shown next to unmapped concepts and starts a `map-xbrl` session, but it never feeds `map_facts`.
The coarse concepts would put components under total labels, which the single-concept rule forbids.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from bedrock.mapping.config import (
    CanonicalItemDef,
    MappingConfigError,
    split_concept,
)

DEFAULT_VENDOR_PATH = Path(__file__).parent / "vendor" / "edgartools_gaap_mappings.json"
DEFAULT_CROSSWALK_PATH = Path(__file__).parent / "crosswalk.yaml"

CandidateIndex = dict[tuple[str, str], list[str]]  # (taxonomy, concept) -> Bedrock codes

_IFRS = "ifrs-full"
_PREFIXED = re.compile(
    r"^([a-z][a-z0-9-]*)_(.+)$"
)  # `ifrs-full_Revenue`; us-gaap names start upper-case


def load_candidate_index(
    vendor_path: Path, crosswalk_path: Path, items: Sequence[CanonicalItemDef]
) -> CandidateIndex:
    """(taxonomy, concept) -> codes, in the order of the concept's standard tags. Concepts whose
    tags are all unmapped are left out. Raises `MappingConfigError` when the crosswalk and the
    table disagree: a standard concept missing from the crosswalk, listed in both sections or not
    in the table, a code that is unknown or residual, or an unmapped concept without a reason."""
    tags_of = _read_vendor(vendor_path)
    codes_of = _read_crosswalk(crosswalk_path, {i.code: i for i in items})

    known = {tag for tags in tags_of.values() for tag in tags}
    missing = sorted(known - set(codes_of))
    if missing:
        raise MappingConfigError(
            f"the crosswalk does not list {len(missing)} standard concept(s) of the table: "
            f"{', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''}"
        )
    stale = sorted(set(codes_of) - known)
    if stale:
        raise MappingConfigError(
            f"the crosswalk lists standard concept(s) the table does not have: {', '.join(stale)}"
        )

    index: CandidateIndex = {}
    for key, tags in tags_of.items():
        codes: list[str] = []
        for tag in tags:
            codes.extend(code for code in codes_of[tag] if code not in codes)
        if codes:
            index[key] = codes
    return index


def candidate_codes(index: CandidateIndex, taxonomy: str, concept: str) -> list[str]:
    return list(index.get((taxonomy, concept), []))


def _read_vendor(path: Path) -> dict[tuple[str, str], list[str]]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise MappingConfigError(f"{path.name} must be an object of concepts")
    tags_of: dict[tuple[str, str], list[str]] = {}
    for name, entry in raw.items():
        if name.startswith("_"):  # `_metadata`, `_comment*`
            continue
        tags = entry.get("standard_tags") if isinstance(entry, dict) else None
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise MappingConfigError(f"{path.name}: {name!r} has no `standard_tags` list")
        tags_of[_normalize(name)] = tags
    return tags_of


def _normalize(name: str) -> tuple[str, str]:
    """`Revenues` -> (`us-gaap`, `Revenues`); `ifrs-full_Revenue` and `ifrs:Revenue` ->
    (`ifrs-full`, `Revenue`)."""
    prefixed = _PREFIXED.match(name)
    taxonomy, concept = split_concept(f"{prefixed[1]}:{prefixed[2]}" if prefixed else name)
    return (_IFRS if taxonomy == "ifrs" else taxonomy, concept)


def _read_crosswalk(path: Path, by_code: dict[str, CanonicalItemDef]) -> dict[str, list[str]]:
    raw: Any = yaml.safe_load(path.read_text())
    codes = raw.get("codes") if isinstance(raw, dict) else None
    unmapped = raw.get("unmapped") if isinstance(raw, dict) else None
    if not isinstance(codes, dict) or not isinstance(unmapped, dict):
        raise MappingConfigError(f"{path.name} needs `codes:` and `unmapped:` mappings")

    both = sorted(set(codes) & set(unmapped))
    if both:
        raise MappingConfigError(f"listed as both mapped and unmapped: {', '.join(both)}")

    result: dict[str, list[str]] = {}
    for tag, value in codes.items():
        wanted = value if isinstance(value, list) else [value]
        for code in wanted:
            if code not in by_code:
                raise MappingConfigError(f"{tag}: unknown code {code!r}")
            if by_code[code].residual:
                raise MappingConfigError(f"{tag}: {code!r} is a residual, which is never mapped")
        result[str(tag)] = list(wanted)
    for tag, reason in unmapped.items():
        if not isinstance(reason, str) or not reason.strip():
            raise MappingConfigError(f"{tag}: an unmapped concept needs a reason")
        result[str(tag)] = []
    return result
