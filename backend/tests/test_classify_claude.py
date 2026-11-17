"""The Claude adapter (M7d S2, docs/erd/face-tree.md "Claude adapter"), through the real SDK
client on a mock transport: no request leaves the process."""

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from bedrock.classify import prompt
from bedrock.classify.claude import ClaudeClassifier
from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable, LineClassifier
from bedrock.classify.types import LineAnswer, Usage
from tests.classify_data import question

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
Handler = Callable[[httpx2.Request], httpx2.Response]


def message(
    answers: list[dict[str, Any]] | str,
    *,
    stop_reason: str = "end_turn",
    usage: tuple[int, int] = (900, 120),
) -> dict[str, Any]:
    text = answers if isinstance(answers, str) else json.dumps({"answers": answers})
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": HAIKU,
        "content": [{"type": "text", "text": text}] if text else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


class Provider:
    """Answers every request with `reply` and keeps the requests."""

    def __init__(self, reply: dict[str, Any] | Handler) -> None:
        self.reply = reply
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if callable(self.reply):
            return self.reply(request)
        return httpx2.Response(200, json=self.reply)

    @property
    def body(self) -> dict[str, Any]:
        (request,) = self.requests
        return json.loads(request.content)  # type: ignore[no-any-return]


def classifier(provider: Provider, model: str = HAIKU) -> ClaudeClassifier:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(provider)),
    )
    return ClaudeClassifier(model, client=client)


def answer(index: int, codes: list[str], confidence: float = 0.9) -> dict[str, Any]:
    return {"index": index, "codes": codes, "confidence": confidence}


BATCH = [question("A"), question("B"), question("C")]


def test_one_request_per_batch_with_the_design_of_the_erd() -> None:
    provider = Provider(message([answer(0, ["cash"]), answer(1, []), answer(2, ["inventory"])]))

    classifier(provider).classify(BATCH)

    body = provider.body
    assert provider.requests[0].url.path == "/v1/messages"
    assert body["model"] == HAIKU
    assert body["max_tokens"] == 4000
    assert body["system"] == prompt.INSTRUCTIONS
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert [m["role"] for m in body["messages"]] == ["user"]


def test_the_user_message_holds_the_rendered_questions_numbered_from_zero() -> None:
    provider = Provider(message([]))

    classifier(provider).classify(BATCH)

    (user,) = provider.body["messages"]
    text = user["content"]
    for n, q in enumerate(BATCH):
        assert f"Line {n}\n{prompt.render(q)}" in text
    assert text.index("Line 0\n") < text.index("Line 1\n") < text.index("Line 2\n")
    assert "Line 3\n" not in text


def test_the_schema_asks_for_index_codes_and_confidence_per_answer() -> None:
    provider = Provider(message([]))

    classifier(provider).classify(BATCH)

    schema = provider.body["output_config"]["format"]["schema"]
    text = json.dumps(schema)
    assert set(schema["properties"]) == {"answers"}
    for field in ("index", "codes", "confidence"):
        assert f'"{field}"' in text


def test_answers_map_to_the_questions_by_index() -> None:
    provider = Provider(
        message([answer(2, ["inventory"], 0.8), answer(0, ["cash"], 0.95), answer(1, [], 0.6)])
    )

    result = classifier(provider).classify(BATCH)

    assert result.answers == (
        LineAnswer("BS|ext|A", ("cash",), 0.95),
        LineAnswer("BS|ext|B", (), 0.6),
        LineAnswer("BS|ext|C", ("inventory",), 0.8),
    )
    assert result.failed == ()
    assert result.usage == Usage(900, 120)


def test_two_codes_are_one_combined_line() -> None:
    provider = Provider(message([answer(0, ["cash", "inventory", "cash"], 0.7)]))

    result = classifier(provider).classify([question("A")])

    assert result.answers == (LineAnswer("BS|ext|A", ("cash", "inventory"), 0.7),)


def test_a_code_outside_the_candidates_fails_that_line_only() -> None:
    provider = Provider(
        message([answer(0, ["cash"]), answer(1, ["goodwill"]), answer(2, ["cash", "nope"])])
    )

    result = classifier(provider).classify(BATCH)

    assert [a.key for a in result.answers] == ["BS|ext|A"]
    assert result.failed == ("BS|ext|B", "BS|ext|C")


def test_a_duplicate_index_fails_that_line_only() -> None:
    provider = Provider(message([answer(0, ["cash"]), answer(0, []), answer(1, ["cash"])]))

    result = classifier(provider).classify(BATCH[:2])

    assert [a.key for a in result.answers] == ["BS|ext|B"]
    assert result.failed == ("BS|ext|A",)


def test_an_index_out_of_range_is_dropped_and_an_unanswered_line_fails() -> None:
    provider = Provider(message([answer(0, ["cash"]), answer(7, ["cash"]), answer(-1, [])]))

    result = classifier(provider).classify(BATCH[:2])

    assert [a.key for a in result.answers] == ["BS|ext|A"]
    assert result.failed == ("BS|ext|B",)


@pytest.mark.parametrize(("given", "kept"), [(1.7, 1.0), (-0.2, 0.0), (0.5, 0.5)])
def test_confidence_is_clamped(given: float, kept: float) -> None:
    provider = Provider(message([answer(0, ["cash"], given)]))

    result = classifier(provider).classify([question("A")])

    assert result.answers[0].confidence == kept


def test_a_refusal_fails_every_line_and_keeps_the_usage() -> None:
    provider = Provider(message("", stop_reason="refusal", usage=(500, 0)))

    result = classifier(provider).classify(BATCH)

    assert result.answers == ()
    assert result.failed == ("BS|ext|A", "BS|ext|B", "BS|ext|C")
    assert result.usage == Usage(500, 0)
    assert result.reason == "the model declined to answer"


def test_a_cut_off_answer_fails_every_line_and_keeps_the_usage() -> None:
    cut = '{"answers": [{"index": 0, "codes": ["cash"], "confidence": 0.9}, {"index": 1, "co'
    provider = Provider(message(cut, stop_reason="max_tokens", usage=(900, 4000)))

    result = classifier(provider).classify(BATCH)

    assert result.answers == ()
    assert result.failed == ("BS|ext|A", "BS|ext|B", "BS|ext|C")
    assert result.usage == Usage(900, 4000)
    assert result.reason == "the answer was cut off at 4,000 output tokens"


def test_a_complete_looking_answer_is_not_used_when_the_stop_reason_is_max_tokens() -> None:
    provider = Provider(message([answer(0, ["cash"])], stop_reason="max_tokens"))

    result = classifier(provider).classify([question("A")])

    assert result.answers == () and result.failed == ("BS|ext|A",)


@pytest.mark.parametrize("text", ["not json", '{"rows": []}', ""])
def test_an_answer_that_is_not_the_schema_fails_every_line(text: str) -> None:
    provider = Provider(message(text))

    result = classifier(provider).classify(BATCH[:2])

    assert result.answers == () and result.failed == ("BS|ext|A", "BS|ext|B")
    assert result.usage == Usage(900, 120)


def test_no_question_makes_no_request() -> None:
    provider = Provider(message([]))

    result = classifier(provider).classify([])

    assert provider.requests == []
    assert (result.answers, result.failed, result.usage) == ((), (), Usage(0, 0))


def test_more_than_a_batch_is_refused_before_any_request() -> None:
    provider = Provider(message([]))
    eleven = [question(f"Q{n}") for n in range(11)]

    with pytest.raises(ValueError, match="at most 10"):
        classifier(provider).classify(eleven)
    assert provider.requests == []


def test_haiku_sends_no_fallback() -> None:
    provider = Provider(message([]))

    classifier(provider, HAIKU).classify(BATCH)

    assert "fallbacks" not in provider.body
    assert FALLBACK_BETA not in provider.requests[0].headers.get("anthropic-beta", "")


def test_sonnet_sends_the_server_side_refusal_fallback() -> None:
    provider = Provider(message([answer(0, ["cash"])]))

    result = classifier(provider, SONNET).classify([question("A")])

    body = provider.body
    assert body["model"] == SONNET
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in provider.requests[0].headers["anthropic-beta"]
    assert body["output_config"]["effort"] == "low"
    assert body["system"] == prompt.INSTRUCTIONS
    assert result.answers == (LineAnswer("BS|ext|A", ("cash",), 0.9),)


@pytest.mark.parametrize("status", [400, 401, 429, 500, 529])
def test_an_error_status_is_a_classifier_error(status: int) -> None:
    error = {"type": "error", "error": {"type": "api_error", "message": "it broke"}}
    provider = Provider(lambda request: httpx2.Response(status, json=error))

    with pytest.raises(ClassifierError, match=str(status)):
        classifier(provider).classify(BATCH)


def test_no_connection_is_a_classifier_error() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(ClassifierError, match="[Cc]onnection"):
        classifier(Provider(refuse)).classify(BATCH)


def test_the_estimate_is_characters_over_three_and_a_fixed_output() -> None:
    provider = Provider(message([]))
    claude = classifier(provider)

    estimate = claude.estimate(BATCH)
    claude.classify(BATCH)

    sent = len(prompt.INSTRUCTIONS) + len(provider.body["messages"][0]["content"])
    assert estimate == Usage(-(-sent // 3), 400 + 60 * 3)
    assert len(provider.requests) == 1  # the estimate asked nothing


def test_the_estimate_counts_one_request_per_batch_of_ten() -> None:
    claude = classifier(Provider(message([])))
    many = [question(f"Q{n}") for n in range(23)]

    estimate = claude.estimate(many)

    parts = [claude.estimate(many[:10]), claude.estimate(many[10:20]), claude.estimate(many[20:])]
    assert estimate.input_tokens == sum(p.input_tokens for p in parts)
    assert estimate.output_tokens == 3 * 400 + 23 * 60
    assert claude.estimate([]) == Usage(0, 0)


def test_names_and_batch_size() -> None:
    haiku: LineClassifier = classifier(Provider(message([])), HAIKU)
    sonnet = classifier(Provider(message([])), SONNET)

    assert (haiku.name, haiku.batch_size) == ("claude:claude-haiku-5-5", 10)
    assert sonnet.name == "claude:claude-sonnet-5-5"


def test_without_a_key_or_a_client_it_estimates_but_does_not_ask() -> None:
    offline = ClaudeClassifier(HAIKU)

    assert offline.estimate(BATCH).input_tokens > 0
    with pytest.raises(ClassifierUnavailable):
        offline.classify(BATCH)


def test_a_key_builds_the_sdk_client(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []

    class Recorder:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", Recorder)

    ClaudeClassifier(HAIKU, api_key="key-a")

    assert built == [{"api_key": "key-a"}]
