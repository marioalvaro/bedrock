"""The Claude classifiers (docs/erd/face-tree.md "Claude adapter"): one Messages request per
batch, the answer constrained to a JSON schema. Touches the network; called only from a
user-started run."""

from collections.abc import Sequence
from typing import Any

import anthropic

from bedrock.classify import batch, prompt
from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable
from bedrock.classify.types import ClassifyResult, LineQuestion, Usage

MAX_TOKENS = 4000
EFFORT = "low"
# Claude Sonnet 5.5 may decline a request (`stop_reason` "refusal"); the server-side fallback
# re-runs it on the model the API picks for the refusal's category. Haiku 5.5 has none.
FALLBACK_MODELS = frozenset({"claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FAILED_STOPS = frozenset({"refusal", "max_tokens"})


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
        return batch.estimate(questions, self.batch_size)

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        if len(questions) > self.batch_size:
            raise ValueError(f"classify takes at most {self.batch_size} questions")
        if not questions:
            return ClassifyResult((), (), Usage(0, 0))
        if self._client is None:
            raise ClassifierUnavailable(f"{self.name} has no API key")
        response = self._ask(self._client, questions)
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        text = None if response.stop_reason in FAILED_STOPS else _text(response.content)
        return batch.result(questions, text, usage)

    def _ask(self, client: anthropic.Anthropic, questions: Sequence[LineQuestion]) -> Any:
        # `messages.create` with a raw schema, not `messages.parse`: `parse` raises on an answer
        # cut off at `max_tokens`, and the tokens it used would be lost to the budget.
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": prompt.INSTRUCTIONS,
            "messages": [{"role": "user", "content": batch.user_message(questions)}],
            "output_config": {
                "effort": EFFORT,
                "format": {
                    "type": "json_schema",
                    "schema": anthropic.transform_schema(batch.BatchAnswer),
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


def _text(content: Sequence[Any]) -> str:
    """The response's first text block; empty when it has none."""
    return next((block.text for block in content if block.type == "text"), "")
