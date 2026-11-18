"""`scripts/classifier_eval.py` (M7d S2, docs/erd/face-tree.md "Known-answer test"): it prints
the cases and the estimate first and asks nothing without `--yes`. The cases and the scoring are
`classify/evaluate.py`, tested on their own; no test here reaches a provider."""

import importlib.util
from collections.abc import Generator, Sequence
from pathlib import Path
from types import ModuleType

import pytest

from bedrock.classify import evaluate
from bedrock.classify.fake import FakeClassifier
from bedrock.classify.protocol import ClassifierError, LineClassifier
from bedrock.classify.types import ClassifyResult, LineQuestion
from bedrock.core.config import Settings
from tests.statements_pipeline import run_pipeline

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "classifier_eval.py"
HAIKU = "claude:claude-haiku-5-5"


@pytest.fixture(autouse=True)
def script_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """No developer `.env` key, no developer data: a blank variable beats the file."""
    from bedrock.core.config import load_settings

    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "no-data"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("classifier_eval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aapl_cases() -> list[evaluate.Case]:
    pipeline = run_pipeline("AAPL")
    assert pipeline.rules.filing_lines is not None
    return evaluate.cases(pipeline.rules.filing_lines, pipeline.items)


def forbidden(name: str, settings: Settings) -> LineClassifier:
    raise AssertionError("no classifier may be built without --yes")


class Factory:
    """Stands in for `registry.get`: hands out one fake that knows every expected answer."""

    def __init__(self, cases: list[evaluate.Case], wrong: int = 0, fail: int = 0) -> None:
        answers = {}
        for n, case in enumerate(cases[fail:]):
            codes = ("no_such_row",) if n < wrong else case.expected
            answers[case.question.key] = (codes, 0.95 if n % 2 else 0.6)
        self.fake = FakeClassifier(answers, name=HAIKU, batch_size=10)
        self.names: list[str] = []

    def __call__(self, name: str, settings: Settings) -> LineClassifier:
        self.names.append(name)
        return self.fake


def test_without_yes_it_prints_the_cases_and_the_estimate_and_asks_nothing(
    script: ModuleType, aapl_cases: list[evaluate.Case], capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(["--classifier", HAIKU, "--fixtures", "AAPL"], factory=forbidden)

    out = capsys.readouterr().out
    assert code == 0
    assert aapl_cases, "the AAPL fixtures give known-answer cases"
    assert f"Cases: {len(aapl_cases)}" in out
    assert "Estimate:" in out and "tokens" in out and "$" in out
    assert "Nothing was asked" in out and "--yes" in out
    assert "Accuracy" not in out


def test_the_estimate_is_the_classifiers_own(
    script: ModuleType, aapl_cases: list[evaluate.Case], capsys: pytest.CaptureFixture[str]
) -> None:
    from bedrock.classify import pricing, registry

    script.main(["--classifier", HAIKU, "--fixtures", "AAPL"], factory=forbidden)

    usage = registry.estimator(HAIKU).estimate([c.question for c in aapl_cases])
    out = capsys.readouterr().out
    assert f"{usage.input_tokens:,} input" in out and f"{usage.output_tokens:,} output" in out
    assert f"${pricing.cost(HAIKU, usage):.4f}" in out


def test_limit_cuts_the_cases(script: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--classifier", HAIKU, "--fixtures", "AAPL", "MSFT", "--limit", "7"]

    assert script.main(args, factory=forbidden) == 0
    assert "Cases: 7" in capsys.readouterr().out


def test_with_yes_it_asks_once_per_case_and_prints_the_scores(
    script: ModuleType, aapl_cases: list[evaluate.Case], capsys: pytest.CaptureFixture[str]
) -> None:
    factory = Factory(aapl_cases, wrong=2, fail=1)
    n = len(aapl_cases)

    code = script.main(["--classifier", HAIKU, "--fixtures", "AAPL", "--yes"], factory=factory)

    out = capsys.readouterr().out
    assert code == 0
    assert factory.names == [HAIKU]
    asked = [q.key for batch in factory.fake.calls for q in batch]
    assert asked == [c.question.key for c in aapl_cases]  # every case once, none twice
    assert out.index("Estimate:") < out.index("Answered:")
    assert f"Cases: {n}" in out
    assert f"Answered: {n - 1}" in out and "Failed: 1" in out
    accuracy = evaluate.ratio(n - 3, n - 1)
    assert accuracy is not None
    assert f"Accuracy: {accuracy * 100:.1f}%" in out
    for label in ("below 0.5", "0.5–0.7", "0.7–0.9", "0.9 and above"):
        assert label in out
    assert f"Tokens: {100 * n:,} input, {10 * n:,} output" in out
    assert "Cost: $" in out and "Seconds per line:" in out


def test_with_yes_and_no_key_it_stops_before_asking(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(["--classifier", HAIKU, "--fixtures", "AAPL", "--yes"])  # the real registry

    captured = capsys.readouterr()
    assert code == 2
    assert "not configured" in captured.err
    assert "Estimate:" in captured.out and "Answered:" not in captured.out


def test_an_unknown_classifier_is_refused(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(["--classifier", "gpt", "--fixtures", "AAPL"], factory=forbidden)

    assert code == 2
    assert "No classifier is named" in capsys.readouterr().err


def test_a_provider_failure_ends_the_run_with_its_message_and_what_was_spent(
    script: ModuleType, aapl_cases: list[evaluate.Case], capsys: pytest.CaptureFixture[str]
) -> None:
    class BreaksOnTheThirdBatch(FakeClassifier):
        def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
            if len(self.calls) == 2:
                raise ClassifierError("Claude returned 500: it broke")
            return super().classify(questions)

    assert len(aapl_cases) > 20
    code = script.main(
        ["--classifier", HAIKU, "--fixtures", "AAPL", "--yes"],
        factory=lambda name, settings: BreaksOnTheThirdBatch({}, name=HAIKU, batch_size=10),
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "Claude returned 500" in err
    # two batches of ten were paid for before the failure: 100 and 10 tokens per line
    assert "Tokens used before the failure: 2,000 input, 200 output" in err
    assert "$0.0003" in err


def test_a_failure_on_the_first_request_spent_nothing(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    class Broken(FakeClassifier):
        def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
            raise ClassifierError("Jev returned 400")

    code = script.main(
        ["--classifier", HAIKU, "--fixtures", "AAPL", "--yes"],
        factory=lambda name, settings: Broken({}, name=HAIKU),
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "Jev returned 400" in err
    assert "Tokens used before the failure: 0 input, 0 output" in err


@pytest.mark.parametrize(
    "argv",
    [
        ["--classifier", HAIKU],
        ["--classifier", HAIKU, "--fixtures", "AAPL", "--holdout"],
        ["--fixtures", "AAPL"],
    ],
)
def test_it_needs_a_classifier_and_exactly_one_source(script: ModuleType, argv: list[str]) -> None:
    try:
        code = script.main(argv, factory=forbidden)
    except SystemExit as stop:  # argparse, for the missing required option
        code = stop.code
    assert code == 2


def test_a_missing_database_is_reported(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(
        ["--classifier", HAIKU, "--db", str(tmp_path / "none.db")], factory=forbidden
    )

    assert code == 2
    assert "no database" in capsys.readouterr().err


def test_the_holdout_shows_totals_only(
    script: ModuleType, aapl_cases: list[evaluate.Case], capsys: pytest.CaptureFixture[str]
) -> None:
    entries = script.fixture_companies(["AAPL"])
    plain = script.render_cases(entries, totals_only=False)
    totals = script.render_cases(entries, totals_only=True)

    assert "AAPL" in plain and f"Cases: {len(aapl_cases)}" in plain
    assert "AAPL" not in totals and f"Cases: {len(aapl_cases)}" in totals
