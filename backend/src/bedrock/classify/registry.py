"""The classifiers by name: which are configured, and their construction (docs/erd/face-tree.md
"Registry and settings"). A Claude name needs `ANTHROPIC_API_KEY`, the Jev name
`TYPESAFE_API_KEY`."""

from bedrock.classify.claude import ClaudeClassifier
from bedrock.classify.jev import JevClassifier
from bedrock.classify.protocol import ClassifierUnavailable, LineClassifier
from bedrock.core.config import Settings

CLAUDE_PREFIX = "claude:"
NAMES = ("claude:claude-haiku-5-5", "claude:claude-sonnet-5-5", "jev:jev-latest")


def available(settings: Settings) -> list[tuple[str, bool]]:
    """(name, configured) for every classifier, in the order of `NAMES`."""
    return [(name, bool(_key(name, settings))) for name in NAMES]


def get(name: str, settings: Settings) -> LineClassifier:
    """The classifier `name`, ready to ask. An unknown name or a missing key raises
    `ClassifierUnavailable`."""
    _known(name)
    key = _key(name, settings)
    if not key:
        raise ClassifierUnavailable(f"{name} is not configured: its API key is not set")
    return _build(name, key)


def estimator(name: str) -> LineClassifier:
    """The classifier `name` without a key: it estimates as the configured one does, and its
    `classify` raises `ClassifierUnavailable`. An estimate never needs a key or a request."""
    _known(name)
    return _build(name, None)


def _known(name: str) -> None:
    if name not in NAMES:
        raise ClassifierUnavailable(f"No classifier is named {name!r}")


def _key(name: str, settings: Settings) -> str | None:
    if name.startswith(CLAUDE_PREFIX):
        return settings.anthropic_api_key
    return settings.typesafe_api_key


def _build(name: str, key: str | None) -> LineClassifier:
    if name.startswith(CLAUDE_PREFIX):
        return ClaudeClassifier(name.removeprefix(CLAUDE_PREFIX), api_key=key)
    return JevClassifier(api_key=key)
