"""The Claude classifiers (docs/erd/face-tree.md "Claude adapter"): one Messages request per
batch, the answer constrained to a JSON schema. Touches the network; called only from a
user-started run."""

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from bedrock.classify import prompt
from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable
from bedrock.classify.types import ClassifyResult, LineAnswer, LineQuestion, Usage

MAX_TOKENS = 4000
EFFORT = "low"
# Estimate (docs/erd/face-tree.md): input = characters / 3; output per request and per line
CHARS_PER_TOKEN = 3
OUTPUT_PER_REQUEST = 400
OUTPUT_PER_LINE = 60
# Claude Sonnet 5.5 may decline a request (`stop_reason` "refusal"); the server-side fallback
# re-runs it on the model the API picks for the refusal's category. Haiku 5.5 has none.
FALLBACK_MODELS = frozenset({"claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FAILED_STOPS = frozenset({"refusal", "max_tokens"})


class Answer(BaseModel):
    index: int
    codes: list[str]
    confidence: float


class BatchAnswer(BaseModel):
    answers: list[Answer]


class ClaudeClassifier:
    batch_size = 10

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        """`client` is for tests. With neither a client nor a key the classifier can estimate
        but not ask (`classify` raises `ClassifierUnavailable`)."""
        self.model = model
        self.name = f"claude:{model}"
        if client is None and api_key:
            client = anthropic.Anthropic(api_key=api_key)
        self._client = client

    def estimate(self, questions: Sequence[LineQuestion]) -> Usage:
        total = Usage(0, 0)
        for start in range(0, len(questions), self.batch_size):
            batch = questions[start : start + self.batch_size]
            characters = len(prompt.INSTRUCTIONS) + len(_user_message(batch))
            total += Usage(
                math.ceil(characters / CHARS_PER_TOKEN),
                OUTPUT_PER_REQUEST + OUTPUT_PER_LINE * len(batch),
            )
        return total

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        if len(questions) > self.batch_size:
            raise ValueError(f"classify takes at most {self.batch_size} questions")
        if not questions:
            return ClassifyResult((), (), Usage(0, 0))
        if self._client is None:
            raise ClassifierUnavailable(f"{self.name} has no API key")
        response = self._ask(self._client, questions)
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        answers = [] if response.stop_reason in FAILED_STOPS else _parse(response.content)
        usable = _usable(questions, answers)
        return ClassifyResult(
            tuple(usable[q.key] for q in questions if q.key in usable),
            tuple(q.key for q in questions if q.key not in usable),
            usage,
        )

    def _ask(self, client: anthropic.Anthropic, questions: Sequence[LineQuestion]) -> Any:
        # `messages.create` with a raw schema, not `messages.parse`: `parse` raises on an answer
        # cut off at `max_tokens`, and the tokens it used would be lost to the budget.
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": prompt.INSTRUCTIONS,
            "messages": [{"role": "user", "content": _user_message(questions)}],
            "output_config": {
                "effort": EFFORT,
                "format": {
                    "type": "json_schema",
                    "schema": anthropic.transform_schema(BatchAnswer),
                },
            },
        }
        try:
            if self.model in FALLBACK_MODELS:
                return client.beta.messages.create(
                    **request, betas=[FALLBACK_BETA], fallbacks="default"
                )
            return client.messages.create(**request)
        except anthropic.APIStatusError as error:
            raise ClassifierError(
                f"Claude returned {error.status_code}: {error.message}"
            ) from error
        except anthropic.APIConnectionError as error:
            raise ClassifierError(f"Connection to Claude failed: {error.message}") from error


def _user_message(questions: Sequence[LineQuestion]) -> str:
    head = (
        f"Place each of the {len(questions)} lines below. Give one answer per line, with the "
        "line's number as `index`; `codes` holds the chosen row's code, several codes for a line "
        "that merges rows, or nothing for none; `confidence` is between 0 and 1."
    )
    return "\n\n".join([head, *(f"Line {n}\n{prompt.render(q)}" for n, q in enumerate(questions))])


def _parse(content: Sequence[Any]) -> list[Answer]:
    """The answers of the response's text; none when it is not the schema."""
    text = next((block.text for block in content if block.type == "text"), "")
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
