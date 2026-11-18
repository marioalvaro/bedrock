"""The OpenRouter adapter (M7d S4b, docs/erd/face-tree.md "OpenRouter adapter"), on an `httpx`
mock transport: no request leaves the process. The shapes are those of openrouter.ai/docs
("API reference overview", "Structured outputs", "Errors and debugging"), read 2026-11-17."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from bedrock.classify import batch, prompt
from bedrock.classify.openrouter import OpenRouterClassifier
from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable, LineClassifier
from bedrock.classify.types import LineAnswer, Usage
from tests.classify_data import question

MODEL = "openai/gpt-6-luna"
BATCH = [question("A"), question("B"), question("C")]
Reply = dict[str, Any] | int | Callable[[httpx.Request], httpx.Response]


def completion(
    answers: list[tuple[int, list[str], float]] | str | None,
    *,
    finish_reason: str = "stop",
    usage: tuple[int, int] = (900, 120),
) -> dict[str, Any]:
    content = (
        answers
        if answers is None or isinstance(answers, str)
        else json.dumps(
            {"answers": [{"index": i, "codes": c, "confidence": p} for i, c, p in answers]}
        )
    )
    return {
        "id": "gen-test",
        "model": MODEL,
        "choices": [
            {
                "finish_reason": finish_reason,
                "native_finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": usage[0],
            "completion_tokens": usage[1],
            "total_tokens": sum(usage),
        },
    }


class Provider:
    """Answers request n with `replies[n]` (the last one from then on) and keeps the requests.
    An int is that error status with OpenRouter's error body."""

    def __init__(self, *replies: Reply) -> None:
        self.replies = replies
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        current = self.replies[min(len(self.requests), len(self.replies) - 1)]
        self.requests.append(request)
        if isinstance(current, int):
            return httpx.Response(
                current, json={"error": {"code": current, "message": f"failure {current}"}}
            )
        if callable(current):
            return current(request)
        return httpx.Response(200, json=current)

    @property
    def body(self) -> dict[str, Any]:
        (request,) = self.requests
        return json.loads(request.content)  # type: ignore[no-any-return]


def classifier(provider: Provider, sleeps: list[float] | None = None) -> OpenRouterClassifier:
    return OpenRouterClassifier(
        MODEL,
        api_key="or-key",
        client=httpx.Client(transport=httpx.MockTransport(provider)),
        sleep=(sleeps if sleeps is not None else []).append,
    )


# --- the request ------------------------------------------------------------------------------


def test_one_chat_completion_per_batch_with_the_bearer_key() -> None:
    provider = Provider(completion([]))

    classifier(provider).classify(BATCH)

    (request,) = provider.requests
    assert request.method == "POST"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer or-key"
    assert request.headers["Content-Type"] == "application/json"


def test_the_body_is_the_erd_design() -> None:
    provider = Provider(completion([]))

    classifier(provider).classify(BATCH)

    assert provider.body == {
        "model": MODEL,
        "max_tokens": 4000,
        "messages": [
            {"role": "system", "content": prompt.INSTRUCTIONS},
            {"role": "user", "content": batch.user_message(BATCH)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "batch_answer", "strict": True, "schema": batch.SCHEMA},
        },
        "reasoning": {"effort": "low"},
        "provider": {"require_parameters": True, "data_collection": "deny"},
    }


# --- the answer -------------------------------------------------------------------------------


def test_answers_map_to_the_questions_by_index_with_the_usage() -> None:
    provider = Provider(
        completion([(2, ["inventory"], 0.8), (0, ["cash"], 0.95), (1, [], 0.6)], usage=(700, 90))
    )

    result = classifier(provider).classify(BATCH)

    assert result.answers == (
        LineAnswer("BS|ext|A", ("cash",), 0.95),
        LineAnswer("BS|ext|B", (), 0.6),
        LineAnswer("BS|ext|C", ("inventory",), 0.8),
    )
    assert result.failed == ()
    assert result.usage == Usage(700, 90)


def test_a_code_outside_the_candidates_fails_that_line_only() -> None:
    provider = Provider(completion([(0, ["goodwill"], 0.9), (1, ["cash"], 0.9)]))

    result = classifier(provider).classify(BATCH[:2])

    assert result.answers == (LineAnswer("BS|ext|B", ("cash",), 0.9),)
    assert result.failed == ("BS|ext|A",)


@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "error"])
def test_a_cut_off_filtered_or_failed_answer_fails_every_line_and_keeps_the_usage(
    finish_reason: str,
) -> None:
    # A complete-looking text is not used either: the model did not finish it.
    provider = Provider(completion([(0, ["cash"], 0.9)], finish_reason=finish_reason))

    result = classifier(provider).classify(BATCH)

    assert result.answers == ()
    assert result.failed == ("BS|ext|A", "BS|ext|B", "BS|ext|C")
    assert result.usage == Usage(900, 120)


@pytest.mark.parametrize(
    ("finish_reason", "reason"),
    [
        ("length", "the answer was cut off at 4,000 output tokens"),
        ("content_filter", "the provider filtered the answer"),
        ("error", "the provider reported an error in the answer"),
    ],
)
def test_an_unusable_answer_says_why(finish_reason: str, reason: str) -> None:
    provider = Provider(completion([(0, ["cash"], 0.9)], finish_reason=finish_reason))

    assert classifier(provider).classify(BATCH).reason == reason


def test_a_cut_off_answer_of_the_free_model_names_its_cap() -> None:
    provider = Provider(completion(None, finish_reason="length", usage=(3600, 32000)))

    result = nemotron(provider).classify(BATCH)

    assert result.reason == "the answer was cut off at 32,000 output tokens"


def test_a_usable_answer_gives_no_reason() -> None:
    provider = Provider(completion([(0, ["goodwill"], 0.9), (1, ["cash"], 0.9)]))

    assert classifier(provider).classify(BATCH[:2]).reason is None


@pytest.mark.parametrize("content", [None, "", "not json", '{"answers": "x"}'])
def test_a_content_that_is_not_the_schema_fails_every_line(content: str | None) -> None:
    provider = Provider(completion(content))

    result = classifier(provider).classify(BATCH)

    assert result.answers == ()
    assert result.failed == ("BS|ext|A", "BS|ext|B", "BS|ext|C")
    assert result.usage == Usage(900, 120)


@pytest.mark.parametrize(
    "reply",
    [
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]},
        {"id": "gen-test"},
        "not json",
    ],
)
def test_a_response_of_an_unknown_shape_is_a_classifier_error(reply: dict[str, Any] | str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if isinstance(reply, str):
            return httpx.Response(200, content=reply.encode())
        return httpx.Response(200, json=reply)

    with pytest.raises(ClassifierError, match="OpenRouter answered in an unknown shape"):
        classifier(Provider(respond)).classify(BATCH)


def test_an_error_in_a_200_body_is_a_classifier_error_with_openrouters_message() -> None:
    # OpenRouter reports a failure after the request was accepted in the body's `error`.
    provider = Provider({"error": {"code": 502, "message": "upstream model failed"}})

    with pytest.raises(ClassifierError, match=r"^OpenRouter failed: upstream model failed$"):
        classifier(provider).classify(BATCH)


# --- errors and retries -----------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 402, 403])
def test_an_error_status_is_a_classifier_error_with_its_message_and_no_retry(status: int) -> None:
    provider = Provider(status)
    sleeps: list[float] = []

    with pytest.raises(ClassifierError, match=f"OpenRouter returned {status}: failure {status}"):
        classifier(provider, sleeps).classify(BATCH)

    assert len(provider.requests) == 1
    assert sleeps == []


def test_an_error_body_that_is_not_openrouters_still_names_the_status() -> None:
    provider = Provider(lambda request: httpx.Response(401, content=b"<html>nope</html>"))

    with pytest.raises(ClassifierError, match=r"^OpenRouter returned 401$"):
        classifier(provider).classify(BATCH)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
def test_a_busy_or_failing_provider_is_tried_again_after_1_and_3_seconds(status: int) -> None:
    provider = Provider(status, status, completion([(0, ["cash"], 0.9)]))
    sleeps: list[float] = []

    result = classifier(provider, sleeps).classify(BATCH[:1])

    assert result.answers == (LineAnswer("BS|ext|A", ("cash",), 0.9),)
    assert len(provider.requests) == 3
    assert sleeps == [1, 3]


def test_a_third_failure_is_a_classifier_error() -> None:
    provider = Provider(503)
    sleeps: list[float] = []

    with pytest.raises(ClassifierError, match="OpenRouter returned 503"):
        classifier(provider, sleeps).classify(BATCH)

    assert len(provider.requests) == 3
    assert sleeps == [1, 3]


def test_no_connection_is_a_classifier_error_and_is_not_retried() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = Provider(refuse)
    sleeps: list[float] = []

    with pytest.raises(ClassifierError, match="Connection to OpenRouter failed"):
        classifier(provider, sleeps).classify(BATCH)

    assert len(provider.requests) == 1
    assert sleeps == []


# --- batches, estimate, no key ----------------------------------------------------------------


def test_no_question_makes_no_request() -> None:
    provider = Provider(completion([]))

    result = classifier(provider).classify([])

    assert (result.answers, result.failed, result.usage) == ((), (), Usage(0, 0))
    assert provider.requests == []


def test_more_than_a_batch_is_refused_before_any_request() -> None:
    provider = Provider(completion([]))

    with pytest.raises(ValueError):
        classifier(provider).classify([question(f"Q{n}") for n in range(11)])

    assert provider.requests == []


def test_the_estimate_is_the_shared_batch_estimate_in_requests_of_ten() -> None:
    questions = [question(f"Q{n}") for n in range(12)]

    assert classifier(Provider(completion([]))).estimate(questions) == batch.estimate(questions, 10)


def test_name_and_batch_size() -> None:
    built = OpenRouterClassifier(MODEL)

    assert built.name == "openrouter:openai/gpt-6-luna"
    assert built.batch_size == 10
    checked: LineClassifier = built
    assert checked.name == built.name


def test_without_a_key_it_estimates_but_does_not_ask() -> None:
    provider = Provider(completion([]))
    keyless = OpenRouterClassifier(
        MODEL, client=httpx.Client(transport=httpx.MockTransport(provider))
    )

    assert keyless.estimate(BATCH).input_tokens > 0
    with pytest.raises(ClassifierUnavailable, match="openrouter:openai/gpt-6-luna"):
        keyless.classify(BATCH)
    assert provider.requests == []


# --- the free Nemotron model: 100 lines per request (S4b, the user's choice of 2026-11-17) -------

NEMOTRON = "nvidia/nemotron-3.5-super-vl:free"


def nemotron(provider: Provider) -> OpenRouterClassifier:
    return OpenRouterClassifier(
        NEMOTRON,
        api_key="or-key",
        client=httpx.Client(transport=httpx.MockTransport(provider)),
        sleep=[].append,
    )


def test_the_free_nemotron_model_asks_100_lines_per_request_and_others_10() -> None:
    assert OpenRouterClassifier(NEMOTRON).batch_size == 100
    assert OpenRouterClassifier(NEMOTRON).name == "openrouter:nvidia/nemotron-3.5-super-vl:free"
    assert OpenRouterClassifier(MODEL).batch_size == 10


def test_a_batch_of_100_is_one_request_and_101_is_refused() -> None:
    provider = Provider(completion([]))
    hundred = [question(f"Q{n}") for n in range(100)]

    nemotron(provider).classify(hundred)

    assert len(provider.requests) == 1
    assert provider.body["messages"][1]["content"] == batch.user_message(hundred)
    with pytest.raises(ValueError):
        nemotron(provider).classify([*hundred, question("Q100")])
    assert len(provider.requests) == 1


def test_the_free_model_has_a_fixed_output_cap_of_32000() -> None:
    # The 4x rule left Nemotron 4,480 tokens for 12 RDDT lines and 19,120 for 73 LMT lines: it
    # spent every one (finish `length`) and answered no line (2026-11-17). It is free, so it gets
    # a fixed cap; the budgets still count the tokens it uses.
    for lines in (1, 12, 73, 100):
        provider = Provider(completion([]))
        nemotron(provider).classify([question(f"Q{n}") for n in range(lines)])
        assert provider.body["max_tokens"] == 32000, lines


def test_a_paid_model_keeps_four_times_the_estimated_answer_at_least_4000() -> None:
    # 400 + 60 per line, times four; a batch of 10 is 4000.
    for lines in (1, 10):
        provider = Provider(completion([]))
        classifier(provider).classify([question(f"Q{n}") for n in range(lines)])
        assert provider.body["max_tokens"] == 4000, lines


def test_the_free_model_allows_data_collection_and_the_others_deny_it() -> None:
    # Free variants train on prompts: no endpoint passes `deny` (a 404, seen 2026-11-17). The
    # user allowed it for this model only.
    free, paid = Provider(completion([])), Provider(completion([]))

    nemotron(free).classify(BATCH)
    classifier(paid).classify(BATCH)

    assert free.body["model"] == NEMOTRON
    assert free.body["provider"] == {"require_parameters": True, "data_collection": "allow"}
    assert paid.body["provider"] == {"require_parameters": True, "data_collection": "deny"}


def test_the_estimate_of_the_free_model_counts_requests_of_100() -> None:
    questions = [question(f"Q{n}") for n in range(150)]

    estimate = OpenRouterClassifier(NEMOTRON).estimate(questions)

    assert estimate == batch.estimate(questions, 100)
    assert estimate.output_tokens == 2 * 400 + 60 * 150
