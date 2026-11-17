"""The question for one face line and a classifier's answer (docs/erd/face-tree.md "Types")."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Candidate:
    code: str
    label: str


@dataclass(frozen=True)
class LineQuestion:
    key: str  # "<statement>|<taxonomy>|<concept>"
    statement: str
    taxonomy: str
    concept: str
    label: str  # as the newest filing that presents the line shows it
    form: str  # of that filing
    period_end: date  # of the line's newest value in that filing
    value: Decimal | None  # that value
    parent_label: str | None  # its calculation parent's label
    parent_value: Decimal | None  # the parent's value for the same period
    sibling_labels: tuple[str, ...]  # the parent's other children, at most 12, as presented
    block_label: str | None  # the canonical label of the line's block
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class LineAnswer:
    key: str
    codes: tuple[str, ...]  # () none of the candidates; (x,) that row; two or more: one combined
    confidence: float  # 0..1


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens
        )


@dataclass(frozen=True)
class ClassifyResult:
    answers: tuple[LineAnswer, ...]
    failed: tuple[str, ...]  # keys with no usable answer
    usage: Usage
    # Why the answer as a whole was unusable (cut off, filtered, not the schema); None when it was
    # usable, though single lines may still have failed. A run reports it (S5 follow-up).
    reason: str | None = None
