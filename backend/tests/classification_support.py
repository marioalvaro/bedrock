"""Shared set-up for the classification service and API tests (M7d S3): a followed AAPL with its
recorded filings parsed, and fake classifiers. No network."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from bedrock.classify.fake import FakeClassifier
from bedrock.classify.questions import AskedLine
from bedrock.classify.types import ClassifyResult, LineQuestion, Usage
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.services import classification as service
from bedrock.services.filings import backfill_filings

from .fakes import FakeEdgar, FakeFilings, FakePrices

HAIKU = "claude:claude-haiku-5-5"
SONNET = "claude:claude-sonnet-5-5"
JEV = "jev:jev-latest"
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
STAMP = NOW.replace(tzinfo=None)  # as the columns keep it


def parse_filings(session: Session, ticker: str = "AAPL") -> Company:
    """Read the company's recorded filings, so it has face lines; returns it."""
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=FakeFilings())
    backfill_filings(session, sources, ticker)
    company = companies_repo.get_by_ticker(session, ticker)
    assert company is not None
    return company


def open_lines(session: Session, company: Company) -> list[AskedLine]:
    lines = service.open_lines(session, company)
    assert len(lines) >= 8, "the recorded AAPL filings leave lines to classify"
    return lines


def answering(
    lines: Sequence[AskedLine],
    *,
    skip: int = 0,
    name: str = HAIKU,
    batch_size: int = 5,
    confidence: float = 0.95,
) -> FakeClassifier:
    """A fake that answers every line but the first `skip` with its first candidate."""
    answers = {
        asked.question.key: ((asked.question.candidates[0].code,), confidence)
        for asked in lines[skip:]
    }
    return FakeClassifier(answers, name=name, batch_size=batch_size)


class Hungry(FakeClassifier):
    """Uses three times the tokens it estimates."""

    def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
        result = super().classify(questions)
        usage = Usage(3 * result.usage.input_tokens, 3 * result.usage.output_tokens)
        return ClassifyResult(result.answers, result.failed, usage)
