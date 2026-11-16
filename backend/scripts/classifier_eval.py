"""The known-answer test of a line classifier (M7d S2, docs/erd/face-tree.md "Known-answer
test"): face lines whose answer the mappings already give, asked as if they were open.

Usage (from backend/):
  uv run python scripts/classifier_eval.py --classifier NAME --fixtures AAPL MSFT ...
  uv run python scripts/classifier_eval.py --classifier NAME --db PATH
  uv run python scripts/classifier_eval.py --classifier NAME --holdout       DATA_DIR/holdout.db
Options:
  --limit N   ask the first N cases only
  --yes       ask the classifier. Without it the script prints the cases and the estimate, and
              asks nothing

NAME is one of `classify/registry.py::NAMES`. Not a pytest: with --yes it SPENDS MONEY and sends
the lines' labels, tags and amounts to the provider; it needs the provider's key in `.env`.
--holdout prints totals only (docs/erd/data-coverage.md, "Principles"). A database is read from a
copy, never in place (docs/Gotcha.md G44). The cases and the scoring are `classify/evaluate.py`;
this script only loads, asks and prints.
"""

import argparse
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:  # `tests` is a package of backend/, not of the installed app
    sys.path.insert(0, str(BACKEND))

from bedrock.classify import evaluate, pricing, registry  # noqa: E402
from bedrock.classify.evaluate import Case, Outcome, Score  # noqa: E402
from bedrock.classify.protocol import (  # noqa: E402
    ClassifierError,
    ClassifierUnavailable,
    LineClassifier,
)
from bedrock.classify.types import ClassifyResult, LineQuestion, Usage  # noqa: E402
from bedrock.core.config import Settings, load_settings  # noqa: E402
from bedrock.core.db import make_engine, make_sessionmaker  # noqa: E402
from bedrock.repositories import companies as companies_repo  # noqa: E402
from bedrock.services.statements import load_inputs  # noqa: E402

Factory = Callable[[str, Settings], LineClassifier]


@dataclass(frozen=True)
class Entry:
    ticker: str
    cases: list[Case]


class Metered:
    """A classifier that keeps what its requests used, so a run that fails midway can still say
    what it spent."""

    def __init__(self, classifier: LineClassifier) -> None:
        self._classifier = classifier
        self.name = classifier.name
        self.batch_size = classifier.batch_size
        self.used = Usage(0, 0)

    def estimate(self, questions: Sequence[LineQuestion]) -> Usage:
        return self._classifier.estimate(questions)

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        result = self._classifier.classify(questions)
        self.used += result.usage
        return result


# --- sources ---------------------------------------------------------------------------------


def fixture_companies(tickers: Sequence[str]) -> list[Entry]:
    from tests.statements_pipeline import run_pipeline

    entries = []
    for ticker in dict.fromkeys(t.upper() for t in tickers):
        pipeline = run_pipeline(ticker)
        face = pipeline.rules.filing_lines
        if face is not None:
            entries.append(Entry(ticker, evaluate.cases(face, pipeline.items)))
    return entries


def db_companies(path: Path) -> list[Entry]:
    """Every company of the database at `path` with a parsed filing, read from a copy."""
    with _copy(path) as copy:
        engine = make_engine(f"sqlite:///{copy}")
        try:
            with make_sessionmaker(engine)() as session:
                entries = []
                for company in sorted(companies_repo.list_all(session), key=lambda c: c.ticker):
                    loaded = load_inputs(session, company)
                    face = loaded.rules.filing_lines
                    if face is not None:
                        entries.append(Entry(company.ticker, evaluate.cases(face, loaded.lines)))
                return entries
        finally:
            engine.dispose()


@contextmanager
def _copy(path: Path) -> Iterator[Path]:
    """The same copy as `coverage_report.py`: the file and its WAL, in a temporary folder."""
    if not path.is_file():
        raise FileNotFoundError(f"no database at {path}")
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / path.name
        for suffix in ("", "-wal"):
            source = path.with_name(path.name + suffix)
            if source.is_file():
                shutil.copyfile(source, copy.with_name(copy.name + suffix))
        yield copy


def limited(entries: Sequence[Entry], limit: int | None) -> list[Entry]:
    """The first `limit` cases, company by company."""
    if limit is None:
        return list(entries)
    out = []
    for entry in entries:
        out.append(Entry(entry.ticker, entry.cases[: max(limit, 0)]))
        limit -= len(out[-1].cases)
    return out


# --- the report ------------------------------------------------------------------------------


def render_cases(entries: Sequence[Entry], totals_only: bool = False) -> str:
    """`totals_only` leaves out every company: what the holdout may show."""
    all_cases = [case for entry in entries for case in entry.cases]
    rows = sum(1 for case in all_cases if case.expected)
    out = [f"Cases: {len(all_cases)} ({rows} with a row, {len(all_cases) - rows} with none)"]
    if not totals_only:
        out += [f"  {entry.ticker:<8}{len(entry.cases):>6}" for entry in entries]
    return "\n".join(out)


def render_estimate(name: str, usage: Usage) -> str:
    return (
        f"Estimate: {usage.input_tokens:,} input, {usage.output_tokens:,} output tokens, "
        f"about ${pricing.cost(name, usage):.4f}"
    )


def _pct(part: int, whole: int) -> str:
    share = evaluate.ratio(part, whole)
    return "n/a" if share is None else f"{share * 100:.1f}%"


def render_score(name: str, score: Score, usage: Usage, seconds: float) -> str:
    confident = score.confident
    out = [
        f"Answered: {score.answered}",
        f"Failed: {score.failed}",
        f"Accuracy: {_pct(score.correct, score.answered)} of the answered lines",
        f"At confidence {confident.label}: {_pct(confident.answered, score.cases)} of the cases, "
        f"accuracy {_pct(confident.correct, confident.answered)}",
        "Accuracy by confidence",
    ]
    out += [
        f"  {band.label:<16}{band.answered:>6} answered{_pct(band.correct, band.answered):>8}"
        for band in score.bands
    ]
    per_line = Decimal(str(seconds)) / score.cases if score.cases else Decimal(0)
    out += [
        f"Tokens: {usage.input_tokens:,} input, {usage.output_tokens:,} output",
        f"Cost: ${pricing.cost(name, usage):.4f} (an estimate from the recorded prices)",
        f"Seconds per line: {per_line:.2f}",
    ]
    return "\n".join(out)


# --- main ------------------------------------------------------------------------------------


def main(argv: list[str], factory: Factory = registry.get) -> int:
    """`factory` builds the classifier once `--yes` is given (tests pass a fake's)."""
    parser = argparse.ArgumentParser(prog="classifier_eval.py", add_help=True)
    parser.add_argument("--classifier", required=True, metavar="NAME")
    parser.add_argument("--fixtures", nargs="+", metavar="TICKER")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--limit", type=int, metavar="N")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if sum(bool(x) for x in (args.fixtures, args.db, args.holdout)) != 1:
        print(__doc__)
        return 2
    try:
        estimator = registry.estimator(args.classifier)
        if args.fixtures:
            entries = fixture_companies(args.fixtures)
        else:
            entries = db_companies(args.db or load_settings().data_dir / "holdout.db")
    except (ClassifierUnavailable, FileNotFoundError) as error:
        print(error, file=sys.stderr)
        return 2
    entries = limited(entries, args.limit)
    estimate = Usage(0, 0)
    for entry in entries:
        estimate += estimator.estimate([case.question for case in entry.cases])
    print(f"Classifier: {args.classifier}")
    print(render_cases(entries, totals_only=args.holdout))
    print(render_estimate(args.classifier, estimate))
    if not args.yes:
        print("Nothing was asked. Run again with --yes to ask the classifier (it spends money).")
        return 0
    try:
        classifier = Metered(factory(args.classifier, load_settings()))
    except ClassifierUnavailable as error:
        print(error, file=sys.stderr)
        return 2
    outcomes: list[Outcome] = []
    started = time.perf_counter()
    try:
        for entry in entries:
            outcomes += evaluate.ask(classifier, entry.cases)[0]
    except ClassifierError as error:
        used = classifier.used
        print(f"The classifier failed: {error}", file=sys.stderr)
        print(
            f"Tokens used before the failure: {used.input_tokens:,} input, "
            f"{used.output_tokens:,} output, about ${pricing.cost(args.classifier, used):.4f}",
            file=sys.stderr,
        )
        return 1
    seconds = time.perf_counter() - started
    print(render_score(args.classifier, evaluate.score(outcomes), classifier.used, seconds))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
