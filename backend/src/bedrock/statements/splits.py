"""Split adjustment of share and per-share values. Pure.

An XBRL value is stated in the shares of the day its filing was filed, so a later split changes
the unit of the figure. The split factor of a value is the product of the ratios of the splits
effective after its filing date; shares are multiplied by it and per-share amounts divided.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

import pandas as pd

SHARES = "shares"
PER_SHARE = "USD/shares"
_PLACES = Decimal(1).scaleb(-10)  # 10 decimal places


class Split(Protocol):
    """A stock split: `ratio` new shares per old share (4 for a 4-for-1)."""

    @property
    def effective_date(self) -> date: ...

    @property
    def ratio(self) -> Decimal: ...


def split_adjust(canonical: pd.DataFrame, actions: Sequence[Split]) -> pd.DataFrame:
    """A new frame with `value` split-adjusted, plus `split_factor` (1 when none),
    `split_dates` (the splits applied, oldest first) and `reported_value` (as reported).
    USD rows keep a factor of 1; only share and per-share rows are adjusted."""
    out = canonical.copy()
    ordered = sorted(actions, key=lambda a: a.effective_date)
    factors: list[Decimal] = []
    dates: list[tuple[date, ...]] = []
    values: list[Decimal] = []
    for r in canonical.to_dict("records"):
        applied = _applied(r["filed_at"], ordered) if r["unit"] in (SHARES, PER_SHARE) else []
        factor = _product(applied)
        factors.append(factor)
        dates.append(tuple(a.effective_date for a in applied))
        values.append(_adjust(r["value"], r["unit"], factor))
    out["reported_value"] = pd.Series(canonical["value"].tolist(), index=out.index, dtype="object")
    out["split_factor"] = pd.Series(factors, index=out.index, dtype="object")
    out["split_dates"] = pd.Series(dates, index=out.index, dtype="object")
    out["value"] = pd.Series(values, index=out.index, dtype="object")
    return out[[*canonical.columns, "split_factor", "split_dates", "reported_value"]]


def split_factor(filed_at: date, actions: Sequence[Split]) -> Decimal:
    """The product of the ratios of the splits effective after `filed_at`: how many of today's
    shares one share of that filing's day is worth."""
    return _product(_applied(filed_at, actions))


def _applied(filed_at: date, actions: Sequence[Split]) -> list[Split]:
    return [a for a in actions if a.effective_date > filed_at]


def _product(actions: Sequence[Split]) -> Decimal:
    factor = Decimal(1)
    for a in actions:
        factor *= a.ratio
    return factor


def _adjust(value: Decimal, unit: str, factor: Decimal) -> Decimal:
    if factor == 1:
        return value
    if unit == SHARES:
        return value * factor
    return per_share(value / factor)


def per_share(value: Decimal) -> Decimal:
    """A per-share amount to 10 decimal places, trailing zeros dropped."""
    return _plain(value.quantize(_PLACES))


def _plain(value: Decimal) -> Decimal:
    """Drop trailing zeros without exponent notation."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Decimal(text or "0")
