"""The batch question and answer of the adapters that ask a chat model several lines at once
(docs/erd/face-tree.md "Batch answers"): Claude and OpenRouter. Pure: no network."""

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from bedrock.classify import prompt
from bedrock.classify.types import ClassifyResult, LineAnswer, LineQuestion, Usage

# Estimate (docs/erd/face-tree.md): input = characters / 3; output per request and per line
CHARS_PER_TOKEN = 3
OUTPUT_PER_REQUEST = 400
OUTPUT_PER_LINE = 60


class Answer(BaseModel):
    index: int
    codes: list[str]
    confidence: float


class BatchAnswer(BaseModel):
    answers: list[Answer]


# The answer's JSON schema for a strict structured output: no references, every field
# required, no other field allowed. `BatchAnswer` validates what comes back.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "codes": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": ["index", "codes", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["answers"],
    "additionalProperties": False,
}


def user_message(questions: Sequence[LineQuestion]) -> str:
    """The one user message of a request: a sentence on the answer, then each question as
    `Line <n>` (from 0) and its rendering."""
    head = (
        f"Place each of the {len(questions)} lines below. Give one answer per line, with the "
        "line's number as `index`; `codes` holds the chosen row's code, several codes for a line "
        "that merges rows, or nothing for none; `confidence` is between 0 and 1."
    )
    return "\n\n".join([head, *(f"Line {n}\n{prompt.render(q)}" for n, q in enumerate(questions))])


def estimate(questions: Sequence[LineQuestion], batch_size: int) -> Usage:
    """The tokens of asking `questions` in requests of `batch_size`: input = ⌈characters of the
    instructions and the user message ÷ 3⌉, output = 400 per request + 60 per line."""
    total = Usage(0, 0)
    for start in range(0, len(questions), batch_size):
        part = questions[start : start + batch_size]
        characters = len(prompt.INSTRUCTIONS) + len(user_message(part))
        total += Usage(
            math.ceil(characters / CHARS_PER_TOKEN),
            OUTPUT_PER_REQUEST + OUTPUT_PER_LINE * len(part),
        )
    return total


def result(questions: Sequence[LineQuestion], text: str | None, usage: Usage) -> ClassifyResult:
    """The result of one request. `text` is the model's answer, or None when it is unusable as a
    whole (a refusal, a cut-off answer): then every line fails. A text that is not the schema
    fails every line too; `usage` is kept either way."""
    usable = _usable(questions, _parse(text))
    return ClassifyResult(
        tuple(usable[q.key] for q in questions if q.key in usable),
        tuple(q.key for q in questions if q.key not in usable),
        usage,
    )


def _parse(text: str | None) -> list[Answer]:
    if text is None:
        return []
    try:
        return BatchAnswer.model_validate_json(text).answers
    except ValidationError:
        return []


def _usable(questions: Sequence[LineQuestion], answers: Sequence[Answer]) -> dict[str, LineAnswer]:
    """key -> answer, for the lines answered once and only with their own candidates."""
    times = Counter(a.index for a in answers)
    out: dict[str, LineAnswer] = {}
    for answer in answers:
        if not 0 <= answer.index < len(questions) or times[answer.index] > 1:
            continue
        question = questions[answer.index]
        allowed = {c.code for c in question.candidates}
        codes = tuple(dict.fromkeys(answer.codes))
        if set(codes) <= allowed:
            out[question.key] = LineAnswer(
                question.key, codes, min(1.0, max(0.0, answer.confidence))
            )
    return out
