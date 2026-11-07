"""The market source: the risk-free rate (FRED DGS10 with a key, else yfinance ^TNX), the
Damodaran implied ERP and the S&P 500 monthly closes. No network: httpx runs on a mock
transport and yfinance is faked."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from bedrock.ingest.protocol import SourceUnavailable
from bedrock.ingest.sources.market import MarketSource

D = Decimal
DAMODARAN = (Path(__file__).parent / "fixtures" / "market" / "damodaran_home.html").read_text()
TODAY = date(2026, 11, 7)


class FakeTicker:
    calls: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, **kwargs: Any) -> pd.DataFrame:
        FakeTicker.calls.append({"symbol": self.symbol, **kwargs})
        if self.symbol not in FakeTicker.frames:
            raise RuntimeError("no data")
        return FakeTicker.frames[self.symbol]


def _frame(rows: dict[str, float]) -> pd.DataFrame:
    index = pd.to_datetime(list(rows)).tz_localize("America/New_York")
    return pd.DataFrame({"Close": list(rows.values())}, index=index)


@pytest.fixture(autouse=True)
def _fake_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTicker.calls = []
    FakeTicker.frames = {}
    monkeypatch.setattr("yfinance.Ticker", FakeTicker)


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _fred(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "api.stlouisfed.org"
    assert request.url.params["series_id"] == "DGS10"
    assert request.url.params["api_key"] == "k"
    body = {
        "observations": [
            {"date": "2026-11-04", "value": "4.21"},
            {"date": "2026-11-05", "value": "."},  # FRED's missing value
            {"date": "2026-11-06", "value": "4.25"},
        ]
    }
    return httpx.Response(200, text=json.dumps(body))


def test_with_a_fred_key_the_risk_free_rate_is_dgs10() -> None:
    source = MarketSource(fred_api_key="k", client=_client(_fred))

    series = source.risk_free(TODAY)

    assert (series.series_id, series.source, series.frequency) == ("DGS10", "fred", "daily")
    assert series.rows == [(date(2026, 11, 4), D("4.21")), (date(2026, 11, 6), D("4.25"))]


def test_without_a_key_the_risk_free_rate_is_the_10_year_yield_index() -> None:
    FakeTicker.frames["^TNX"] = _frame({"2026-11-05": 4.2312, "2026-11-06": 4.25})
    source = MarketSource(fred_api_key=None, client=_client(lambda r: httpx.Response(500)))

    series = source.risk_free(TODAY)

    assert (series.series_id, series.source) == ("^TNX", "yfinance")
    assert series.rows == [(date(2026, 11, 5), D("4.2312")), (date(2026, 11, 6), D("4.25"))]
    assert FakeTicker.calls[0]["period"] == "1mo"


def test_the_index_is_six_years_of_monthly_closes() -> None:
    FakeTicker.frames["^GSPC"] = _frame({"2026-10-01": 6800.5, "2026-11-01": 6900.25})
    source = MarketSource(fred_api_key=None, client=_client(lambda r: httpx.Response(500)))

    series = source.index(TODAY)

    assert (series.series_id, series.frequency) == ("^GSPC", "monthly")
    assert series.rows == [(date(2026, 10, 1), D("6800.5")), (date(2026, 11, 1), D("6900.25"))]
    assert FakeTicker.calls == [
        {"symbol": "^GSPC", "period": "6y", "interval": "1mo", "auto_adjust": False}
    ]


def test_the_erp_is_read_off_damodaran_s_home_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/New_Home_Page/home.htm")
        return httpx.Response(200, text=DAMODARAN)

    series = MarketSource(fred_api_key=None, client=_client(handler)).erp(TODAY)

    assert (series.series_id, series.frequency) == ("DAMODARAN_ERP", "monthly")
    assert series.rows == [(date(2026, 11, 1), D("4.41"))]


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(503),
        lambda r: httpx.Response(200, text="<html>redesigned</html>"),
    ],
)
def test_an_unreadable_erp_page_is_unavailable(handler: Any) -> None:
    with pytest.raises(SourceUnavailable):
        MarketSource(fred_api_key=None, client=_client(handler)).erp(TODAY)


def test_a_yfinance_failure_or_an_empty_frame_is_unavailable() -> None:
    source = MarketSource(fred_api_key=None, client=_client(lambda r: httpx.Response(500)))
    with pytest.raises(SourceUnavailable):
        source.index(TODAY)  # no frame: the fake raises
    FakeTicker.frames["^TNX"] = _frame({})
    with pytest.raises(SourceUnavailable):
        source.risk_free(TODAY)


def test_a_fred_failure_is_unavailable() -> None:
    source = MarketSource(fred_api_key="k", client=_client(lambda r: httpx.Response(500)))
    with pytest.raises(SourceUnavailable):
        source.risk_free(TODAY)
