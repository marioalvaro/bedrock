"""The field-level diff the audit trail records (docs/erd/accountability.md "Audit trail"). Pure."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldChange:
    field: str
    old: str | None
    new: str | None


def changes(before: Mapping[str, str | None], after: Mapping[str, str | None]) -> list[FieldChange]:
    """The fields whose value differs, sorted by field. An absent field equals None."""
    return [
        FieldChange(field, before.get(field), after.get(field))
        for field in sorted({*before, *after})
        if before.get(field) != after.get(field)
    ]
