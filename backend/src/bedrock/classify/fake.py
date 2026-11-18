"""A classifier that answers from a mapping (docs/erd/face-tree.md "Fake adapter"): for tests
and for trying the feature without a provider."""

from collections.abc import Mapping, Sequence

from bedrock.classify.types import ClassifyResult, LineAnswer, LineQuestion, Usage

INPUT_TOKENS_PER_LINE = 100
OUTPUT_TOKENS_PER_LINE = 10


class FakeClassifier:
    def __init__(
        self,
        answers: Mapping[str, tuple[tuple[str, ...], float]],
        name: str = "fake",
        batch_size: int = 5,
    ) -> None:
        self.answers = answers
        self.name = name
        self.batch_size = batch_size
        self.calls: list[list[LineQuestion]] = []  # the batches received

    def estimate(self, questions: Sequence[LineQuestion]) -> Usage:
        return Usage(
            INPUT_TOKENS_PER_LINE * len(questions), OUTPUT_TOKENS_PER_LINE * len(questions)
        )

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        self.calls.append(list(questions))
        answered = tuple(
            LineAnswer(q.key, *self.answers[q.key]) for q in questions if q.key in self.answers
        )
        failed = tuple(q.key for q in questions if q.key not in self.answers)
        return ClassifyResult(answered, failed, self.estimate(questions))
