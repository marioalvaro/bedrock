"""The value types of a statement cell: its value, provenance and the fact or derivation behind it.
Shared by the cell engine (`cells.py`) and the rule engine (`rules.py`). Pure."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

Provenance = Literal["reported", "derived", "normalized", "zero_inferred"]


@dataclass(frozen=True)
class FactRef:
    taxonomy: str
    concept: str
    unit: str
    period_start: date | None
    period_end: date
    accession_no: str
    form: str
    filed_at: date


@dataclass(frozen=True)
class DerivationInput:
    code: str
    fiscal_period: str  # FY, Q1..Q4, or "YTD Q2" for a year-to-date figure
    value: Decimal


@dataclass(frozen=True)
class Derivation:
    formula: str
    inputs: tuple[DerivationInput, ...]


@dataclass(frozen=True)
class Cell:
    value: Decimal | None
    provenance: Provenance | None
    source: FactRef | None = None
    derivation: Derivation | None = None
    solved_by: str | None = None  # the identity that filled this cell (see `rules.py`)


EMPTY = Cell(None, None)

CellKey = tuple[str, str]  # (code, period key)


@dataclass(frozen=True)
class RuleWarning:
    """A rule that produced a value and was refused by a guard, or two rules that disagreed: the
    cell stays as it was. `value` is the refused value (None when no value was produced)."""

    rule: str
    code: str
    period_key: str
    value: Decimal | None
    reason: str
