"""The classifiers by name: which are configured, and their construction (docs/erd/face-tree.md
"Registry and settings"). A name is `<provider>:<model>`; the provider says which key enables it
(`claude` `ANTHROPIC_API_KEY`, `jev` `TYPESAFE_API_KEY`, `openrouter` `OPENROUTER_API_KEY`) and
how it is built."""

from collections.abc import Callable
from typing import NamedTuple

from bedrock.classify.claude import ClaudeClassifier
from bedrock.classify.jev import JevClassifier
from bedrock.classify.openrouter import OpenRouterClassifier
from bedrock.classify.protocol import ClassifierUnavailable, LineClassifier
from bedrock.core.config import Settings

NAMES = (
    "claude:claude-haiku-5-5",
    "claude:claude-sonnet-5-5",
    "jev:jev-latest",
    "openrouter:openai/gpt-6-luna",
    "openrouter:nvidia/nemotron-3.5-super-vl:free",
)


class Provider(NamedTuple):
    key: Callable[[Settings], str | None]
    build: Callable[[str, str | None], LineClassifier]  # (model, key) -> classifier


PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        lambda s: s.anthropic_api_key, lambda model, key: ClaudeClassifier(model, api_key=key)
    ),
    "jev": Provider(lambda s: s.typesafe_api_key, lambda _model, key: JevClassifier(api_key=key)),
    "openrouter": Provider(
        lambda s: s.openrouter_api_key,
        lambda model, key: OpenRouterClassifier(model, api_key=key),
    ),
}


def available(settings: Settings) -> list[tuple[str, bool]]:
    """(name, configured) for every classifier, in the order of `NAMES`."""
    return [(name, bool(_provider(name).key(settings))) for name in NAMES]


def get(name: str, settings: Settings) -> LineClassifier:
    """The classifier `name`, ready to ask. An unknown name or a missing key raises
    `ClassifierUnavailable`."""
    provider = _known(name)
    key = provider.key(settings)
    if not key:
        raise ClassifierUnavailable(f"{name} is not configured: its API key is not set")
    return provider.build(_model(name), key)


def estimator(name: str) -> LineClassifier:
    """The classifier `name` without a key: it estimates as the configured one does, and its
    `classify` raises `ClassifierUnavailable`. An estimate never needs a key or a request."""
    return _known(name).build(_model(name), None)


def _known(name: str) -> Provider:
    if name not in NAMES:
        raise ClassifierUnavailable(f"No classifier is named {name!r}")
    return _provider(name)


def _provider(name: str) -> Provider:
    return PROVIDERS[name.partition(":")[0]]


def _model(name: str) -> str:
    return name.partition(":")[2]
