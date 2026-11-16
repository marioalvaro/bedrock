"""`services/classification.py` (M7d S3, docs/erd/face-tree.md "Runs and guards"): a run starts
only through its seven checks, asks no line twice, stops at its budget, and its answers are
proposals the user decides on. Every classifier here is a fake."""

import threading
from collections.abc import Callable, Sequence
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bedrock.classify import pricing
from bedrock.classify.fake import FakeClassifier
from bedrock.classify.protocol import ClassifierError, LineClassifier
from bedrock.classify.types import ClassifyResult, LineQuestion, Usage
from bedrock.core.config import Settings
from bedrock.models.audit_log import AuditLog
from bedrock.models.classification_run import ClassificationRun
from bedrock.models.company import Company
from bedrock.repositories import classifications as repo
from bedrock.services import classification as service
from bedrock.services.classification import ClassificationRunner
from bedrock.services.errors import (
    BudgetExceeded,
    ClassificationNotFound,
    ClassificationRunning,
    ClassifierUnavailable,
    CompanyNotFound,
    InvalidClassification,
    NothingToClassify,
    StaleEstimate,
)

from .classification_support import (
    HAIKU,
    JEV,
    NOW,
    STAMP,
    Hungry,
    answering,
    open_lines,
    parse_filings,
)

Factory = Callable[[str, Settings], LineClassifier]


@pytest.fixture
def aapl(db_session: Session, seed_db: Callable[..., None], authed_client: TestClient) -> Company:
    seed_db("AAPL")
    return parse_filings(db_session)


@pytest.fixture
def runner() -> ClassificationRunner:
    return ClassificationRunner(clock=lambda: NOW)


def giving(classifier: LineClassifier) -> Factory:
    return lambda name, settings: classifier


def unavailable(name: str, settings: Settings) -> LineClassifier:
    raise ClassifierUnavailable(f"{name} is not configured")


def start(
    runner: ClassificationRunner,
    session: Session,
    factory: Factory,
    settings: Settings,
    confirm: int,
    *,
    ticker: str = "AAPL",
    name: str = HAIKU,
    wait: bool = True,
) -> ClassificationRun:
    run = runner.start(
        session, sessionmaker(bind=session.get_bind()), factory, settings, ticker, name, confirm
    )
    if wait:
        runner.join(timeout=30)
        session.refresh(run)
    return run


def a_run(session: Session, company: Company, **cols: object) -> ClassificationRun:
    fields: dict[str, object] = {
        "company_id": company.id,
        "classifier": HAIKU,
        "status": "done",
        "started_at": STAMP,
        "lines_asked": 1,
    }
    fields.update(cols)
    run = repo.add_run(session, ClassificationRun(**fields))
    session.commit()
    return run


# --- a run ---------------------------------------------------------------------------------


def test_a_run_asks_every_open_line_once_and_stores_proposals(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    fake = answering(lines)

    run = start(runner, db_session, giving(fake), settings, len(lines))

    asked = [q.key for batch in fake.calls for q in batch]
    assert asked == [ln.question.key for ln in lines]
    assert all(len(batch) <= fake.batch_size for batch in fake.calls)
    assert (run.status, run.error, run.finished_at) == ("done", None, STAMP)
    assert (run.classifier, run.started_at) == (HAIKU, STAMP)
    assert (run.lines_asked, run.lines_answered) == (len(lines), len(lines))
    used = Usage(100 * len(lines), 10 * len(lines))
    assert (run.input_tokens, run.output_tokens) == (used.input_tokens, used.output_tokens)
    assert run.cost_usd == pricing.cost(HAIKU, used).quantize(Decimal("0.000001"))
    rows = repo.rows_for(db_session, aapl.id)
    assert [(r.statement, r.taxonomy, r.concept) for r in rows] == [
        (ln.question.statement, ln.question.taxonomy, ln.question.concept) for ln in lines
    ]
    assert {(r.classifier, r.status, r.run_id, r.confidence) for r in rows} == {
        (HAIKU, "proposed", run.id, Decimal("0.95"))
    }
    assert [repo.codes_of(r) for r in rows] == [(ln.question.candidates[0].code,) for ln in lines]


def test_start_returns_the_running_run_before_the_worker_ends(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    release = threading.Event()

    class Waiting(FakeClassifier):
        def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
            assert release.wait(timeout=10)
            return super().classify(questions)

    fake = Waiting({}, name=HAIKU)
    try:
        run = start(runner, db_session, giving(fake), settings, len(lines), wait=False)
        assert (run.id is not None, run.status, run.lines_asked) == (True, "running", len(lines))
        with pytest.raises(ClassificationRunning):
            start(runner, db_session, giving(fake), settings, len(lines), wait=False)
    finally:
        release.set()
        runner.join(timeout=30)
    db_session.refresh(run)
    assert run.status == "done"


def test_a_second_click_asks_nothing_new(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    fake = answering(lines)
    start(runner, db_session, giving(fake), settings, len(lines))

    with pytest.raises(NothingToClassify):
        start(runner, db_session, giving(fake), settings, len(lines))
    with pytest.raises(NothingToClassify):
        start(runner, db_session, giving(fake), settings, 0)

    assert len(fake.calls) == 2  # the two batches of the first run
    assert db_session.execute(select(ClassificationRun)).scalars().all()[1:] == []


def test_another_classifier_is_asked_about_the_same_lines(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    start(runner, db_session, giving(answering(lines)), settings, len(lines))
    jev = answering(lines, name=JEV, batch_size=1)

    run = start(runner, db_session, giving(jev), settings, len(lines), name=JEV)

    assert (run.status, run.lines_answered, len(jev.calls)) == ("done", len(lines), len(lines))
    assert len(repo.rows_for(db_session, aapl.id)) == 2 * len(lines)


def test_a_failed_line_gets_no_row_and_is_asked_again_by_the_next_run(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    first = answering(lines, skip=2)

    run = start(runner, db_session, giving(first), settings, len(lines))

    assert (run.status, run.lines_asked, run.lines_answered) == ("done", len(lines), len(lines) - 2)
    assert len(repo.rows_for(db_session, aapl.id)) == len(lines) - 2
    second = answering(lines)
    again = start(runner, db_session, giving(second), settings, 2)
    assert [q.key for batch in second.calls for q in batch] == [ln.question.key for ln in lines[:2]]
    assert (again.lines_asked, again.lines_answered) == (2, 2)


def test_a_run_asks_at_most_the_cap_and_the_next_run_goes_on(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    capped = settings.model_copy(update={"classify_max_lines_per_run": 3})
    fake = answering(lines)

    with pytest.raises(StaleEstimate):
        start(runner, db_session, giving(fake), capped, len(lines))
    first = start(runner, db_session, giving(fake), capped, 3)
    second = start(runner, db_session, giving(fake), capped, 3)

    assert (first.lines_asked, second.lines_asked) == (3, 3)
    assert [q.key for batch in fake.calls for q in batch] == [ln.question.key for ln in lines[:6]]


def test_the_returned_run_reads_running_however_fast_the_worker_is(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)

    run = start(runner, db_session, giving(answering(lines)), settings, len(lines), wait=False)
    runner.join(timeout=30)  # the worker has finished and committed `done`

    assert run.status == "running"  # as it was when `start` returned: no re-read
    db_session.refresh(run)
    assert run.status == "done"


def test_a_key_answered_twice_in_one_batch_is_stored_once(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)

    class Repeats(FakeClassifier):
        def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
            result = super().classify(questions)
            again = result.answers[0].__class__(result.answers[0].key, (), 0.1)
            return ClassifyResult((*result.answers, again), result.failed, result.usage)

    fake = Repeats(answering(lines).answers, name=HAIKU, batch_size=5)

    run = start(runner, db_session, giving(fake), settings, len(lines))

    assert (run.status, run.error, run.lines_answered) == ("done", None, len(lines))
    rows = repo.rows_for(db_session, aapl.id)
    assert len(rows) == len(lines)
    assert repo.codes_of(rows[0]) == (lines[0].question.candidates[0].code,)  # the first answer


# --- the checks of `start`, in order ---------------------------------------------------------


def test_check_1_an_unknown_company_comes_before_the_classifier(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    with pytest.raises(CompanyNotFound):
        start(runner, db_session, unavailable, settings, 1, ticker="ZZZZ")


def test_check_1_an_unavailable_classifier_comes_before_everything_else(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    stale = a_run(db_session, aapl, status="running", started_at=STAMP - timedelta(hours=2))

    with pytest.raises(ClassifierUnavailable):
        start(runner, db_session, unavailable, settings, 999)

    db_session.refresh(stale)
    assert stale.status == "running"  # check 2 was not reached


def test_check_2_a_running_row_older_than_thirty_minutes_is_failed_as_timed_out(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    stale = a_run(
        db_session, aapl, status="running", started_at=STAMP - timedelta(minutes=30, seconds=1)
    )

    run = start(runner, db_session, giving(answering(lines)), settings, len(lines))

    db_session.refresh(stale)
    assert (stale.status, stale.error, stale.finished_at) == ("failed", "timed out", STAMP)
    assert run.status == "done"


def test_check_2_holds_even_when_a_later_check_refuses_the_run(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    stale = a_run(db_session, aapl, status="running", started_at=STAMP - timedelta(hours=1))

    with pytest.raises(StaleEstimate):
        start(runner, db_session, giving(answering(lines)), settings, len(lines) + 1)

    db_session.expire_all()
    assert db_session.get(ClassificationRun, stale.id).status == "failed"  # type: ignore[union-attr]


def test_a_running_row_of_thirty_minutes_or_less_still_blocks(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    fresh = a_run(db_session, aapl, status="running", started_at=STAMP - timedelta(minutes=30))
    fake = answering(lines)

    with pytest.raises(ClassificationRunning):
        start(runner, db_session, giving(fake), settings, len(lines))

    db_session.refresh(fresh)
    assert (fresh.status, fake.calls) == ("running", [])
    assert repo.rows_for(db_session, aapl.id) == []


def test_check_3_nothing_to_classify_comes_before_the_confirmed_number(
    db_session: Session,
    seed_db: Callable[..., None],
    authed_client: TestClient,
    runner: ClassificationRunner,
    settings: Settings,
) -> None:
    seed_db("AAPL")  # followed, but no filing parsed: no face line, so no open line

    with pytest.raises(NothingToClassify):
        start(runner, db_session, giving(FakeClassifier({}, name=HAIKU)), settings, 5)


def test_check_4_a_stale_confirmation_comes_before_the_budget(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    broke = settings.model_copy(update={"classify_daily_tokens": 1})
    fake = answering(lines)

    with pytest.raises(StaleEstimate, match=str(len(lines))):
        start(runner, db_session, giving(fake), broke, len(lines) - 1)
    with pytest.raises(BudgetExceeded):
        start(runner, db_session, giving(fake), broke, len(lines))
    assert fake.calls == []


@pytest.mark.parametrize("budget", ["classify_daily_tokens", "classify_monthly_tokens"])
def test_check_5_the_estimate_must_fit_what_is_left_of_each_budget(
    db_session: Session,
    aapl: Company,
    runner: ClassificationRunner,
    settings: Settings,
    budget: str,
) -> None:
    lines = open_lines(db_session, aapl)
    estimate = 110 * len(lines)  # the fake: 100 input and 10 output tokens per line
    a_run(db_session, aapl, input_tokens=400, output_tokens=100)  # 500 used today
    fake = answering(lines)

    with pytest.raises(BudgetExceeded):
        tight = settings.model_copy(update={budget: 500 + estimate - 1})
        start(runner, db_session, giving(fake), tight, len(lines))
    exact = settings.model_copy(update={budget: 500 + estimate})
    run = start(runner, db_session, giving(fake), exact, len(lines))

    assert run.status == "done"


def test_check_5_usage_of_another_day_counts_for_the_month_only(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    estimate = 110 * len(lines)
    a_run(db_session, aapl, started_at=STAMP - timedelta(days=2), input_tokens=5000)
    a_run(db_session, aapl, started_at=STAMP - timedelta(days=40), input_tokens=900_000)
    fake = answering(lines)

    with pytest.raises(BudgetExceeded, match="month"):
        monthly = settings.model_copy(update={"classify_monthly_tokens": 5000 + estimate - 1})
        start(runner, db_session, giving(fake), monthly, len(lines))
    daily = settings.model_copy(
        update={"classify_daily_tokens": estimate, "classify_monthly_tokens": 5000 + estimate}
    )
    assert start(runner, db_session, giving(fake), daily, len(lines)).status == "done"


def test_check_5_the_budget_comes_before_the_running_run(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    a_run(db_session, aapl, status="running")
    broke = settings.model_copy(update={"classify_monthly_tokens": 1})

    with pytest.raises(BudgetExceeded):
        start(runner, db_session, giving(answering(lines)), broke, len(lines))


def test_check_6_one_run_in_the_whole_database(
    db_session: Session,
    seed_db: Callable[..., None],
    authed_client: TestClient,
    runner: ClassificationRunner,
    settings: Settings,
) -> None:
    seed_db("AAPL", "MSFT")
    aapl = parse_filings(db_session)
    msft = parse_filings(db_session, "MSFT")
    a_run(db_session, msft, status="running")
    lines = open_lines(db_session, aapl)

    with pytest.raises(ClassificationRunning):
        start(runner, db_session, giving(answering(lines)), settings, len(lines))

    # the session is usable after the refused insert
    assert repo.rows_for(db_session, aapl.id) == []


def test_check_7_a_worker_that_cannot_start_fails_its_run_and_does_not_block_the_next(
    db_session: Session,
    aapl: Company,
    runner: ClassificationRunner,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = open_lines(db_session, aapl)
    fake = answering(lines)
    original = threading.Thread.start

    def refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", refuse)
    with pytest.raises(RuntimeError):
        start(runner, db_session, giving(fake), settings, len(lines), wait=False)
    monkeypatch.setattr(threading.Thread, "start", original)

    (failed,) = db_session.execute(select(ClassificationRun)).scalars().all()
    assert (failed.status, failed.error) == ("failed", "can't start new thread")
    assert start(runner, db_session, giving(fake), settings, len(lines)).status == "done"


# --- the worker ------------------------------------------------------------------------------


def test_a_budget_reached_midway_ends_the_run_stopped_with_its_rows_kept(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    estimate = 110 * len(lines)
    hungry = Hungry(answering(lines).answers, name=HAIKU, batch_size=5)
    # the estimate fits, but the first batch uses 3 x 550 tokens: the second no longer fits
    tight = settings.model_copy(update={"classify_daily_tokens": estimate + 100})

    run = start(runner, db_session, giving(hungry), tight, len(lines))

    assert (run.status, run.finished_at) == ("stopped", STAMP)
    assert run.error is not None and "daily" in run.error
    assert len(hungry.calls) == 1
    assert (run.lines_asked, run.lines_answered) == (len(lines), 5)
    assert (run.input_tokens, run.output_tokens) == (1500, 150)
    assert len(repo.rows_for(db_session, aapl.id)) == 5


def test_the_monthly_budget_stops_a_run_too(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    lines = open_lines(db_session, aapl)
    hungry = Hungry(answering(lines).answers, name=HAIKU, batch_size=5)
    tight = settings.model_copy(update={"classify_monthly_tokens": 110 * len(lines) + 100})

    run = start(runner, db_session, giving(hungry), tight, len(lines))

    assert run.status == "stopped" and run.error is not None and "monthly" in run.error


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ClassifierError("Claude returned 500: it broke"), "Claude returned 500: it broke"),
        (RuntimeError("boom"), "RuntimeError: boom"),
    ],
)
def test_an_error_ends_the_run_failed_with_its_message_and_keeps_the_rows(
    db_session: Session,
    aapl: Company,
    runner: ClassificationRunner,
    settings: Settings,
    error: Exception,
    message: str,
) -> None:
    lines = open_lines(db_session, aapl)

    class BreaksOnTheSecondBatch(FakeClassifier):
        def classify(self, questions: Sequence[LineQuestion]) -> ClassifyResult:
            if self.calls:
                raise error
            return super().classify(questions)

    fake = BreaksOnTheSecondBatch(answering(lines).answers, name=HAIKU, batch_size=5)

    run = start(runner, db_session, giving(fake), settings, len(lines))

    assert (run.status, run.error, run.finished_at) == ("failed", message, STAMP)
    assert (run.lines_answered, run.input_tokens) == (5, 500)
    assert len(repo.rows_for(db_session, aapl.id)) == 5
    # the lines of the failed batch have no row: the next run asks them
    again = start(runner, db_session, giving(answering(lines)), settings, len(lines) - 5)
    assert again.status == "done"


# --- decisions -------------------------------------------------------------------------------


@pytest.fixture
def proposed(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> Company:
    lines = open_lines(db_session, aapl)
    start(runner, db_session, giving(answering(lines)), settings, len(lines))
    start(runner, db_session, giving(answering(lines, name=JEV)), settings, len(lines), name=JEV)
    return aapl


def audit(session: Session, company: Company) -> list[tuple[str, str, str, str | None, str | None]]:
    rows = session.execute(select(AuditLog).where(AuditLog.company_id == company.id)).scalars()
    return [(r.entity, r.action, r.field, r.old_value, r.new_value) for r in rows]


def test_decide_sets_the_status_and_writes_the_audit_trail(
    db_session: Session, proposed: Company
) -> None:
    row = repo.rows_for(db_session, proposed.id)[0]

    decided = service.decide(db_session, proposed, row.id, "accepted", NOW)

    assert (decided.id, decided.status, decided.decided_at) == (row.id, "accepted", STAMP)
    assert audit(db_session, proposed) == [
        ("line_classification", "edit", "status", "proposed", "accepted")
    ]
    (logged,) = db_session.execute(select(AuditLog)).scalars().all()
    assert (logged.entity_id, logged.changed_at) == (row.id, STAMP)
    assert row.concept in logged.label and HAIKU in logged.label

    service.decide(db_session, proposed, row.id, "rejected", NOW)
    service.decide(db_session, proposed, row.id, "proposed", NOW)
    assert [a[3:] for a in audit(db_session, proposed)] == [
        ("proposed", "accepted"),
        ("accepted", "rejected"),
        ("rejected", "proposed"),
    ]


def test_accepting_another_answer_of_the_line_puts_the_first_back_and_audits_both(
    db_session: Session, proposed: Company
) -> None:
    rows = repo.rows_for(db_session, proposed.id)
    haiku = rows[0]
    jev = next(r for r in rows if r.classifier == JEV and repo.line_of(r) == repo.line_of(haiku))
    service.decide(db_session, proposed, haiku.id, "accepted", NOW)

    service.decide(db_session, proposed, jev.id, "accepted", NOW)

    db_session.expire_all()
    assert (haiku.status, jev.status) == ("proposed", "accepted")
    assert [(a[3], a[4]) for a in audit(db_session, proposed)] == [
        ("proposed", "accepted"),
        ("proposed", "accepted"),
        ("accepted", "proposed"),
    ]


def test_deciding_the_same_status_again_writes_nothing(
    db_session: Session, proposed: Company
) -> None:
    row = repo.rows_for(db_session, proposed.id)[0]

    service.decide(db_session, proposed, row.id, "proposed", NOW)

    assert audit(db_session, proposed) == []


def test_decide_refuses_an_unknown_row_another_companys_row_and_an_unknown_status(
    db_session: Session, proposed: Company
) -> None:
    row = repo.rows_for(db_session, proposed.id)[0]
    other = Company(ticker="BBB", cik="b", name="B", fiscal_year_end_month=12, currency="USD")
    db_session.add(other)
    db_session.commit()

    with pytest.raises(ClassificationNotFound):
        service.decide(db_session, proposed, 999_999, "accepted", NOW)
    with pytest.raises(ClassificationNotFound):
        service.decide(db_session, other, row.id, "accepted", NOW)
    with pytest.raises(InvalidClassification):
        service.decide(db_session, proposed, row.id, "maybe", NOW)
    assert row.status == "proposed"


def test_answer_stores_the_users_own_answer_as_the_accepted_row(
    db_session: Session, proposed: Company
) -> None:
    line = open_lines(db_session, proposed)[0].question
    haiku = repo.rows_for(db_session, proposed.id)[0]
    service.decide(db_session, proposed, haiku.id, "accepted", NOW)
    second = line.candidates[1].code

    row = service.answer(
        db_session, proposed, line.statement, line.taxonomy, line.concept, [second], NOW
    )

    assert (row.classifier, row.status, row.confidence) == ("user", "accepted", Decimal(1))
    assert (repo.codes_of(row), row.run_id, row.decided_at) == ((second,), None, STAMP)
    db_session.refresh(haiku)
    assert haiku.status == "proposed"
    created = [a for a in audit(db_session, proposed) if a[1] == "create"]
    assert sorted(created) == [
        ("line_classification", "create", "codes", None, second),
        ("line_classification", "create", "status", None, "accepted"),
    ]


def test_answer_again_updates_the_users_row(db_session: Session, proposed: Company) -> None:
    line = open_lines(db_session, proposed)[0].question
    place = (line.statement, line.taxonomy, line.concept)
    first, second = (c.code for c in line.candidates[:2])
    service.answer(db_session, proposed, *place, [first], NOW)
    service.decide(
        db_session, proposed, repo.rows_for(db_session, proposed.id)[0].id, "accepted", NOW
    )

    row = service.answer(db_session, proposed, *place, [], NOW + timedelta(hours=1))

    mine = [r for r in repo.rows_for(db_session, proposed.id) if r.classifier == "user"]
    assert mine == [row]
    assert (repo.codes_of(row), row.status) == ((), "accepted")  # "Other": none of the rows
    assert [r.status for r in repo.rows_for(db_session, proposed.id) if r.status == "accepted"] == [
        "accepted"
    ]
    edits = [a for a in audit(db_session, proposed) if a[1] == "edit" and a[2] == "codes"]
    assert edits == [("line_classification", "edit", "codes", first, "")]


def test_answer_takes_a_combined_line_of_candidates(db_session: Session, proposed: Company) -> None:
    line = open_lines(db_session, proposed)[0].question
    first, second = (c.code for c in line.candidates[:2])

    row = service.answer(
        db_session,
        proposed,
        line.statement,
        line.taxonomy,
        line.concept,
        [second, first, second],
        NOW,
    )

    assert repo.codes_of(row) == (second, first)


def test_answer_refuses_a_code_that_is_not_a_candidate_and_a_line_that_is_not_open(
    db_session: Session, proposed: Company
) -> None:
    line = open_lines(db_session, proposed)[0].question
    before = len(repo.rows_for(db_session, proposed.id))

    with pytest.raises(InvalidClassification, match="total_assets"):
        service.answer(
            db_session, proposed, line.statement, line.taxonomy, line.concept, ["total_assets"], NOW
        )
    with pytest.raises(InvalidClassification, match="not a line to classify"):
        service.answer(db_session, proposed, "BS", "us-gaap", "Assets", [], NOW)

    assert len(repo.rows_for(db_session, proposed.id)) == before
    assert audit(db_session, proposed) == []


def test_set_mode_stores_the_mode_and_source_and_audits_them(
    db_session: Session, aapl: Company
) -> None:
    assert (aapl.classification_mode, aapl.classification_source) == ("off", None)

    service.set_mode(db_session, aapl, "all", HAIKU, NOW)

    db_session.refresh(aapl)
    assert (aapl.classification_mode, aapl.classification_source) == ("all", HAIKU)
    assert sorted(audit(db_session, aapl)) == [
        ("company", "mode", "mode", "off", "all"),
        ("company", "mode", "source", None, HAIKU),
    ]

    service.set_mode(db_session, aapl, "accepted", None, NOW)
    db_session.refresh(aapl)
    assert (aapl.classification_mode, aapl.classification_source) == ("accepted", None)


@pytest.mark.parametrize(
    ("mode", "source"),
    [("all", None), ("all", "fake"), ("all", "user"), ("sometimes", None), ("accepted", "fake")],
)
def test_set_mode_refuses_what_it_cannot_use(
    db_session: Session, aapl: Company, mode: str, source: str | None
) -> None:
    with pytest.raises(InvalidClassification):
        service.set_mode(db_session, aapl, mode, source, NOW)

    db_session.refresh(aapl)
    assert (aapl.classification_mode, aapl.classification_source) == ("off", None)
    assert audit(db_session, aapl) == []


# --- status and overview ---------------------------------------------------------------------


def test_status_reports_the_classifiers_the_budgets_and_what_was_used(
    db_session: Session, aapl: Company, settings: Settings
) -> None:
    keyed = settings.model_copy(update={"typesafe_api_key": "t"})
    a_run(db_session, aapl, input_tokens=400, output_tokens=100, cost_usd=Decimal("0.01"))
    a_run(
        db_session,
        aapl,
        started_at=STAMP - timedelta(days=3),
        input_tokens=1000,
        cost_usd=Decimal("0.02"),
    )
    a_run(db_session, aapl, started_at=STAMP - timedelta(days=40), input_tokens=7)

    status = service.status(db_session, keyed, NOW)

    assert status.classifiers == [
        ("claude:claude-haiku-5-5", False),
        ("claude:claude-sonnet-5-5", False),
        ("jev:jev-latest", True),
    ]
    assert (status.daily_tokens, status.monthly_tokens) == (300_000, 3_000_000)
    assert (status.used_today, status.used_month) == (500, 1500)
    assert status.cost_month_usd == Decimal("0.03")
    assert (status.max_lines_per_run, status.min_confidence) == (300, 0.9)


def test_the_overview_lists_the_open_lines_with_their_answers(
    db_session: Session, proposed: Company, settings: Settings
) -> None:
    lines = open_lines(db_session, proposed)

    overview = service.overview(db_session, settings, proposed, None)

    assert (overview.mode, overview.source) == ("off", None)
    assert (overview.to_ask, overview.estimate, overview.estimate_cost_usd) == (None, None, None)
    assert overview.run is not None and overview.run.classifier == JEV  # the newest
    assert [ln.asked.question.key for ln in overview.lines] == [ln.question.key for ln in lines]
    assert all(ln.effective is None for ln in overview.lines)
    assert [[a.classifier for a in ln.answers] for ln in overview.lines] == [[HAIKU, JEV]] * len(
        lines
    )
    assert overview.labels["cash"]


def test_the_overview_estimates_for_a_named_classifier_what_a_run_would_ask(
    db_session: Session, aapl: Company, runner: ClassificationRunner, settings: Settings
) -> None:
    from bedrock.classify import registry

    lines = open_lines(db_session, aapl)
    start(runner, db_session, giving(answering(lines, skip=3)), settings, len(lines))
    capped = settings.model_copy(update={"classify_max_lines_per_run": 2})

    left = service.overview(db_session, settings, aapl, HAIKU)
    fresh = service.overview(db_session, settings, aapl, JEV)
    cut = service.overview(db_session, capped, aapl, JEV)

    assert (left.to_ask, fresh.to_ask, cut.to_ask) == (3, len(lines), 2)
    expected = registry.estimator(HAIKU).estimate([ln.question for ln in lines[:3]])
    assert left.estimate == expected
    assert left.estimate_cost_usd == pricing.cost(HAIKU, expected).quantize(Decimal("0.000001"))
    assert cut.estimate == registry.estimator(JEV).estimate([ln.question for ln in lines[:2]])


def test_the_overview_of_an_unknown_classifier_is_unavailable(
    db_session: Session, aapl: Company, settings: Settings
) -> None:
    with pytest.raises(ClassifierUnavailable):
        service.overview(db_session, settings, aapl, "gpt")


def test_the_overview_shows_what_is_in_force_under_the_mode(
    db_session: Session, proposed: Company, settings: Settings
) -> None:
    rows = repo.rows_for(db_session, proposed.id)
    service.decide(db_session, proposed, rows[0].id, "accepted", NOW)

    service.set_mode(db_session, proposed, "accepted", None, NOW)
    accepted = service.overview(db_session, settings, proposed, None)
    service.set_mode(db_session, proposed, "all", JEV, NOW)
    everything = service.overview(db_session, settings, proposed, None)
    strict = service.overview(
        db_session, settings.model_copy(update={"classify_min_confidence": 0.99}), proposed, None
    )

    assert [ln.effective for ln in accepted.lines][:2] == [repo.codes_of(rows[0]), None]
    assert all(ln.effective is not None for ln in everything.lines)
    assert [ln.effective is not None for ln in strict.lines] == [True] + [False] * (
        len(strict.lines) - 1
    )
    # the lines stay listed: they are computed with no classification applied
    assert len(everything.lines) == len(accepted.lines)


def test_a_company_with_no_parsed_filing_has_an_empty_overview(
    db_session: Session,
    seed_db: Callable[..., None],
    authed_client: TestClient,
    settings: Settings,
) -> None:
    seed_db("AAPL")
    from bedrock.repositories import companies as companies_repo

    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None

    overview = service.overview(db_session, settings, company, HAIKU)

    assert (overview.lines, overview.run, overview.to_ask) == ([], None, 0)
    assert overview.estimate == Usage(0, 0)
