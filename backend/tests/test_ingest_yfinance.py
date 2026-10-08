from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources.yfinance import YFinanceSource

CSV = Path(__file__).parent / "fixtures" / "yfinance" / "AAPL.csv"
AAPL = CompanyRef("AAPL", "0000320193")


class FakeTicker:
    calls: list[dict[str, Any]] = []

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, **kwargs: Any) -> pd.DataFrame:
        FakeTicker.calls.append({"symbol": self.symbol, **kwargs})
        return pd.read_csv(CSV, index_col="Date", parse_dates=True)


@pytest.fixture(autouse=True)
def _fake_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTicker.calls = []
    monkeypatch.setattr("yfinance.Ticker", FakeTicker)


def test_the_fixture_csv_becomes_price_rows() -> None:
    frame = pd.read_csv(CSV, index_col="Date", parse_dates=True)

    rows = YFinanceSource().fetch(AAPL, None).rows

    assert len(rows) == len(frame)
    first = rows[0]
    assert first.date == frame.index[0].date()
    assert first.close == Decimal(str(round(frame["Close"].iloc[0], 4)))
    assert first.adj_close == Decimal(str(round(frame["Adj Close"].iloc[0], 4)))
    assert first.volume == int(frame["Volume"].iloc[0])
    assert isinstance(first.volume, int)


def test_a_first_fetch_asks_for_the_maximum_history_unadjusted() -> None:
    YFinanceSource().fetch(AAPL, None)

    assert FakeTicker.calls == [
        {
            "symbol": "AAPL",
            "period": "max",
            "start": None,
            "auto_adjust": False,
            "actions": False,
        }
    ]


def test_a_later_fetch_starts_the_day_after_the_last_stored_date() -> None:
    YFinanceSource().fetch(AAPL, date(2026, 10, 7))

    (call,) = FakeTicker.calls
    assert call["start"] == date(2026, 10, 8)
    assert call["period"] is None


def test_any_exception_becomes_source_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def __init__(self, symbol: str) -> None: ...

        def history(self, **kwargs: Any) -> pd.DataFrame:
            raise RuntimeError("rate limited")

    monkeypatch.setattr("yfinance.Ticker", Broken)

    with pytest.raises(SourceUnavailable, match="rate limited"):
        YFinanceSource().fetch(AAPL, None)


def test_an_empty_frame_is_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    class Empty:
        def __init__(self, symbol: str) -> None: ...

        def history(self, **kwargs: Any) -> pd.DataFrame:
            return pd.DataFrame()

    monkeypatch.setattr("yfinance.Ticker", Empty)

    assert YFinanceSource().fetch(AAPL, date(2026, 10, 7)).rows == []
