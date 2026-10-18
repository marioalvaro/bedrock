"""Normalization adjustments of a followed company: CRUD with validation."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.mapping.config import is_adjustable
from bedrock.models.adjustment import CATEGORIES, Adjustment
from bedrock.models.company import Company
from bedrock.repositories import adjustments as repo
from bedrock.services.errors import AdjustmentNotFound, InvalidAdjustment
from bedrock.services.statements import canonical_items, fiscal_periods
from bedrock.statements.normalize import AppliedAdjustment

__all__ = [
    "AdjustmentInput",
    "CellAdjustment",
    "cell_adjustments",
    "label_of",
    "AdjustmentNotFound",
    "InvalidAdjustment",
    "create_adjustment",
    "delete_adjustment",
    "list_adjustments",
    "update_adjustment",
]

_PERIOD_ORDER = {"FY": 0, "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}

# SQLite stores `adjustment.amount` (Numeric) as a double (docs/Gotcha.md G15). Every integer below
# 10**15 < 2**53 is exact in a double, so a bound at 10**15 means the stored figure is the typed one
# and an unchanged edit form passes validation again. A larger magnitude is rounded (a value just
# under 10**18 reads back as 10**18) and, at the extreme, could read back as Infinity.
AMOUNT_LIMIT = Decimal(10) ** 15


@dataclass(frozen=True)
class AdjustmentInput:
    canonical_code: str
    fiscal_year: int
    fiscal_period: str  # FY, Q1..Q4
    amount: Decimal  # USD units, displayed sign convention
    category: str
    reason: str


@dataclass(frozen=True)
class CellAdjustment:
    """An adjustment that changes a statement cell; `via` is the adjusted line when the cell got
    the change through propagation, else None."""

    adjustment: Adjustment
    via: str | None


def label_of(code: str) -> str:
    return next((i.label for i in canonical_items() if i.code == code), code)


def cell_adjustments(
    session: Session, company: Company, applied: Sequence[AppliedAdjustment]
) -> list[CellAdjustment]:
    """The stored rows behind a cell's applied adjustments, in the order they were applied."""
    stored = {a.id: a for a in repo.list_for(session, company.id)}
    return [
        CellAdjustment(stored[a.adjustment_id], a.via) for a in applied if a.adjustment_id in stored
    ]


def list_adjustments(session: Session, company: Company) -> list[Adjustment]:
    """By fiscal year, then period (FY, Q1..Q4), then id."""
    return sorted(
        repo.list_for(session, company.id),
        key=lambda a: (a.fiscal_year, _PERIOD_ORDER.get(a.fiscal_period, 9), a.id),
    )


def create_adjustment(
    session: Session, company: Company, data: AdjustmentInput, now: datetime
) -> Adjustment:
    _validate(session, company, data)
    stamp = _naive_utc(now)
    added = repo.add(
        session,
        Adjustment(
            company_id=company.id,
            created_at=stamp,
            updated_at=stamp,
            **_fields(data),
        ),
    )
    adjustment_id = added.id
    session.commit()
    return _reloaded(session, company, adjustment_id)


def update_adjustment(
    session: Session, company: Company, adjustment_id: int, data: AdjustmentInput, now: datetime
) -> Adjustment:
    stored = _stored(session, company, adjustment_id)
    _validate(session, company, data)
    for name, value in _fields(data).items():
        setattr(stored, name, value)
    stored.updated_at = _naive_utc(now)
    session.commit()
    return _reloaded(session, company, adjustment_id)


def delete_adjustment(session: Session, company: Company, adjustment_id: int) -> None:
    repo.delete(session, _stored(session, company, adjustment_id))
    session.commit()


def _reloaded(session: Session, company: Company, adjustment_id: int) -> Adjustment:
    """The stored row after a commit (which expires it), with a plain-decimal amount."""
    reloaded = repo.get(session, company.id, adjustment_id)
    assert reloaded is not None
    return reloaded


def _stored(session: Session, company: Company, adjustment_id: int) -> Adjustment:
    stored = repo.get(session, company.id, adjustment_id)
    if stored is None:
        raise AdjustmentNotFound(str(adjustment_id))
    return stored


def _fields(data: AdjustmentInput) -> dict[str, object]:
    return {
        "canonical_code": data.canonical_code,
        "fiscal_year": data.fiscal_year,
        "fiscal_period": data.fiscal_period,
        "amount": data.amount,
        "category": data.category,
        "reason": data.reason.strip(),
    }


def _validate(session: Session, company: Company, data: AdjustmentInput) -> None:
    item = next((i for i in canonical_items() if i.code == data.canonical_code), None)
    if item is None:
        raise InvalidAdjustment(f"Unknown line item {data.canonical_code!r}")
    if not is_adjustable(item):
        raise InvalidAdjustment(f"{item.label} cannot be adjusted: adjust one of its components")
    if data.category not in CATEGORIES:
        raise InvalidAdjustment(f"Unknown category {data.category!r}; use one of {CATEGORIES}")
    if not data.reason.strip():
        raise InvalidAdjustment("An adjustment needs a reason")
    if not data.amount.is_finite():
        raise InvalidAdjustment("The amount must be a finite number")
    if abs(data.amount) >= AMOUNT_LIMIT:
        raise InvalidAdjustment(f"The amount is too large: it must be below {AMOUNT_LIMIT:,} USD")
    if (data.fiscal_year, data.fiscal_period) not in fiscal_periods(session, company):
        raise InvalidAdjustment(
            f"FY{data.fiscal_year} {data.fiscal_period} is not a fiscal period of {company.ticker}"
        )


def _naive_utc(moment: datetime) -> datetime:
    # SQLite keeps no time zone: the columns hold UTC without one.
    return moment.astimezone(UTC).replace(tzinfo=None)
