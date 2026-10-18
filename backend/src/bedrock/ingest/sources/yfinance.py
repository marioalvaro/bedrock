from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar, cast

import pandas as pd
import yfinance as yf

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
