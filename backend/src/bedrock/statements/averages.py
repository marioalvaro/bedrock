"""Q4 of the average items (docs/erd/data.md "R2"). Pure.

A weighted-average share count or EPS is reported for a year and for Q1-Q3, never for Q4. Q4 is
rebuilt from them and marked `approximated`: diluted shares are not additive, and rounding errors
in the year and the quarters are multiplied about four times in the remainder.
"""

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal

from bedrock.mapping.config import CanonicalItemDef
from bedrock.statements.cell_types import (
    EMPTY,
    Cell,
    CellKey,
    Derivation,
    DerivationInput,
    RuleWarning,
)
from bedrock.statements.periods import Period
from bedrock.statements.rules import WarningLog
from bedrock.statements.splits import per_share

Look = Callable[[str, str], Cell]  # (code, period key) -> the cell as it stands

SHARES_CODES = ("shares_basic", "shares_diluted")
EPS_SHARES = {"eps_basic": "shares_basic", "eps_diluted": "shares_diluted"}
NET_INCOME_COMMON = "net_income_common"

SHARES_BAND = Decimal("0.20")  # Q4 shares must lie within this fraction of Q3's
EPS_FLOOR = Decimal("0.02")  # the EPS check accepts the larger of this and ...
EPS_RELATIVE = Decimal("0.03")  # ... this fraction of the year's EPS


def q4_average_cells(
    cells: Mapping[CellKey, Cell],
    by_code: Mapping[str, CanonicalItemDef],
    periods: Sequence[Period],
    log: WarningLog,
) -> list[tuple[CellKey, Cell]]:
    """The Q4 cells of the share counts and then of EPS (which divides by the Q4 shares just
    rebuilt), for every year whose Q4 is empty. A result a guard refuses is a warning."""
    by_key = {p.key: p for p in periods}
    found: dict[CellKey, Cell] = {}

    def look(code: str, key: str) -> Cell:
        return found.get((code, key)) or cells.get((code, key), EMPTY)

    q4_periods = [p for p in periods if p.fiscal_period == "Q4"]
    for code in SHARES_CODES:
        if code not in by_code:
            continue
        for q4 in q4_periods:
            if cells.get((code, q4.key), EMPTY).value is not None:
                continue
            cell = _q4_shares(code, q4, by_key, look, log)
            if cell is not None:
                found[(code, q4.key)] = cell
    for code, shares_code in EPS_SHARES.items():
        if code not in by_code or shares_code not in by_code or NET_INCOME_COMMON not in by_code:
            continue
        for q4 in q4_periods:
            if cells.get((code, q4.key), EMPTY).value is not None:
                continue
            cell = _q4_eps(code, shares_code, q4, look, log)
            if cell is not None:
                found[(code, q4.key)] = cell
    return list(found.items())


def _year_keys(q4: Period) -> tuple[str, list[str]]:
    year = f"FY{q4.fiscal_year}"
    return year, [f"{year}Q{n}" for n in (1, 2, 3)]


def _days(period: Period) -> int:
    return (period.end - period.start).days + 1  # both ends count: the four quarters add up to FY


def _q4_shares(
    code: str,
    q4: Period,
    by_key: Mapping[str, Period],
    look: Look,
    log: WarningLog,
) -> Cell | None:
    year_key, quarter_keys = _year_keys(q4)
    year_period = by_key.get(year_key)
    inputs = [look(code, k) for k in (year_key, *quarter_keys)]
    if year_period is None or any(c.value is None for c in inputs):
        return None
    fiscal, q1, q2, q3 = (c.value for c in inputs if c.value is not None)
    weighted = [(q, _days(by_key[k])) for q, k in zip((q1, q2, q3), quarter_keys, strict=True)]
    value = (
        (fiscal * _days(year_period) - sum((q * d for q, d in weighted), Decimal(0))) / _days(q4)
    ).quantize(Decimal(1))
    if value <= 0:
        log.add(_warning("q4_shares", code, q4, value, "Q4 shares are not positive"))
        return None
    if abs(value - q3) > SHARES_BAND * q3:
        log.add(_warning("q4_shares", code, q4, value, "Q4 shares are more than 20% from Q3's"))
        return None
    return Cell(
        value,
        "approximated",
        derivation=Derivation(
            "(FY × days FY - sum of Q × days Q) / days Q4",
            tuple(
                DerivationInput(code, period, c.value)
                for period, c in zip(("FY", "Q1", "Q2", "Q3"), inputs, strict=True)
                if c.value is not None
            ),
        ),
    )


def _q4_eps(
    code: str,
    shares_code: str,
    q4: Period,
    look: Look,
    log: WarningLog,
) -> Cell | None:
    year_key, quarter_keys = _year_keys(q4)
    income = look(NET_INCOME_COMMON, q4.key).value
    shares = look(shares_code, q4.key).value
    parts = [look(code, k).value for k in (year_key, *quarter_keys)]
    if income is None or not shares or any(v is None for v in parts):
        return None
    fiscal, q1, q2, q3 = (v for v in parts if v is not None)
    value = per_share(income / shares)
    remainder = fiscal - q1 - q2 - q3
    if abs(value - remainder) > max(EPS_FLOOR, EPS_RELATIVE * abs(fiscal)):
        log.add(
            _warning(
                "q4_eps",
                code,
                q4,
                value,
                f"Q4 EPS is not within the tolerance of FY - Q1 - Q2 - Q3 ({remainder})",
            )
        )
        return None
    return Cell(
        value,
        "approximated",
        derivation=Derivation(
            f"{NET_INCOME_COMMON} / {shares_code}",
            (
                DerivationInput(NET_INCOME_COMMON, "Q4", income),
                DerivationInput(shares_code, "Q4", shares),
            ),
        ),
    )


def _warning(rule: str, code: str, q4: Period, value: Decimal, reason: str) -> RuleWarning:
    return RuleWarning(rule, code, q4.key, value, reason)
