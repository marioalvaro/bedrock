"""Names, availability and construction of the classifiers (M7d S2, docs/erd/face-tree.md
"Registry and settings"). No key, no feature."""

from pathlib import Path

import pytest

from bedrock.classify import registry
from bedrock.classify.claude import ClaudeClassifier
from bedrock.classify.jev import JevClassifier
from bedrock.classify.openrouter import OpenRouterClassifier
from bedrock.classify.pricing import PRICES
from bedrock.core.config import Settings
from bedrock.services import errors
from tests.classify_data import question

HAIKU = "claude:claude-haiku-5-5"
SONNET = "claude:claude-sonnet-5-5"
JEV = "jev:jev-latest"
LUNA = "openrouter:openai/gpt-6-luna"
NEMOTRON = "openrouter:nvidia/nemotron-3.5-super-vl:free"


def settings(
    anthropic: str | None = None, typesafe: str | None = None, openrouter: str | None = None
) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=Path("unused"),
        session_secret="test-secret",
        anthropic_api_key=anthropic,
        typesafe_api_key=typesafe,
        openrouter_api_key=openrouter,
    )


EVERY_KEY = {"anthropic": "a", "typesafe": "t", "openrouter": "o"}


def test_the_names_are_the_erd_list_and_each_has_a_price() -> None:
    assert registry.NAMES == (HAIKU, SONNET, JEV, LUNA, NEMOTRON)
    assert set(PRICES) == set(registry.NAMES)


def test_without_a_key_no_classifier_is_configured() -> None:
    assert registry.available(settings()) == [
        (HAIKU, False),
        (SONNET, False),
        (JEV, False),
        (LUNA, False),
        (NEMOTRON, False),
    ]


def test_each_key_configures_its_own_classifiers() -> None:
    assert registry.available(settings(anthropic="a")) == [
        (HAIKU, True),
        (SONNET, True),
        (JEV, False),
        (LUNA, False),
        (NEMOTRON, False),
    ]
    assert registry.available(settings(typesafe="t")) == [
        (HAIKU, False),
        (SONNET, False),
        (JEV, True),
        (LUNA, False),
        (NEMOTRON, False),
    ]
    assert registry.available(settings(openrouter="o")) == [
        (HAIKU, False),
        (SONNET, False),
        (JEV, False),
        (LUNA, True),
        (NEMOTRON, True),
    ]


def test_get_builds_the_named_classifier() -> None:
    every = settings(**EVERY_KEY)

    haiku, sonnet, jev, luna, nemotron = (registry.get(name, every) for name in registry.NAMES)

    assert isinstance(haiku, ClaudeClassifier) and haiku.name == HAIKU
    assert isinstance(sonnet, ClaudeClassifier) and sonnet.name == SONNET
    assert isinstance(jev, JevClassifier) and jev.name == JEV
    assert isinstance(luna, OpenRouterClassifier) and luna.name == LUNA
    assert isinstance(nemotron, OpenRouterClassifier) and nemotron.name == NEMOTRON
    assert nemotron.batch_size == 100


@pytest.mark.parametrize("name", [HAIKU, SONNET, JEV, LUNA, NEMOTRON])
def test_get_without_the_key_is_unavailable(name: str) -> None:
    with pytest.raises(errors.ClassifierUnavailable, match=name):
        registry.get(name, settings())


def test_a_key_of_the_other_provider_does_not_count() -> None:
    with pytest.raises(errors.ClassifierUnavailable):
        registry.get(JEV, settings(anthropic="a"))
    with pytest.raises(errors.ClassifierUnavailable):
        registry.get(HAIKU, settings(typesafe="t"))
    with pytest.raises(errors.ClassifierUnavailable):
        registry.get(LUNA, settings(anthropic="a", typesafe="t"))
    with pytest.raises(errors.ClassifierUnavailable):
        registry.get(HAIKU, settings(openrouter="o"))


@pytest.mark.parametrize(
    "name",
    [
        "fake",
        "claude:claude-opus-5-5",
        "",
        "jev",
        "openrouter:openai/gpt-6-sol",
        "openrouter:",
        "openrouter:nvidia/nemotron-3.5-super-vl",
        "openai/gpt-6-luna",
    ],
)
def test_an_unknown_name_is_unavailable(name: str) -> None:
    with pytest.raises(errors.ClassifierUnavailable):
        registry.get(name, settings(**EVERY_KEY))


@pytest.mark.parametrize("name", [HAIKU, SONNET, JEV, LUNA, NEMOTRON])
def test_the_estimator_needs_no_key_and_cannot_ask(name: str) -> None:
    estimator = registry.estimator(name)

    assert estimator.name == name
    assert estimator.estimate([question()]).input_tokens > 0
    with pytest.raises(errors.ClassifierUnavailable):
        estimator.classify([question()])


def test_the_estimator_of_an_unknown_name_is_unavailable() -> None:
    with pytest.raises(errors.ClassifierUnavailable):
        registry.estimator("fake")


def test_the_estimator_estimates_as_the_configured_classifier_does() -> None:
    every = settings(**EVERY_KEY)
    batch = [question("A"), question("B")]

    for name in registry.NAMES:
        assert registry.estimator(name).estimate(batch) == registry.get(name, every).estimate(batch)


def test_the_services_know_the_classifier_errors() -> None:
    from bedrock.classify import protocol

    assert errors.ClassifierUnavailable is protocol.ClassifierUnavailable
    assert errors.ClassifierError is protocol.ClassifierError
    assert not issubclass(errors.ClassifierError, errors.ClassifierUnavailable)


def test_the_classifier_errors_are_domain_errors_with_a_message_for_a_person() -> None:
    assert issubclass(errors.ClassifierUnavailable, errors.DOMAIN_ERRORS)
    assert issubclass(errors.ClassifierError, errors.DOMAIN_ERRORS)
    assert (
        errors.user_message(errors.ClassifierUnavailable("jev:jev-latest is not configured"))
        == "Classifier unavailable: jev:jev-latest is not configured"
    )
    assert (
        errors.user_message(errors.ClassifierError("Jev returned 400"))
        == "The classifier failed: Jev returned 400"
    )
