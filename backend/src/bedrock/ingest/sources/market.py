"""The market series behind the valuation's discount-rate defaults (docs/erd/data.md "Market
series"): the 10-year Treasury yield (FRED `DGS10` with a key, else yfinance `^TNX`), the
Damodaran implied ERP off his home page, and the S&P 500 monthly closes for beta."""

from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar, cast

import httpx
import pandas as pd
import yfinance as yf

from bedrock.ingest.protocol import SeriesPayload, SourceUnavailable
from bedrock.valuation.market import parse_damodaran_erp

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
DAMODARAN_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm"
_TIMEOUT_SECONDS = 20.0
_PLACES = 4


class MarketSource:
    name: ClassVar[str] = "market"

    def __init__(self, fred_api_key: str | None, client: httpx.Client | None = None) -> None:
        self._fred_api_key = fred_api_key
        self._client = client or httpx.Client(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "bedrock (personal research tool)"},
        )

    def risk_free(self, today: date) -> SeriesPayload:
        if self._fred_api_key:
            return SeriesPayload(
                "DGS10", "10-year Treasury yield", "daily", "fred", self._fred(today)
            )
        rows = _closes("^TNX", period="1mo")
        return SeriesPayload("^TNX", "10-year Treasury yield", "daily", "yfinance", rows)

    def erp(self, today: date) -> SeriesPayload:
        try:
            response = self._client.get(DAMODARAN_URL)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise SourceUnavailable(f"Damodaran ERP: {error}") from error
        found = parse_damodaran_erp(response.text)
        if found is None:
            raise SourceUnavailable("Damodaran ERP: the implied ERP line is not on the page")
        return SeriesPayload(
            "DAMODARAN_ERP", "Damodaran implied ERP", "monthly", "damodaran", [found]
        )

    def index(self, today: date) -> SeriesPayload:
        rows = _closes("^GSPC", period="6y", interval="1mo", auto_adjust=False)
        return SeriesPayload("^GSPC", "S&P 500", "monthly", "yfinance", rows)

    def _fred(self, today: date) -> list[tuple[date, Decimal]]:
        params = {
            "series_id": "DGS10",
            "api_key": cast(str, self._fred_api_key),
            "file_type": "json",
            "observation_start": (today - timedelta(days=31)).isoformat(),
        }
        try:
            response = self._client.get(FRED_URL, params=params)
            response.raise_for_status()
            observations = response.json()["observations"]
        except (httpx.HTTPError, ValueError, KeyError) as error:
            raise SourceUnavailable(f"FRED DGS10: {error}") from error
        rows = [
            (date.fromisoformat(o["date"]), Decimal(o["value"]))
            for o in observations
            if o.get("value") not in (None, ".", "")
        ]
        if not rows:
            raise SourceUnavailable("FRED DGS10: no observations")
        return rows


def _closes(symbol: str, **history: object) -> list[tuple[date, Decimal]]:
    try:
        frame = yf.Ticker(symbol).history(**history)
    except Exception as error:
        raise SourceUnavailable(f"yfinance {symbol}: {error}") from error
    rows = (
        [
            (cast(pd.Timestamp, day).date(), Decimal(str(round(float(close), _PLACES))))
            for day, close in frame["Close"].items()
            if not pd.isna(close)
        ]
        if "Close" in frame
        else []
    )
    if not rows:
        raise SourceUnavailable(f"yfinance {symbol}: no data")
    return rows
