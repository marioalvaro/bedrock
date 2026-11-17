"""The batch question and answer that the Claude and OpenRouter adapters share (M7d S4b,
docs/erd/face-tree.md "Batch answers"). Pure: no network."""

import json
import math

import pytest

from bedrock.classify import batch, prompt
from bedrock.classify.types import ClassifyResult, LineAnswer, Usage
from tests.classify_data import question

BATCH = [question("A"), question("B"), question("C")]
USAGE = Usage(900, 120)


def text(*answers: tuple[int, list[str], float]) -> str:
    return json.dumps(
        {"answers": [{"index": i, "codes": c, "confidence": p} for i, c, p in answers]}
    )


def test_the_user_message_numbers_the_rendered_questions_from_zero() -> None:
    message = batch.user_message(BATCH)

    assert message.startswith("Place each of the 3 lines below.")
    for n, q in enumerate(BATCH):
        assert f"Line {n}\n{prompt.render(q)}" in message
    assert message.index("Line 0\n") < message.index("Line 1\n") < message.index("Line 2\n")


def test_the_schema_is_strict_with_every_field_required() -> None:
    schema = batch.SCHEMA

    assert schema["type"] == "object"
    assert schema["required"] == ["answers"]
    assert schema["additionalProperties"] is False
    item = schema["properties"]["answers"]["items"]
    assert item["type"] == "object"
    assert set(item["properties"]) == {"index", "codes", "confidence"}
    assert sorted(item["required"]) == ["codes", "confidence", "index"]
    assert item["additionalProperties"] is False
    assert item["properties"]["codes"] == {"type": "array", "items": {"type": "string"}}
    assert "$ref" not in json.dumps(schema)


def test_answers_map_to_the_questions_by_index_and_keep_the_usage() -> None:
    result = batch.result(
        BATCH, text((2, ["inventory"], 0.8), (0, ["cash"], 0.95), (1, [], 0.6)), USAGE
    )

    assert result == ClassifyResult(
        (
            LineAnswer("BS|ext|A", ("cash",), 0.95),
            LineAnswer("BS|ext|B", (), 0.6),
            LineAnswer("BS|ext|C", ("inventory",), 0.8),
        ),
        (),
        USAGE,
    )


def test_no_text_fails_every_line_and_keeps_the_usage() -> None:
    result = batch.result(BATCH, None, USAGE)

    assert result == ClassifyResult((), ("BS|ext|A", "BS|ext|B", "BS|ext|C"), USAGE)


@pytest.mark.parametrize("given", ["", "not json", '{"answers": "x"}', '{"other": []}'])
def test_a_text_that_is_not_the_schema_fails_every_line(given: str) -> None:
    result = batch.result(BATCH, given, USAGE)

    assert result.answers == ()
    assert result.failed == ("BS|ext|A", "BS|ext|B", "BS|ext|C")
    assert result.usage == USAGE


def test_a_code_outside_the_candidates_or_a_duplicate_index_fails_that_line_only() -> None:
    result = batch.result(
        BATCH,
        text(
            (0, ["goodwill"], 0.9),
            (1, ["cash"], 0.9),
            (1, ["inventory"], 0.9),
            (2, ["cash"], 0.9),
            (7, ["cash"], 0.9),
        ),
        USAGE,
    )

    assert result.answers == (LineAnswer("BS|ext|C", ("cash",), 0.9),)
    assert result.failed == ("BS|ext|A", "BS|ext|B")


def test_repeated_codes_are_kept_once_and_confidence_is_clamped() -> None:
    result = batch.result(
        BATCH[:2], text((0, ["cash", "inventory", "cash"], 1.4), (1, [], -0.2)), USAGE
    )

    assert result.answers == (
        LineAnswer("BS|ext|A", ("cash", "inventory"), 1.0),
        LineAnswer("BS|ext|B", (), 0.0),
    )


def test_the_estimate_counts_one_request_per_batch() -> None:
    questions = [question(f"Q{n}") for n in range(12)]

    estimate = batch.estimate(questions, batch_size=10)

    first, second = questions[:10], questions[10:]
    expected_input = sum(
        math.ceil((len(prompt.INSTRUCTIONS) + len(batch.user_message(b))) / 3)
        for b in (first, second)
    )
    assert estimate == Usage(expected_input, 2 * 400 + 60 * 12)


def test_the_estimate_of_nothing_is_zero() -> None:
    assert batch.estimate([], batch_size=10) == Usage(0, 0)
