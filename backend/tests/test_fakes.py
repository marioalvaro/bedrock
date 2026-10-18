"""The test doubles for the external sources: they must behave like the real adapters."""

from datetime import date
from decimal import Decimal

import pytest

from bedrock.ingest.protocol import (
    CompanyRef,
    SourceNotConfigured,
    SourceUnavailable,
    SplitRow,
    UnknownTicker,
)

from .fakes import FakeEdgar, FakePrices

AAPL = CompanyRef("AAPL", "0000320193")


def test_fake_edgar_resolves_a_recorded_ticker() -> None:
    profile = FakeEdgar().resolve("aapl")

    assert (profile.cik, profile.ticker, profile.fiscal_year_end_month) == ("0000320193", "AAPL", 9)
    assert profile.name == "Apple Inc."


def test_fake_edgar_does_not_know_other_tickers() -> None:
    with pytest.raises(UnknownTicker):
        FakeEdgar().resolve("ZZZZ")


def test_fake_edgar_fetches_the_recorded_companyfacts() -> None:
    payload = FakeEdgar().fetch(AAPL, None)

    assert payload.companyfacts["cik"] == 320193
    assert "us-gaap" in payload.companyfacts["facts"]


@pytest.mark.parametrize("error", [SourceUnavailable("down"), SourceNotConfigured("no UA")])
def test_fake_edgar_raises_what_it_is_told_to(error: Exception) -> None:
    edgar = FakeEdgar(raises=error)

    with pytest.raises(type(error)):
        edgar.resolve("AAPL")
    with pytest.raises(type(error)):
        edgar.fetch(AAPL, None)


def test_fake_edgar_can_fail_the_fetch_only() -> None:
    edgar = FakeEdgar(fetch_raises=SourceUnavailable("down"))

    assert edgar.resolve("AAPL").cik == "0000320193"
    with pytest.raises(SourceUnavailable):
        edgar.fetch(AAPL, None)


def test_fake_prices_returns_the_recorded_rows() -> None:
    rows = FakePrices().fetch(AAPL, None).rows

    assert rows[0].date == date(2025, 10, 8)
    assert str(rows[0].close) == "258.06"


def test_fake_prices_returns_only_rows_after_since() -> None:
    everything = FakePrices().fetch(AAPL, None).rows
    since = everything[10].date

    later = FakePrices().fetch(AAPL, since).rows

    assert later == everything[11:]


def test_fake_prices_raises_what_it_is_told_to() -> None:
    with pytest.raises(SourceUnavailable):
        FakePrices(raises=SourceUnavailable("down")).fetch(AAPL, None)


def test_fake_prices_remember_what_they_were_asked_for() -> None:
    prices = FakePrices()

    prices.fetch(AAPL, None)
    prices.fetch(AAPL, date(2025, 11, 3))

    assert prices.calls == [None, date(2025, 11, 3)]


def test_fake_prices_serve_the_recorded_split_history_whatever_since_is() -> None:
    expected = [SplitRow(date(2014, 6, 9), Decimal("7")), SplitRow(date(2020, 8, 31), Decimal("4"))]

    for since in (None, date(2026, 1, 1)):
        splits = FakePrices().fetch(AAPL, since).splits
        assert len(splits) == 5
        assert [s for s in splits if s.effective_date.year in (2014, 2020)] == expected
        assert splits == sorted(splits, key=lambda s: s.effective_date)


def test_fake_prices_have_no_splits_for_a_ticker_without_a_splits_file() -> None:
    from .fakes import _splits

    assert _splits("NOSUCH") == ()
