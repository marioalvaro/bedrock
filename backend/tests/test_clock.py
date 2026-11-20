from datetime import UTC, datetime, timedelta, timezone

from bedrock.core.clock import naive_utc


def test_aware_moment_becomes_naive_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    moment = datetime(2026, 11, 18, 9, 30, tzinfo=eastern)
    assert naive_utc(moment) == datetime(2026, 11, 18, 14, 30)
    assert naive_utc(moment).tzinfo is None


def test_utc_moment_keeps_its_wall_time() -> None:
    assert naive_utc(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == datetime(2026, 1, 2, 3, 4, 5)


def test_naive_moment_is_taken_as_utc_already() -> None:
    moment = datetime(2026, 1, 2, 3, 4, 5)
    assert naive_utc(moment) == moment
