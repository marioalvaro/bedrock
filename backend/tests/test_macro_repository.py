"""The stored market series (risk-free rate, ERP, index closes): upsert and reads."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.repositories import macro

D = Decimal
AT = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def test_observations_are_stored_oldest_first_and_the_latest_is_read(db_session: Session) -> None:
    rows = [(date(2026, 11, 5), D("4.1")), (date(2026, 11, 4), D("4.0"))]
    assert macro.upsert(db_session, "DGS10", "10-year Treasury", "daily", "fred", rows, AT) == 2
    db_session.commit()

    assert macro.observations(db_session, "DGS10") == [
        (date(2026, 11, 4), D("4.0")),
        (date(2026, 11, 5), D("4.1")),
    ]
    assert macro.latest(db_session, "DGS10") == (date(2026, 11, 5), D("4.1"))
    assert macro.latest(db_session, "UNKNOWN") is None
    assert macro.observations(db_session, "UNKNOWN") == []


def test_a_new_value_for_a_stored_date_replaces_it(db_session: Session) -> None:
    # Today's index bar moves during the session: the later fetch wins.
    macro.upsert(
        db_session, "^GSPC", "S&P 500", "monthly", "yfinance", [(date(2026, 11, 1), D(1))], AT
    )
    later = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
    added = macro.upsert(
        db_session,
        "^GSPC",
        "S&P 500",
        "monthly",
        "yfinance",
        [(date(2026, 11, 1), D(2)), (date(2026, 12, 1), D(3))],
        later,
    )
    db_session.commit()

    assert added == 1
    assert macro.observations(db_session, "^GSPC") == [
        (date(2026, 11, 1), D(2)),
        (date(2026, 12, 1), D(3)),
    ]
    assert macro.fetched_at(db_session, "^GSPC") == later.replace(tzinfo=None)
