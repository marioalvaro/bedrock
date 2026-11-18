"""The known-answer test (docs/erd/face-tree.md "Known-answer test"): face lines whose answer
the mappings already give, asked as if they were open, and the scoring of the answers. Pure: the
classifier is passed in."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from bedrock.classify import questions
from bedrock.classify.protocol import LineClassifier
from bedrock.classify.types import LineAnswer, LineQuestion, Usage
from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.projection import PlacedLine
from bedrock.statements.structure import FaceLines

# (label, lower bound): a band holds the confidences from its bound up to the next band's
BAND_BOUNDS = (("below 0.5", 0.0), ("0.5–0.7", 0.5), ("0.7–0.9", 0.7), ("0.9 and above", 0.9))
RATIO_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class Case:
    question: LineQuestion  # built as for an open line: it does not say what is known
    expected: tuple[str, ...]  # (code,) the line's row; () none of the rows


@dataclass(frozen=True)
class Band:
    label: str
    answered: int
    correct: int


@dataclass(frozen=True)
class Score:
    cases: int
    answered: int
    failed: int  # cases with no usable answer
    correct: int
    bands: tuple[Band, ...]  # by confidence, lowest first; they partition `answered`

    @property
    def confident(self) -> Band:
        """The answers at confidence 0.9 and above: what mode `all` would use unreviewed."""
        return self.bands[-1]


Outcome = tuple[Case, LineAnswer | None]  # None: the line failed


def cases(face: FaceLines, items: Sequence[CanonicalItemDef]) -> list[Case]:
    """The lines of one company with a known answer, distinct by (statement, taxonomy, concept),
    in question order. Expected `(code,)`: a leaf line mapped to exactly one row that is among
    its candidates (a row that is not could never be answered). Expected `()`: a line under
    `other_lines`, or with a triage verdict that names no code."""
    out: list[Case] = []
    for asked in questions.select(face, items, lambda line: _expected(face, line) is not None):
        expected = _expected(face, asked.line)
        offered = {c.code for c in asked.question.candidates}
        if expected is not None and set(expected) <= offered:
            out.append(Case(asked.question, expected))
    return out


def ask(classifier: LineClassifier, asked: Sequence[Case]) -> tuple[list[Outcome], Usage]:
    """Every case's answer (None for a failed line), asked in batches of the classifier's size,
    and the tokens used."""
    answers: dict[str, LineAnswer] = {}
    usage = Usage(0, 0)
    for start in range(0, len(asked), classifier.batch_size):
        batch = [case.question for case in asked[start : start + classifier.batch_size]]
        result = classifier.classify(batch)
        answers.update({answer.key: answer for answer in result.answers})
        usage += result.usage
    return [(case, answers.get(case.question.key)) for case in asked], usage


def score(outcomes: Sequence[Outcome]) -> Score:
    """An answer is correct when it names exactly the expected rows."""
    answered = [(case, answer) for case, answer in outcomes if answer is not None]
    in_band: list[list[bool]] = [[] for _ in BAND_BOUNDS]
    for case, answer in answered:
        band = max(
            n for n, (_, low) in enumerate(BAND_BOUNDS) if answer.confidence >= low or n == 0
        )
        in_band[band].append(set(answer.codes) == set(case.expected))
    bands = tuple(
        Band(label, len(hits), sum(hits))
        for (label, _), hits in zip(BAND_BOUNDS, in_band, strict=True)
    )
    return Score(
        cases=len(outcomes),
        answered=len(answered),
        failed=len(outcomes) - len(answered),
        correct=sum(b.correct for b in bands),
        bands=bands,
    )


def ratio(part: int, whole: int) -> Decimal | None:
    """`part / whole` to four places; None when there is nothing to divide by."""
    return (Decimal(part) / Decimal(whole)).quantize(RATIO_PLACES) if whole else None


def _expected(face: FaceLines, line: PlacedLine) -> tuple[str, ...] | None:
    """The known answer of a placed line; None when it has none."""
    concept = (line.taxonomy, line.concept)
    if line.kind == "mapped" and not line.is_total and len(line.codes) == 1:
        return line.codes
    no_code_verdict = concept in face.verdicts and not face.verdicts[concept]
    if line.kind == "other" and (concept in face.other_lines or no_code_verdict):
        return ()
    return None
