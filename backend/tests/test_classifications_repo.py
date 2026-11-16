"""`repositories/classifications.py` (M7d S3, docs/erd/face-tree.md "Storage", "Effective
classification"): answers per classifier and line, the accepted-row rule, what is in force under
each mode, and the token and cost sums the budgets read."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bedrock.models.classification_run import ClassificationRun
from bedrock.models.company import Company
from bedrock.repositories import classifications as repo
from bedrock.repositories.classifications import Proposal

HAIKU = "claude:claude-haiku-5-5"
JEV = "jev:jev-latest"
NOW = datetime(2026, 11, 17, 10, 0)
WIDGETS = ("BS", "ext", "Widgets")


def company(session: Session, ticker: str = "AAA", **cols: object) -> Company:
    row = Company(
        ticker=ticker, cik=f"cik-{ticker}", name=ticker, fiscal_year_end_month=12, currency="USD"
    )
    for name, value in cols.items():
        setattr(row, name, value)
    session.add(row)
    session.flush()
    return row


def proposal(
    concept: str = "Widgets",
    codes: tuple[str, ...] = ("inventory",),
    confidence: float = 0.95,
    statement: str = "BS",
) -> Proposal:
    return Proposal(statement, "ext", concept, codes, confidence)


def run(
    session: Session, owner: Company, started: datetime = NOW, **cols: object
) -> ClassificationRun:
    fields: dict[str, object] = {
        "company_id": owner.id,
        "classifier": HAIKU,
        "status": "done",
        "started_at": started,
        "lines_asked": 1,
    }
    fields.update(cols)
    return repo.add_run(session, ClassificationRun(**fields))


def test_proposals_are_stored_as_proposed_rows_with_their_codes(db_session: Session) -> None:
    owner = company(db_session)
    started = run(db_session, owner)

    added = repo.add_proposals(
        db_session,
        owner.id,
        HAIKU,
        started.id,
        [proposal(), proposal("Tools", (), 0.61234), proposal("Mix", ("cash", "inventory"), 1)],
        NOW,
    )

    rows = repo.rows_for(db_session, owner.id)
    assert added == 3
    assert [(r.concept, repo.codes_of(r), r.confidence, r.status) for r in rows] == [
        ("Widgets", ("inventory",), Decimal("0.95"), "proposed"),
        ("Tools", (), Decimal("0.6123"), "proposed"),
        ("Mix", ("cash", "inventory"), Decimal("1"), "proposed"),
    ]
    assert {(r.classifier, r.run_id, r.created_at, r.decided_at) for r in rows} == {
        (HAIKU, started.id, NOW, None)
    }


def test_one_answer_per_classifier_and_line(db_session: Session) -> None:
    owner = company(db_session)
    other = company(db_session, "BBB")
    repo.add_proposals(db_session, owner.id, HAIKU, None, [proposal()], NOW)
    repo.add_proposals(db_session, owner.id, JEV, None, [proposal()], NOW)
    repo.add_proposals(db_session, owner.id, HAIKU, None, [proposal(statement="IS")], NOW)
    repo.add_proposals(db_session, other.id, HAIKU, None, [proposal()], NOW)
    db_session.commit()

    with pytest.raises(IntegrityError):
        repo.add_proposals(db_session, owner.id, HAIKU, None, [proposal(codes=())], NOW)
    db_session.rollback()

    assert len(repo.rows_for(db_session, owner.id)) == 3
    assert len(repo.rows_for(db_session, other.id)) == 1


def test_a_row_is_found_only_under_its_own_company(db_session: Session) -> None:
    owner, other = company(db_session), company(db_session, "BBB")
    repo.add_proposals(db_session, owner.id, HAIKU, None, [proposal()], NOW)
    (row,) = repo.rows_for(db_session, owner.id)

    assert repo.get(db_session, owner.id, row.id) is row
    assert repo.get(db_session, other.id, row.id) is None
    assert repo.get(db_session, owner.id, row.id + 99) is None
    assert repo.get_for(db_session, owner.id, WIDGETS, HAIKU) is row
    assert repo.get_for(db_session, owner.id, WIDGETS, JEV) is None


def test_accepting_one_row_sets_the_lines_other_accepted_row_back_to_proposed(
    db_session: Session,
) -> None:
    owner = company(db_session)
    repo.add_proposals(db_session, owner.id, HAIKU, None, [proposal(), proposal("Tools")], NOW)
    repo.add_proposals(db_session, owner.id, JEV, None, [proposal(codes=("cash",))], NOW)
    haiku, tools, jev = repo.rows_for(db_session, owner.id)
    later = NOW + timedelta(hours=1)

    assert repo.set_status(db_session, haiku, "accepted", NOW) == []
    assert repo.set_status(db_session, tools, "accepted", NOW) == []
    assert repo.set_status(db_session, jev, "accepted", later) == [haiku]

    assert (haiku.status, jev.status, tools.status) == ("proposed", "accepted", "accepted")
    assert (jev.decided_at, tools.decided_at) == (later, NOW)
    assert haiku.decided_at == later  # put back by the later decision


def test_rejecting_or_reopening_touches_only_that_row(db_session: Session) -> None:
    owner = company(db_session)
    repo.add_proposals(db_session, owner.id, HAIKU, None, [proposal()], NOW)
    repo.add_proposals(db_session, owner.id, JEV, None, [proposal()], NOW)
    haiku, jev = repo.rows_for(db_session, owner.id)
    repo.set_status(db_session, haiku, "accepted", NOW)

    repo.set_status(db_session, jev, "rejected", NOW)
    assert (haiku.status, jev.status) == ("accepted", "rejected")
    repo.set_status(db_session, jev, "proposed", NOW)
    assert (haiku.status, jev.status) == ("accepted", "proposed")


def seeded(session: Session, mode: str, source: str | None = None) -> Company:
    """Widgets: Haiku 0.95 inventory, Jev 0.99 cash. Tools: Haiku 0.80 none. Fees (IS and BS):
    Haiku 0.92 revenue on IS, Haiku 0.97 cash on BS. Gone: Haiku 0.99, rejected."""
    owner = company(session, classification_mode=mode, classification_source=source)
    repo.add_proposals(
        session,
        owner.id,
        HAIKU,
        None,
        [
            proposal("Widgets", ("inventory",), 0.95),
            proposal("Tools", (), 0.80),
            proposal("Fees", ("revenue",), 0.92, statement="IS"),
            proposal("Fees", ("cash",), 0.97),
            proposal("Gone", ("cash",), 0.99),
        ],
        NOW,
    )
    repo.add_proposals(session, owner.id, JEV, None, [proposal("Widgets", ("cash",), 0.99)], NOW)
    by = {(r.classifier, r.statement, r.concept): r for r in repo.rows_for(session, owner.id)}
    repo.set_status(session, by[(HAIKU, "BS", "Gone")], "rejected", NOW)
    return owner


def test_mode_off_has_no_effective_classification(db_session: Session) -> None:
    owner = seeded(db_session, "off", HAIKU)
    repo.set_status(db_session, repo.rows_for(db_session, owner.id)[0], "accepted", NOW)

    assert repo.effective(db_session, owner, 0.9) == {}
    assert repo.effective_lines(repo.rows_for(db_session, owner.id), "off", HAIKU, 0.9) == {}


def test_mode_accepted_uses_only_accepted_rows(db_session: Session) -> None:
    owner = seeded(db_session, "accepted", HAIKU)
    assert repo.effective(db_session, owner, 0.9) == {}

    tools = repo.get_for(db_session, owner.id, ("BS", "ext", "Tools"), HAIKU)
    jev = repo.get_for(db_session, owner.id, WIDGETS, JEV)
    assert tools is not None and jev is not None
    repo.set_status(db_session, tools, "accepted", NOW)
    repo.set_status(db_session, jev, "accepted", NOW)

    assert repo.effective(db_session, owner, 0.9) == {
        ("ext", "Widgets"): ("cash",),
        ("ext", "Tools"): (),  # an accepted "none of the rows" is in force too
    }


def test_mode_all_adds_the_sources_proposals_at_or_above_the_threshold(db_session: Session) -> None:
    owner = seeded(db_session, "all", HAIKU)

    lines = repo.effective_lines(repo.rows_for(db_session, owner.id), "all", HAIKU, 0.92)

    assert lines == {
        WIDGETS: ("inventory",),  # 0.95; Jev's 0.99 is not the source
        ("IS", "ext", "Fees"): ("revenue",),  # 0.92: the threshold itself counts
        ("BS", "ext", "Fees"): ("cash",),
        # not Tools (0.80), not Gone (rejected)
    }
    assert repo.effective(db_session, owner, 0.92) == {
        ("ext", "Widgets"): ("inventory",),
        ("ext", "Fees"): ("revenue", "cash"),  # a concept's statements merged, IS then BS
    }


def test_mode_all_prefers_the_accepted_row_and_never_uses_a_rejected_one(
    db_session: Session,
) -> None:
    owner = seeded(db_session, "all", HAIKU)
    jev = repo.get_for(db_session, owner.id, WIDGETS, JEV)
    fees = repo.get_for(db_session, owner.id, ("BS", "ext", "Fees"), HAIKU)
    assert jev is not None and fees is not None
    repo.set_status(db_session, jev, "accepted", NOW)
    repo.set_status(db_session, fees, "rejected", NOW)

    assert repo.effective(db_session, owner, 0.9) == {
        ("ext", "Widgets"): ("cash",),
        ("ext", "Fees"): ("revenue",),
    }


def test_mode_all_without_a_source_uses_only_accepted_rows(db_session: Session) -> None:
    owner = seeded(db_session, "all", None)

    assert repo.effective(db_session, owner, 0.0) == {}


def test_another_companys_rows_are_never_effective(db_session: Session) -> None:
    seeded(db_session, "all", HAIKU)
    other = company(db_session, "BBB", classification_mode="all", classification_source=HAIKU)

    assert repo.effective(db_session, other, 0.0) == {}


def test_usage_sums_the_runs_started_in_the_window(db_session: Session) -> None:
    owner, other = company(db_session), company(db_session, "BBB")
    day = datetime(2026, 11, 17)
    run(db_session, owner, day, input_tokens=100, output_tokens=10, cost_usd=Decimal("0.010000"))
    run(
        db_session,
        other,
        day + timedelta(hours=23, minutes=59),
        input_tokens=1000,
        output_tokens=0,
        cost_usd=Decimal("0.200000"),
        status="failed",
    )
    run(db_session, owner, day - timedelta(seconds=1), input_tokens=5, output_tokens=5)
    run(db_session, owner, day + timedelta(days=1), input_tokens=7, output_tokens=7)

    assert repo.usage(db_session, day, day + timedelta(days=1)) == (1110, Decimal("0.21"))
    assert repo.usage(db_session, datetime(2026, 11, 1), datetime(2026, 12, 1)) == (
        1134,
        Decimal("0.21"),
    )
    assert repo.usage(db_session, datetime(2025, 1, 1), datetime(2025, 2, 1)) == (0, Decimal(0))


def test_the_newest_run_of_a_company_and_the_running_one(db_session: Session) -> None:
    owner, other = company(db_session), company(db_session, "BBB")
    assert repo.newest_run(db_session, owner.id) is None
    assert repo.running(db_session) is None
    run(db_session, owner, NOW)
    newest = run(db_session, owner, NOW + timedelta(hours=1), status="running")
    run(db_session, other, NOW + timedelta(hours=2))

    assert repo.newest_run(db_session, owner.id) is newest
    assert repo.running(db_session) is newest


def test_a_second_running_run_is_refused_by_the_database(db_session: Session) -> None:
    owner, other = company(db_session), company(db_session, "BBB")
    run(db_session, owner, status="running")
    db_session.commit()

    with pytest.raises(IntegrityError):
        run(db_session, other, status="running")
