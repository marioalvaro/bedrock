"""Line classification runs and decisions (M7d S3, docs/erd/face-tree.md "Runs and guards"). A
classifier is called only from `ClassificationRunner.start`, after its checks; its answers are
proposals, and what the statements use is the company's mode."""

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from bedrock.classify import pricing, questions, registry
from bedrock.classify.protocol import ClassifierError, LineClassifier
from bedrock.classify.questions import AskedLine
from bedrock.classify.types import LineQuestion, Usage
from bedrock.core.config import Settings
from bedrock.models.classification_run import ClassificationRun
from bedrock.models.company import Company
from bedrock.models.line_classification import LineClassification
from bedrock.repositories import classifications as repo
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import mappings as mappings_repo
from bedrock.repositories.classifications import Line, Proposal
from bedrock.services import audit as audit_service
from bedrock.services.errors import (
    BudgetExceeded,
    ClassificationNotFound,
    ClassificationRunning,
    CompanyNotFound,
    InvalidClassification,
    NothingToClassify,
    StaleEstimate,
)
from bedrock.services.statements import canonical_items, face_lines

logger = logging.getLogger(__name__)

Factory = Callable[[str, Settings], LineClassifier]
USER = "user"  # the `classifier` of the user's own answer
MODES = ("off", "accepted", "all")
STATUSES = ("proposed", "accepted", "rejected")
STALE_AFTER = timedelta(minutes=30)
COST_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class Status:
    classifiers: list[tuple[str, bool]]  # (name, configured)
    daily_tokens: int
    monthly_tokens: int
    used_today: int
    used_month: int
    cost_month_usd: Decimal
    max_lines_per_run: int
    min_confidence: float


@dataclass(frozen=True)
class OverviewLine:
    asked: AskedLine
    effective: tuple[str, ...] | None  # the codes in force under the mode; None when none
    answers: list[LineClassification]


@dataclass(frozen=True)
class Overview:
    """`to_ask`, `estimate` and `estimate_cost_usd` are for the named classifier; None without
    one. `labels` names every canonical code."""

    mode: str
    source: str | None
    run: ClassificationRun | None  # the company's newest
    to_ask: int | None
    estimate: Usage | None
    estimate_cost_usd: Decimal | None
    lines: list[OverviewLine]
    labels: dict[str, str]


def open_lines(session: Session, company: Company) -> list[AskedLine]:
    """The company's lines to classify, with no classification applied (whatever its mode)."""
    mappings = mappings_repo.mappings_for(session, company.id)
    face = face_lines(session, company, mappings, None, classified={})
    return [] if face is None else questions.open_lines(face, canonical_items())


def status(session: Session, settings: Settings, now: datetime) -> Status:
    day, next_day, month, next_month = _windows(_naive_utc(now))
    used_month, cost_month = repo.usage(session, month, next_month)
    return Status(
        classifiers=registry.available(settings),
        daily_tokens=settings.classify_daily_tokens,
        monthly_tokens=settings.classify_monthly_tokens,
        used_today=repo.usage(session, day, next_day)[0],
        used_month=used_month,
        cost_month_usd=cost_month,
        max_lines_per_run=settings.classify_max_lines_per_run,
        min_confidence=settings.classify_min_confidence,
    )


def overview(
    session: Session, settings: Settings, company: Company, classifier_name: str | None
) -> Overview:
    """The company's open lines with every answer, and for `classifier_name` what a run would ask
    now. Builds no classifier that can ask: the estimate needs no key. Raises
    ClassifierUnavailable for an unknown name."""
    estimator = None if classifier_name is None else registry.estimator(classifier_name)
    lines = open_lines(session, company)
    rows = repo.rows_for(session, company.id)
    in_force = repo.effective_lines(
        rows,
        company.classification_mode,
        company.classification_source,
        settings.classify_min_confidence,
    )
    by_line: dict[Line, list[LineClassification]] = {}
    for row in rows:
        by_line.setdefault(repo.line_of(row), []).append(row)
    to_ask = estimate = cost = None
    if estimator is not None and classifier_name is not None:
        asking = _to_ask(lines, rows, classifier_name, settings)
        to_ask = len(asking)
        estimate = estimator.estimate([a.question for a in asking])
        cost = pricing.cost(classifier_name, estimate).quantize(COST_PLACES)
    return Overview(
        mode=company.classification_mode,
        source=company.classification_source,
        run=repo.newest_run(session, company.id),
        to_ask=to_ask,
        estimate=estimate,
        estimate_cost_usd=cost,
        lines=[
            OverviewLine(asked, in_force.get(_line(asked)), by_line.get(_line(asked), []))
            for asked in lines
        ],
        labels={i.code: i.label for i in canonical_items()},
    )


class ClassificationRunner:
    """Starts a classification run after its checks and carries it out in a worker thread (the
    route's 202), like `services/filings.py::BackfillRunner`. The database allows one running
    run; a run left `running` by a process that died is failed after `STALE_AFTER`."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(
        self,
        session: Session,
        session_factory: sessionmaker[Session],
        factory: Factory,
        settings: Settings,
        ticker: str,
        classifier_name: str,
        confirm_lines: int,
    ) -> ClassificationRun:
        """Start a run and return it (`running`). In this order, raises CompanyNotFound,
        ClassifierUnavailable, NothingToClassify, StaleEstimate (`confirm_lines` is not the
        number a run would now ask), BudgetExceeded and ClassificationRunning."""
        company = companies_repo.get_by_ticker(session, ticker.strip().upper())
        if company is None:
            raise CompanyNotFound(ticker)
        classifier = factory(classifier_name, settings)
        now = _naive_utc(self._clock())
        self._fail_stale(session, now)
        asking = _to_ask(
            open_lines(session, company),
            repo.rows_for(session, company.id),
            classifier_name,
            settings,
        )
        if not asking:
            raise NothingToClassify(
                f"{classifier_name} has no line of {company.ticker} left to classify"
            )
        if confirm_lines != len(asking):
            raise StaleEstimate(
                f"{len(asking)} lines would be sent now, not the {confirm_lines} confirmed: "
                "check the new estimate and confirm again"
            )
        asked = [a.question for a in asking]
        estimate = classifier.estimate(asked)
        reason = _over_budget(
            session, settings, now, estimate.input_tokens + estimate.output_tokens
        )
        if reason is not None:
            raise BudgetExceeded(f"The estimate does not fit: {reason}")
        run = ClassificationRun(
            company_id=company.id,
            classifier=classifier_name,
            status="running",
            started_at=now,
            lines_asked=len(asked),
        )
        try:
            repo.add_run(session, run)
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise ClassificationRunning("A classification run is already running") from error
        # `run.id` below reloads the row now, so the run handed back reads `running` however
        # fast the worker commits.
        thread = threading.Thread(
            target=self._work,
            args=(session_factory, classifier, settings, run.id, classifier_name, asked),
            name=f"classify-{company.ticker}",
            daemon=True,
        )
        try:
            thread.start()
        except BaseException as error:
            _finish(session, run, "failed", str(error), _naive_utc(self._clock()))
            raise
        with self._lock:
            self._thread = thread
        return run

    def join(self, timeout: float | None = None) -> None:
        """Wait for the last started run's worker (tests and shutdown)."""
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _fail_stale(self, session: Session, now: datetime) -> None:
        running = repo.running(session)
        if running is not None and now - running.started_at > STALE_AFTER:
            _finish(session, running, "failed", "timed out", now)

    def _work(
        self,
        session_factory: sessionmaker[Session],
        classifier: LineClassifier,
        settings: Settings,
        run_id: int,
        classifier_name: str,
        asked: Sequence[LineQuestion],
    ) -> None:
        try:
            with session_factory() as session:
                run = repo.get_run(session, run_id)
                assert run is not None
                try:
                    outcome, reason = self._ask(session, classifier, settings, run, asked)
                except ClassifierError as error:
                    session.rollback()
                    outcome, reason = "failed", str(error)
                except Exception as error:  # a run never stays `running` after its worker
                    session.rollback()
                    logger.exception("classification run %d failed", run_id)
                    outcome, reason = "failed", f"{type(error).__name__}: {error}"
                _finish(session, run, outcome, reason, _naive_utc(self._clock()))
        except Exception:  # the thread's top level: nothing above it would see the error
            logger.exception("classification run %d could not be closed", run_id)

    def _ask(
        self,
        session: Session,
        classifier: LineClassifier,
        settings: Settings,
        run: ClassificationRun,
        asked: Sequence[LineQuestion],
    ) -> tuple[str, str | None]:
        """Ask batch by batch, committing each batch's proposals and usage; returns the run's
        final status and reason. A failed line gets no row, so a later run asks it again."""
        by_key = {q.key: q for q in asked}
        for start in range(0, len(asked), classifier.batch_size):
            batch = asked[start : start + classifier.batch_size]
            now = _naive_utc(self._clock())
            estimate = classifier.estimate(batch)
            reason = _over_budget(
                session, settings, now, estimate.input_tokens + estimate.output_tokens
            )
            if reason is not None:
                return "stopped", f"Stopped: {reason}"
            result = classifier.classify(batch)
            answers = {a.key: a for a in reversed(result.answers) if a.key in by_key}
            proposals = [  # one per line: of a key answered twice, the first answer
                Proposal(
                    by_key[key].statement,
                    by_key[key].taxonomy,
                    by_key[key].concept,
                    answers[key].codes,
                    answers[key].confidence,
                )
                for key in (q.key for q in batch)
                if key in answers
            ]
            repo.add_proposals(session, run.company_id, run.classifier, run.id, proposals, now)
            run.lines_answered += len(proposals)
            run.input_tokens += result.usage.input_tokens
            run.output_tokens += result.usage.output_tokens
            run.cost_usd += pricing.cost(run.classifier, result.usage).quantize(COST_PLACES)
            session.commit()
        return "done", None


def decide(
    session: Session, company: Company, classification_id: int, status: str, now: datetime
) -> LineClassification:
    """Accept, reject or reopen (`proposed`) one answer. Accepting it puts any other accepted
    answer of the line back to `proposed`. Raises ClassificationNotFound and
    InvalidClassification."""
    if status not in STATUSES:
        raise InvalidClassification(f"The status must be one of {', '.join(STATUSES)}")
    row = repo.get(session, company.id, classification_id)
    if row is None:
        raise ClassificationNotFound(str(classification_id))
    stamp = _naive_utc(now)
    before = row.status
    put_back = repo.set_status(session, row, status, stamp)
    _record(session, row, "edit", {"status": before}, {"status": status}, stamp)
    for other in put_back:
        _record(session, other, "edit", {"status": "accepted"}, {"status": "proposed"}, stamp)
    session.commit()
    return row


def answer(
    session: Session,
    company: Company,
    statement: str,
    taxonomy: str,
    concept: str,
    codes: Sequence[str],
    now: datetime,
) -> LineClassification:
    """The user's own answer for one open line: the accepted row of classifier `user`, inserted
    or updated. `codes` are candidates of the line, or empty for none of the rows. Raises
    InvalidClassification."""
    line = (statement, taxonomy, concept)
    asked = next((a for a in open_lines(session, company) if _line(a) == line), None)
    if asked is None:
        raise InvalidClassification(
            f"{statement} {taxonomy}:{concept} is not a line to classify of {company.ticker}"
        )
    chosen = tuple(dict.fromkeys(codes))
    unknown = set(chosen) - {c.code for c in asked.question.candidates}
    if unknown:
        raise InvalidClassification(f"Not a row this line can be: {', '.join(sorted(unknown))}")
    stamp = _naive_utc(now)
    row = repo.get_for(session, company.id, line, USER)
    if row is None:
        row = repo.add(
            session,
            LineClassification(
                company_id=company.id,
                statement=statement,
                taxonomy=taxonomy,
                concept=concept,
                classifier=USER,
                codes=repo.codes_text(chosen),
                confidence=Decimal(1),
                status="proposed",
                created_at=stamp,
            ),
        )
        action, before = "create", {}
    else:
        action, before = "edit", _audited(row)
        row.codes = repo.codes_text(chosen)
    put_back = repo.set_status(session, row, "accepted", stamp)
    _record(session, row, action, before, _audited(row), stamp)
    for other in put_back:
        _record(session, other, "edit", {"status": "accepted"}, {"status": "proposed"}, stamp)
    session.commit()
    return row


def set_mode(
    session: Session, company: Company, mode: str, source: str | None, now: datetime
) -> Company:
    """What of the classifications the company's statements use. `all` needs a `source`; a
    source, when given, is a registry name and is stored with any mode. Raises
    InvalidClassification."""
    if mode not in MODES:
        raise InvalidClassification(f"The mode must be one of {', '.join(MODES)}")
    if mode == "all" and source is None:
        raise InvalidClassification("The mode all needs a source classifier")
    if source is not None and source not in registry.NAMES:
        raise InvalidClassification(f"No classifier is named {source!r}")
    before = {"mode": company.classification_mode, "source": company.classification_source}
    company.classification_mode = mode
    company.classification_source = source
    audit_service.record(
        session,
        company.id,
        "company",
        company.id,
        None,
        "mode",
        before,
        {"mode": mode, "source": source},
        lambda field: (f"Line classification {field}", None),
        _naive_utc(now),
    )
    session.commit()
    return company


def _line(asked: AskedLine) -> Line:
    q = asked.question
    return (q.statement, q.taxonomy, q.concept)


def _to_ask(
    lines: Sequence[AskedLine],
    rows: Sequence[LineClassification],
    classifier_name: str,
    settings: Settings,
) -> list[AskedLine]:
    """The open lines the classifier has no row for, cut to the cap of one run."""
    done = {repo.line_of(row) for row in rows if row.classifier == classifier_name}
    return [a for a in lines if _line(a) not in done][: settings.classify_max_lines_per_run]


def _windows(now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    """The UTC day and calendar month of `now`, each as [start, end)."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    next_month = (month + timedelta(days=32)).replace(day=1)
    return day, day + timedelta(days=1), month, next_month


def _over_budget(session: Session, settings: Settings, now: datetime, tokens: int) -> str | None:
    """Which budget `tokens` more would exceed, as a sentence; None when both hold."""
    day, next_day, month, next_month = _windows(now)
    used_today = repo.usage(session, day, next_day)[0]
    if used_today + tokens > settings.classify_daily_tokens:
        left = max(settings.classify_daily_tokens - used_today, 0)
        return f"{tokens:,} tokens are needed and {left:,} are left of the daily budget"
    used_month = repo.usage(session, month, next_month)[0]
    if used_month + tokens > settings.classify_monthly_tokens:
        left = max(settings.classify_monthly_tokens - used_month, 0)
        return f"{tokens:,} tokens are needed and {left:,} are left of the monthly budget"
    return None


def _finish(
    session: Session, run: ClassificationRun, status: str, error: str | None, now: datetime
) -> None:
    run.status = status
    run.error = error
    run.finished_at = now
    session.commit()


def _audited(row: LineClassification) -> dict[str, str | None]:
    return {"status": row.status, "codes": ",".join(repo.codes_of(row))}


def _record(
    session: Session,
    row: LineClassification,
    action: str,
    before: dict[str, str | None],
    after: dict[str, str | None],
    stamp: datetime,
) -> None:
    name = f"{row.statement} {row.taxonomy}:{row.concept} ({row.classifier})"
    audit_service.record(
        session,
        row.company_id,
        "line_classification",
        row.id,
        None,
        action,
        before,
        after,
        lambda field: (f"{name} {field}", None),
        stamp,
    )


def _naive_utc(moment: datetime) -> datetime:
    # SQLite keeps no time zone: the columns hold UTC without one.
    return moment.astimezone(UTC).replace(tzinfo=None)
