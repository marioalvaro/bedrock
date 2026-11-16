"""The Jev adapter (M7d S2, docs/erd/face-tree.md "Jev adapter"), on an `httpx` mock transport:
no request leaves the process. The shapes are those of docs.typesafe.ai, read 2026-11-16."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from bedrock.classify import prompt
from bedrock.classify.jev import JevClassifier
from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable, LineClassifier
from bedrock.classify.types import LineAnswer, Usage
from tests.classify_data import question

Q = question("A")  # candidates: cash, inventory


def reply(
    choice: str = "cash",
    confidence: float = 0.9,
    probabilities: dict[str, float] | None = None,
    noul: float = 0.1,
    usage: tuple[int, int] = (700, 0),
) -> dict[str, Any]:
    return {
        "answers": {
            "row": {
                "choice": choice,
                "confidence": confidence,
                "probabilities": probabilities or {choice: confidence},
            },
            "combined": {"noul": noul},
        },
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


class Provider:
    """Answers request n with `replies[n]` (the last one from then on) and keeps the requests."""

    def __init__(self, *replies: dict[str, Any] | int | Callable[[httpx.Request], httpx.Response]):
        self.replies = replies
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        current = self.replies[min(len(self.requests), len(self.replies) - 1)]
        self.requests.append(request)
        if isinstance(current, int):
            return httpx.Response(current, json={"error": "it broke"})
        if callable(current):
            return current(request)
        return httpx.Response(200, json=current)


def classifier(provider: Provider, sleeps: list[float] | None = None) -> JevClassifier:
    return JevClassifier(
        api_key="jev-key",
        client=httpx.Client(transport=httpx.MockTransport(provider)),
        sleep=(sleeps if sleeps is not None else []).append,
    )


def test_the_request_is_the_erd_body_with_the_bearer_key() -> None:
    provider = Provider(reply())

    classifier(provider).classify([Q])

    (request,) = provider.requests
    assert request.method == "POST"
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["Authorization"] == "Bearer jev-key"
    assert json.loads(request.content) == {
        "state": prompt.render(Q),
        "model": "jev-latest",
        "questions": {
            "row": {
                "type": "choice",
                "instructions": prompt.INSTRUCTIONS,
                "criteria": {
                    "cash": "Cash",
                    "inventory": "Inventory",
                    "none": "None of these rows: the line stays in the block's Other row",
                },
            },
            "combined": {
                "type": "noul",
                "instructions": "The line merges two or more of the listed rows into one amount",
            },
        },
    }


def test_a_single_answer_is_the_choice_with_its_confidence() -> None:
    result = classifier(Provider(reply("inventory", 0.83))).classify([Q])

    assert result.answers == (LineAnswer("BS|ext|A", ("inventory",), 0.83),)
    assert result.failed == ()
    assert result.usage == Usage(700, 0)


def test_none_is_no_code() -> None:
    result = classifier(Provider(reply("none", 0.7))).classify([Q])

    assert result.answers == (LineAnswer("BS|ext|A", (), 0.7),)


def test_a_combined_answer_takes_the_likely_rows_in_candidate_order() -> None:
    probabilities = {"inventory": 0.45, "cash": 0.4, "none": 0.15}
    provider = Provider(reply("inventory", 0.45, probabilities, noul=0.9))

    result = classifier(provider).classify([Q])

    (answer,) = result.answers
    assert answer.codes == ("cash", "inventory")
    assert answer.confidence == pytest.approx(0.85)  # the smaller of 0.9 and 0.45 + 0.4


def test_a_combined_answer_is_capped_by_the_noul() -> None:
    probabilities = {"inventory": 0.5, "cash": 0.5}
    provider = Provider(reply("cash", 0.5, probabilities, noul=0.6))

    (answer,) = classifier(provider).classify([Q]).answers

    assert (answer.codes, answer.confidence) == (("cash", "inventory"), 0.6)


@pytest.mark.parametrize(
    ("noul", "probabilities"),
    [
        (0.49, {"cash": 0.5, "inventory": 0.5}),  # not said to be combined
        (0.9, {"cash": 0.76, "inventory": 0.24}),  # one likely row only
        (0.9, {"cash": 0.5, "none": 0.5}),  # `none` is not a row
    ],
)
def test_otherwise_the_answer_is_single(noul: float, probabilities: dict[str, float]) -> None:
    provider = Provider(reply("cash", 0.5, probabilities, noul=noul))

    assert classifier(provider).classify([Q]).answers == (LineAnswer("BS|ext|A", ("cash",), 0.5),)


def test_the_combined_thresholds_are_inclusive() -> None:
    provider = Provider(reply("cash", 0.5, {"cash": 0.25, "inventory": 0.25}, noul=0.5))

    (answer,) = classifier(provider).classify([Q]).answers

    assert (answer.codes, answer.confidence) == (("cash", "inventory"), 0.5)


def test_a_choice_outside_the_candidates_fails_the_line() -> None:
    result = classifier(Provider(reply("goodwill", 0.9))).classify([Q])

    assert result.answers == ()
    assert result.failed == ("BS|ext|A",)
    assert result.usage == Usage(700, 0)


@pytest.mark.parametrize(("given", "kept"), [(1.4, 1.0), (-0.1, 0.0)])
def test_confidence_is_clamped(given: float, kept: float) -> None:
    (answer,) = classifier(Provider(reply("cash", given))).classify([Q]).answers

    assert answer.confidence == kept


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_429_or_5xx_is_retried_after_one_and_three_seconds(status: int) -> None:
    provider, sleeps = Provider(status, status, reply()), []

    result = classifier(provider, sleeps).classify([Q])

    assert len(provider.requests) == 3
    assert sleeps == [1, 3]
    assert result.answers == (LineAnswer("BS|ext|A", ("cash",), 0.9),)


def test_a_third_failure_is_a_classifier_error() -> None:
    provider, sleeps = Provider(503), []

    with pytest.raises(ClassifierError, match="503"):
        classifier(provider, sleeps).classify([Q])
    assert len(provider.requests) == 3
    assert sleeps == [1, 3]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_another_error_status_is_a_classifier_error_at_once(status: int) -> None:
    provider, sleeps = Provider(status), []

    with pytest.raises(ClassifierError, match=str(status)):
        classifier(provider, sleeps).classify([Q])
    assert len(provider.requests) == 1
    assert sleeps == []


def test_no_connection_is_a_classifier_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(ClassifierError, match="no route"):
        classifier(Provider(refuse)).classify([Q])


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"answers": {"row": {"choice": "cash"}}, "usage": {"input_tokens": 1, "output_tokens": 0}},
        {"answers": reply()["answers"]},
        {"answers": [], "usage": {}},
    ],
)
def test_a_response_of_another_shape_is_a_classifier_error(body: dict[str, Any]) -> None:
    with pytest.raises(ClassifierError, match="shape"):
        classifier(Provider(body)).classify([Q])


def test_a_response_that_is_not_json_is_a_classifier_error() -> None:
    provider = Provider(lambda request: httpx.Response(200, text="<html>"))

    with pytest.raises(ClassifierError, match="shape"):
        classifier(provider).classify([Q])


def test_the_request_times_out_after_thirty_seconds() -> None:
    def check(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"] == {
            "connect": 30,
            "read": 30,
            "write": 30,
            "pool": 30,
        }
        return httpx.Response(200, json=reply())

    assert classifier(Provider(check)).classify([Q]).failed == ()


def test_the_estimate_is_the_request_body_over_three_and_no_output() -> None:
    provider = Provider(reply())
    jev = classifier(provider)
    other = question("B", label="A much longer label than the first question has")

    estimates = (jev.estimate([Q]), jev.estimate([other]), jev.estimate([Q, other]))
    assert provider.requests == []  # an estimate asks nothing
    jev.classify([Q])
    jev.classify([other])

    first, second = (-(-len(r.content.decode()) // 3) for r in provider.requests)
    assert estimates == (Usage(first, 0), Usage(second, 0), Usage(first + second, 0))
    assert jev.estimate([]) == Usage(0, 0)


def test_one_question_per_request() -> None:
    provider = Provider(reply())
    jev = classifier(provider)

    with pytest.raises(ValueError, match="at most 1"):
        jev.classify([Q, question("B")])
    assert provider.requests == []
    assert jev.classify([]) == jev.classify([])  # nothing asked, nothing answered
    assert provider.requests == []


def test_name_and_batch_size() -> None:
    jev: LineClassifier = classifier(Provider(reply()))

    assert (jev.name, jev.batch_size) == ("jev:jev-latest", 1)


def test_without_a_key_it_estimates_but_does_not_ask() -> None:
    provider = Provider(reply())
    offline = JevClassifier(client=httpx.Client(transport=httpx.MockTransport(provider)))

    assert offline.estimate([Q]).input_tokens > 0
    with pytest.raises(ClassifierUnavailable):
        offline.classify([Q])
    assert provider.requests == []
