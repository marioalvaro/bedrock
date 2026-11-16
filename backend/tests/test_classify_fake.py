"""The prices and the fake adapter (M7d S2, docs/erd/face-tree.md "Prices", "Fake adapter")."""

from decimal import Decimal

import pytest

from bedrock.classify import pricing
from bedrock.classify.fake import FakeClassifier
from bedrock.classify.protocol import LineClassifier
from bedrock.classify.types import LineAnswer, Usage
from tests.classify_data import question

MILLION = Usage(1_000_000, 1_000_000)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("claude:claude-haiku-5-5", Decimal("0.60")),
        ("claude:claude-sonnet-5-5", Decimal("12.00")),
        ("jev:jev-latest", Decimal("0.042")),
    ],
)
def test_cost_is_the_erd_price_per_million_tokens(name: str, expected: Decimal) -> None:
    assert pricing.cost(name, MILLION) == expected


def test_cost_prices_input_and_output_apart() -> None:
    cost = pricing.cost("claude:claude-haiku-5-5", Usage(12_345, 678))

    assert cost == Decimal("0.0012345") + Decimal("0.000339")
    assert isinstance(cost, Decimal)


def test_cost_of_no_tokens_is_zero() -> None:
    assert pricing.cost("claude:claude-sonnet-5-5", Usage(0, 0)) == 0


def test_a_classifier_without_a_listed_price_costs_nothing() -> None:
    assert pricing.cost("fake", MILLION) == 0


def test_usages_add() -> None:
    assert Usage(1, 2) + Usage(10, 20) == Usage(11, 22)


def test_the_fake_answers_from_its_mapping_and_fails_the_rest() -> None:
    fake = FakeClassifier({"BS|ext|A": (("cash",), 0.95), "BS|ext|B": ((), 0.4)})

    result = fake.classify([question("A"), question("B"), question("C")])

    assert result.answers == (
        LineAnswer("BS|ext|A", ("cash",), 0.95),
        LineAnswer("BS|ext|B", (), 0.4),
    )
    assert result.failed == ("BS|ext|C",)
    assert result.usage == Usage(300, 30)


def test_the_fake_records_the_batches_it_received() -> None:
    fake = FakeClassifier({})
    first, second = [question("A"), question("B")], [question("C")]

    fake.classify(first)
    fake.classify(second)

    assert fake.calls == [first, second]


def test_the_fake_estimates_what_it_uses_without_a_call() -> None:
    fake = FakeClassifier({})

    assert fake.estimate([question("A"), question("B")]) == Usage(200, 20)
    assert fake.estimate([]) == Usage(0, 0)
    assert fake.calls == []


def test_the_fake_is_a_line_classifier_with_the_erd_defaults() -> None:
    fake: LineClassifier = FakeClassifier({})
    named = FakeClassifier({}, name="claude:claude-haiku-5-5", batch_size=2)

    assert (fake.name, fake.batch_size) == ("fake", 5)
    assert (named.name, named.batch_size) == ("claude:claude-haiku-5-5", 2)
