"""Market-based discount-rate defaults (docs/erd/valuation.md "Market defaults"): the current
risk-free rate, the Damodaran implied equity risk premium and a 5-year monthly beta, as the
defaults of `risk_free_rate`, `equity_risk_premium` and `beta`. Pure: the service reads the
stored series and passes them in."""

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal

from bedrock.valuation.inputs import input_def

BETA_MONTHS = 60
MIN_BETA_MONTHS = 36
_RATE_PLACES = Decimal("0.0001")
_BETA_PLACES = Decimal("0.01")

_TAG = re.compile(r"<[^>]+>")
_ERP = re.compile(r"Implied ERP on\s+([A-Z][a-z]+ \d{1,2}, \d{4})\s*=\s*(\d+(?:\.\d+)?)\s*%")


def parse_damodaran_erp(html: str) -> tuple[date, Decimal] | None:
    """The date and percentage of the "Implied ERP on <date> = x%" line of Damodaran's home
    page (tags removed first: the figure is split by markup), or None when it is not there."""
    text = " ".join(_TAG.sub("", html).split())
    found = _ERP.search(text)
    if found is None:
        return None
    try:
        day = datetime.strptime(found.group(1), "%B %d, %Y").date()
    except ValueError:
        return None
    return day, Decimal(found.group(2))


Month = tuple[int, int]


def month_end_closes(closes: Iterable[tuple[date, Decimal]]) -> dict[Month, Decimal]:
    """Each month's last close, by (year, month)."""
    latest: dict[Month, tuple[date, Decimal]] = {}
    for day, close in closes:
        key = (day.year, day.month)
        if key not in latest or day > latest[key][0]:
            latest[key] = (day, close)
    return {key: close for key, (_, close) in sorted(latest.items())}


def _returns(ends: Mapping[Month, Decimal]) -> dict[Month, Decimal]:
    """The return of each month over the month before it (consecutive months only)."""
    out: dict[Month, Decimal] = {}
    keys = sorted(ends)
    for prev, cur in zip(keys, keys[1:], strict=False):
        consecutive = (cur[0] * 12 + cur[1]) - (prev[0] * 12 + prev[1]) == 1
        if consecutive and ends[prev] > 0:
            out[cur] = ends[cur] / ends[prev] - 1
    return out


def beta(
    stock: Iterable[tuple[date, Decimal]], index: Iterable[tuple[date, Decimal]]
) -> Decimal | None:
    """The 5-year monthly beta: cov(stock, index) / var(index) over the latest BETA_MONTHS
    complete months both series have (the month of the stock's latest close is partial and left
    out), to two places; None with fewer than MIN_BETA_MONTHS or an index that never moved."""
    stock_ends = month_end_closes(stock)
    if not stock_ends:
        return None
    current = max(stock_ends)
    s = _returns({k: v for k, v in stock_ends.items() if k < current})
    i = _returns({k: v for k, v in month_end_closes(index).items() if k < current})
    months = sorted(set(s) & set(i))[-BETA_MONTHS:]
    if len(months) < MIN_BETA_MONTHS:
        return None
    n = Decimal(len(months))
    mean_s = sum((s[m] for m in months), Decimal(0)) / n
    mean_i = sum((i[m] for m in months), Decimal(0)) / n
    cov = sum(((s[m] - mean_s) * (i[m] - mean_i) for m in months), Decimal(0))
    var = sum(((i[m] - mean_i) ** 2 for m in months), Decimal(0))
    if var == 0:
        return None
    return (cov / var).quantize(_BETA_PLACES)


def market_defaults(
    risk_free_pct: Decimal | None, erp_pct: Decimal | None, beta: Decimal | None
) -> dict[str, Decimal]:
    """The market figures as input defaults (percentages to fractions); a missing figure, or one
    outside its input's bounds, is left out so the catalog default stands."""
    found = {
        "risk_free_rate": None if risk_free_pct is None else (risk_free_pct / 100),
        "equity_risk_premium": None if erp_pct is None else (erp_pct / 100),
        "beta": beta,
    }
    out: dict[str, Decimal] = {}
    for code, value in found.items():
        if value is None:
            continue
        value = value.quantize(_BETA_PLACES if code == "beta" else _RATE_PLACES)
        bounds = input_def(code).bounds
        if bounds is not None and not bounds.contains(value):
            continue
        out[code] = value
    return out
