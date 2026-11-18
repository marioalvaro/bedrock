from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar, cast

import pandas as pd
import yfinance as yf

from bedrock.analysis.consensus import (
    ConsensusRow,
    EpsHistoryRow,
    history_from_frame,
    rows_from_frames,
)
from bedrock.ingest.protocol import CompanyRef, PricePayload, PriceRow, SourceUnavailable, SplitRow

# yfinance prices are float32-derived; four places keeps the cents and drops the noise.
_PRICE_PLACES = 4


class YFinanceSource:
    name: ClassVar[str] = "yfinance"

    def fetch(self, company: CompanyRef, since: date | None) -> PricePayload:
        """Daily unadjusted prices (with `Adj Close`) after `since`, or all history, plus the
        full split history."""
        try:
            ticker = yf.Ticker(company.ticker)
            frame = ticker.history(
                period="max" if since is None else None,
                start=None if since is None else since + timedelta(days=1),
                auto_adjust=False,
                actions=False,
            )
            return PricePayload(rows=_rows(frame), splits=_splits(ticker.splits))
        except Exception as error:
            raise SourceUnavailable(f"yfinance {company.ticker}: {error}") from error


def _rows(frame: pd.DataFrame) -> list[PriceRow]:
    """One row per day that has a price; Yahoo can list the current day with its volume
    before the close is known (NaN), and a later refresh picks that day up."""
    if not frame.empty:
        frame = frame.dropna(subset=["Close", "Adj Close"])
    return [
        PriceRow(
            date=cast(pd.Timestamp, day).date(),
            close=_price(row["Close"]),
            adj_close=_price(row["Adj Close"]),
            volume=int(row["Volume"]),
        )
        for day, row in frame.iterrows()
    ]


def _price(value: float) -> Decimal:
    return Decimal(str(round(float(value), _PRICE_PLACES)))


def _splits(series: pd.Series) -> list[SplitRow]:
    """Split ratios by effective date, oldest first; yfinance reports 0 for no split."""
    return [
        SplitRow(effective_date=cast(pd.Timestamp, day).date(), ratio=Decimal(str(float(ratio))))
        for day, ratio in series.sort_index().items()
        if float(ratio) != 0
    ]


class YFinanceConsensus:
    """Yahoo's analyst consensus: the `revenue_estimate` and `earnings_estimate` frames, and the
    `earnings_history` of past quarters."""

    def fetch(self, company: CompanyRef) -> list[ConsensusRow]:
        try:
            ticker = yf.Ticker(company.ticker)
            return rows_from_frames(ticker.revenue_estimate, ticker.earnings_estimate)
        except Exception as error:
            raise SourceUnavailable(f"yfinance consensus {company.ticker}: {error}") from error

    def history(self, company: CompanyRef) -> list[EpsHistoryRow]:
        """Yahoo's `earnings_history`: the EPS average before each of the last reports."""
        try:
            return history_from_frame(yf.Ticker(company.ticker).earnings_history)
        except Exception as error:
            raise SourceUnavailable(
                f"yfinance earnings history {company.ticker}: {error}"
            ) from error
