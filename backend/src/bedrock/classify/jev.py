"""The Jev classifier of TypeSafe (docs/erd/face-tree.md "Jev adapter"): one request per line.
Touches the network; called only from a user-started run. Jev is in early access: the request
and response shapes are those of docs.typesafe.ai ("Quick start", "Choice"), read 2026-11-16."""

import json
import math
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from bedrock.classify import prompt
from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable
from bedrock.classify.types import ClassifyResult, LineAnswer, LineQuestion, Usage

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_SECONDS = 30
RETRY_DELAYS = (1, 3)  # seconds before the second and the third attempt
CHARS_PER_TOKEN = 3
NONE_TEXT = "None of these rows: the line stays in the block's Other row"
COMBINED_TEXT = "The line merges two or more of the listed rows into one amount"
# A line is combined when Jev says so and at least two rows are each this likely
COMBINED_NOUL = 0.5
COMBINED_PROBABILITY = 0.25


class JevClassifier:
    name = f"jev:{MODEL}"
    batch_size = 1

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`client` and `sleep` are for tests. Without a key the classifier can estimate but not
        ask (`classify` raises `ClassifierUnavailable`)."""
        self._api_key = api_key
        self._client = client or httpx.Client()
        self._sleep = sleep

    def estimate(self, questions: Sequence[LineQuestion]) -> Usage:
        return Usage(sum(math.ceil(len(_body(q)) / CHARS_PER_TOKEN) for q in questions), 0)

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        if len(questions) > self.batch_size:
            raise ValueError(f"classify takes at most {self.batch_size} question")
        if not questions:
            return ClassifyResult((), (), Usage(0, 0))
        if not self._api_key:
            raise ClassifierUnavailable(f"{self.name} has no API key")
        question = questions[0]
        payload = self._post(_body(question))
        try:
            row = payload["answers"]["row"]
            choice = str(row["choice"])
            confidence = float(row["confidence"])
            probabilities = {str(k): float(v) for k, v in row["probabilities"].items()}
            noul = float(payload["answers"]["combined"]["noul"])
            usage = Usage(
                int(payload["usage"]["input_tokens"]), int(payload["usage"]["output_tokens"])
            )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ClassifierError(f"Jev answered in an unknown shape: {error!r}") from error
        answer = _answer(question, choice, confidence, probabilities, noul)
        if answer is None:
            return ClassifyResult((), (question.key,), usage)
        return ClassifyResult((answer,), (), usage)

    def _post(self, body: str) -> Any:
        """The response's JSON. A 429 or 5xx is tried again after each of `RETRY_DELAYS`."""
        for delay in (*RETRY_DELAYS, None):
            try:
                response = self._client.post(
                    URL,
                    content=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as error:
                raise ClassifierError(f"Connection to Jev failed: {error}") from error
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and delay is not None:
                self._sleep(delay)
                continue
            if response.status_code >= 400:
                raise ClassifierError(f"Jev returned {response.status_code}")
            try:
                return response.json()
            except ValueError as error:
                raise ClassifierError("Jev answered in an unknown shape: not JSON") from error
        raise AssertionError("unreachable: the last attempt returns or raises")


def _body(question: LineQuestion) -> str:
    criteria = {c.code: c.label for c in question.candidates}
    criteria[prompt.NONE] = NONE_TEXT
    return json.dumps(
        {
            "state": prompt.render(question),
            "model": MODEL,
            "questions": {
                "row": {
                    "type": "choice",
                    "instructions": prompt.INSTRUCTIONS,
                    "criteria": criteria,
                },
                "combined": {"type": "noul", "instructions": COMBINED_TEXT},
            },
        }
    )


def _answer(
    question: LineQuestion,
    choice: str,
    confidence: float,
    probabilities: dict[str, float],
    noul: float,
) -> LineAnswer | None:
    """None when the choice is not one of the line's candidates (nor `none`)."""
    codes = [c.code for c in question.candidates]
    likely = [c for c in codes if probabilities.get(c, 0.0) >= COMBINED_PROBABILITY]
    if noul >= COMBINED_NOUL and len(likely) >= 2:
        return LineAnswer(
            question.key, tuple(likely), _clamp(min(noul, sum(probabilities[c] for c in likely)))
        )
    if choice == prompt.NONE:
        return LineAnswer(question.key, (), _clamp(confidence))
    if choice not in codes:
        return None
    return LineAnswer(question.key, (choice,), _clamp(confidence))


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
