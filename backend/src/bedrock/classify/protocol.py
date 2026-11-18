"""What every classifier is (docs/erd/face-tree.md "Types"), and the errors one raises."""

from collections.abc import Sequence
from typing import Protocol

from bedrock.classify.types import ClassifyResult, LineQuestion, Usage


class ClassifierUnavailable(Exception):
    """No classifier with this name, or its API key is not set."""


class ClassifierError(Exception):
    """The provider failed (an error status, no connection, an answer of an unknown shape); the
    message says how. A line the provider answered unusably is not an error: it is `failed`."""


class LineClassifier(Protocol):
    name: str
    batch_size: int

    def estimate(self, questions: Sequence[LineQuestion]) -> Usage:
        """The tokens asking `questions` would use, without asking: any number of questions,
        counted in requests of `batch_size`."""
        ...

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        """Ask at most `batch_size` questions. Every question's key is in `answers` or in
        `failed`. Raises `ClassifierError` when the provider fails."""
        ...
