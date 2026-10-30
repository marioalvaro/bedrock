"""Custom child lines among the canonical items (docs/erd/data.md "Custom lines"). Pure."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Protocol

from bedrock.mapping.config import CanonicalItemDef

BUILT_FROM_CHILDREN = "sum of custom breakdown"  # the derivation of a parent built from its lines


class LineSpec(Protocol):
    """A stored custom line: the `custom_line` row, or what an import adds."""

    @property
    def code(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def statement(self) -> str: ...
    @property
    def parent_code(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def unit(self) -> str: ...
    @property
    def children_complete(self) -> bool: ...


def custom_items(
    items: Sequence[CanonicalItemDef], lines: Iterable[LineSpec]
) -> list[CanonicalItemDef]:
    """The lines as items (kind and unit as stored). A line shows in its parent's convention, so
    its sign is the nearest canonical ancestor's; a line whose chain does not end in a canonical
    item is left out."""
    by_code = {i.code: i for i in items}
    out: list[CanonicalItemDef] = []
    for line in lines:
        ancestor = by_code.get(line.parent_code)
        if ancestor is None:
            continue
        item = CanonicalItemDef(
            line.code,
            line.statement,
            line.label,
            line.kind,
            line.unit,
            ancestor.sign,
            line.parent_code,
            (),
            None,
            False,
            (),
            custom=True,
        )
        by_code[line.code] = item
        out.append(item)
    return out


def merge_lines(
    items: Sequence[CanonicalItemDef], custom: Sequence[CanonicalItemDef]
) -> list[CanonicalItemDef]:
    """The canonical items with each custom line right after its parent, nested lines after
    theirs, siblings in the order given. A custom line whose parent is not among the items or the
    earlier lines is left out."""
    children: defaultdict[str, list[CanonicalItemDef]] = defaultdict(list)
    for line in custom:
        children[line.parent or ""].append(line)

    merged: list[CanonicalItemDef] = []

    def add(item: CanonicalItemDef) -> None:
        merged.append(item)
        for child in children.get(item.code, []):
            add(child)

    for item in items:
        add(item)
    return merged


def complete_parents(lines: Iterable[tuple[str, str, bool]]) -> frozenset[str]:
    """The parents whose breakdown is complete, from `(code, parent code, children_complete)` of
    every custom line: each line under the parent carries the parent's flag, and the breakdown
    counts only when all of them are marked."""
    marked: dict[str, bool] = {}
    for _, parent, flag in lines:
        marked[parent] = marked.get(parent, True) and flag
    return frozenset(parent for parent, complete in marked.items() if complete)
