"""The classifiers reached through OpenRouter (docs/erd/face-tree.md "OpenRouter adapter"): one
chat completion per batch, the answer constrained to a strict JSON schema. Touches the network;
called only from a user-started run. The shapes are those of openrouter.ai/docs ("API reference
overview", "Structured outputs", "Errors and debugging"), read 2026-11-17."""

import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from bedrock.classify import batch, prompt
from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable
from bedrock.classify.types import ClassifyResult, LineQuestion, Usage

URL = "https://openrouter.ai/api/v1/chat/completions"
# Lines per request: 10 unless listed. The free tier allows 50 requests a day, so the free
# model asks a company's lines in one request (the user's choice of 2026-11-17).
BATCH_SIZES = {"nvidia/nemotron-3.5-super-vl:free": 100}
DEFAULT_BATCH_SIZE = 10
# `data_collection` per model: deny unless listed. A free variant has only endpoints that train
# on prompts, so `deny` leaves it none; the user allowed it for this model (2026-11-17).
DATA_COLLECTION = {"nvidia/nemotron-3.5-super-vl:free": "allow"}
DEFAULT_DATA_COLLECTION = "deny"
# The output cap: four times the estimated answer of the batch (room for reasoning), at least
# MIN_MAX_TOKENS. Twice was too tight: Nemotron used 6,616 of 6,680 on 49 AAPL lines
# (2026-11-17). The budgets count the tokens used, not the cap.
MIN_MAX_TOKENS = 4000
REASONING_FACTOR = 4
TIMEOUT_SECONDS = 60
RETRY_DELAYS = (1, 3)  # seconds before the second and the third attempt
RETRY_STATUSES = frozenset({408, 429})  # and every 5xx
# A normalized finish reason that leaves the text unusable: cut off, filtered, failed
FAILED_FINISHES = frozenset({"length", "content_filter", "error"})


class OpenRouterClassifier:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`model` is OpenRouter's id (`vendor/model`). `client` and `sleep` are for tests.
        Without a key the classifier can estimate but not ask (`classify` raises
        `ClassifierUnavailable`)."""
        self.model = model
        self.name = f"openrouter:{model}"
        self.batch_size = BATCH_SIZES.get(model, DEFAULT_BATCH_SIZE)
        self._api_key = api_key
        self._client = client or httpx.Client()
        self._sleep = sleep

    def estimate(self, questions: Sequence[LineQuestion]) -> Usage:
        return batch.estimate(questions, self.batch_size)

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        if len(questions) > self.batch_size:
            raise ValueError(f"classify takes at most {self.batch_size} questions")
        if not questions:
            return ClassifyResult((), (), Usage(0, 0))
        if not self._api_key:
            raise ClassifierUnavailable(f"{self.name} has no API key")
        payload = self._post(self._request(questions))
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            # a failure reported after the request was accepted (HTTP 200)
            raise ClassifierError(f"OpenRouter failed: {payload['error'].get('message')}")
        try:
            choice = payload["choices"][0]
            finish = choice["finish_reason"]
            content = choice["message"]["content"]
            usage = Usage(
                int(payload["usage"]["prompt_tokens"]),
                int(payload["usage"]["completion_tokens"]),
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ClassifierError(f"OpenRouter answered in an unknown shape: {error!r}") from error
        text = None if finish in FAILED_FINISHES else str(content or "")
        return batch.result(questions, text, usage)

    def _request(self, questions: Sequence[LineQuestion]) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": max(
                MIN_MAX_TOKENS,
                REASONING_FACTOR * batch.estimate(questions, self.batch_size).output_tokens,
            ),
            "messages": [
                {"role": "system", "content": prompt.INSTRUCTIONS},
                {"role": "user", "content": batch.user_message(questions)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "batch_answer", "strict": True, "schema": batch.SCHEMA},
            },
            "reasoning": {"effort": "low"},
            # Only endpoints that honour every parameter (the schema above); unless the model is
            # listed in DATA_COLLECTION, none that may store the request.
            "provider": {
                "require_parameters": True,
                "data_collection": DATA_COLLECTION.get(self.model, DEFAULT_DATA_COLLECTION),
            },
        }

    def _post(self, body: dict[str, Any]) -> Any:
        """The response's JSON. A 408, 429 or 5xx is tried again after each of `RETRY_DELAYS`."""
        for delay in (*RETRY_DELAYS, None):
            try:
                response = self._client.post(
                    URL,
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as error:
                raise ClassifierError(f"Connection to OpenRouter failed: {error}") from error
            status = response.status_code
            if (status in RETRY_STATUSES or status >= 500) and delay is not None:
                self._sleep(delay)
                continue
            if status >= 400:
                raise ClassifierError(_error_text(response))
            try:
                return response.json()
            except ValueError as error:
                raise ClassifierError(
                    "OpenRouter answered in an unknown shape: not JSON"
                ) from error
        raise AssertionError("unreachable: the last attempt returns or raises")


def _error_text(response: httpx.Response) -> str:
    """`OpenRouter returned <status>`, with OpenRouter's `error.message` when the body has one."""
    head = f"OpenRouter returned {response.status_code}"
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return head
    return f"{head}: {message}" if isinstance(message, str) and message else head
