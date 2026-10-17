"""Quality-of-earnings flags, capital allocation and off-balance-sheet items of a followed
company (FR-ANL-05, FR-ANL-06). Flags and capital allocation are on the reported basis."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.analysis import capital_allocation as capital_engine
from bedrock.analysis.capital_allocation import CapitalAllocationTable
from bedrock.analysis.qoe import FlagTable, evaluate_flags
from bedrock.models.company import Company
from bedrock.models.off_balance_item import KINDS, OffBalanceItem
from bedrock.ratios.calculator import RatioFreq
from bedrock.repositories import off_balance_items as repo
from bedrock.services import qoe
from bedrock.services.adjustments import AMOUNT_LIMIT
from bedrock.services.errors import InvalidOffBalanceItem, OffBalanceItemNotFound
from bedrock.services.ratios import ratio_inputs


@dataclass(frozen=True)
class OffBalanceInput:
    kind: str  # one of models/off_balance_item.py::KINDS
    description: str
    amount: Decimal | None  # USD units
    as_of: date
    source_note: str | None


@dataclass(frozen=True)
class Flags:
    table: FlagTable
    off_balance_items: list[OffBalanceItem]  # as `list_off_balance_items`


def flags(session: Session, company: Company, freq: RatioFreq) -> Flags:
    """`evaluate_flags` on the reported `services/ratios.py::ratio_inputs` with the effective
    rules (`services/qoe.py::effective`), plus the company's off-balance-sheet items."""
    inputs = ratio_inputs(session, company, freq, "reported")
    table = evaluate_flags(inputs, qoe.effective(session), freq)
    return Flags(table=table, off_balance_items=list_off_balance_items(session, company))


def capital_allocation(
    session: Session, company: Company, freq: RatioFreq
) -> CapitalAllocationTable:
    """`analysis/capital_allocation.py::capital_allocation` on the reported `ratio_inputs`."""
    inputs = ratio_inputs(session, company, freq, "reported")
    return capital_engine.capital_allocation(inputs, freq)


def list_off_balance_items(session: Session, company: Company) -> list[OffBalanceItem]:
    """Newest `as_of` first, then newest id first."""
    return repo.list_for(session, company.id)


def create_off_balance_item(
    session: Session, company: Company, data: OffBalanceInput, now: datetime
) -> OffBalanceItem:
    """Validates, stores (description and source note stripped; an empty source note becomes
    None) and commits. Raises InvalidOffBalanceItem for an unknown kind, an empty description, or
    an amount that is not finite or whose magnitude is >= `services/adjustments.py::AMOUNT_LIMIT`
    (docs/Gotcha.md G15)."""
    _validate(data)
    stamp = _naive_utc(now)
    added = repo.add(
        session,
        OffBalanceItem(company_id=company.id, created_at=stamp, updated_at=stamp, **_fields(data)),
    )
    item_id = added.id
    session.commit()
    return _reloaded(session, company, item_id)


def update_off_balance_item(
    session: Session, company: Company, item_id: int, data: OffBalanceInput, now: datetime
) -> OffBalanceItem:
    """Replaces every field and `updated_at`, and commits. Raises OffBalanceItemNotFound (checked
    first) and InvalidOffBalanceItem as in create."""
    stored = _stored(session, company, item_id)
    _validate(data)
    for name, value in _fields(data).items():
        setattr(stored, name, value)
    stored.updated_at = _naive_utc(now)
    session.commit()
    return _reloaded(session, company, item_id)


def delete_off_balance_item(session: Session, company: Company, item_id: int) -> None:
    """Raises OffBalanceItemNotFound for an unknown id or another company's id."""
    repo.delete(session, _stored(session, company, item_id))
    session.commit()


def _stored(session: Session, company: Company, item_id: int) -> OffBalanceItem:
    stored = repo.get(session, company.id, item_id)
    if stored is None:
        raise OffBalanceItemNotFound(str(item_id))
    return stored


def _reloaded(session: Session, company: Company, item_id: int) -> OffBalanceItem:
    """The stored row after a commit (which expires it), with a plain-decimal amount."""
    reloaded = repo.get(session, company.id, item_id)
    assert reloaded is not None
    return reloaded


def _fields(data: OffBalanceInput) -> dict[str, object]:
    note = data.source_note.strip() if data.source_note is not None else ""
    return {
        "kind": data.kind,
        "description": data.description.strip(),
        "amount": data.amount,
        "as_of": data.as_of,
        "source_note": note or None,
    }


def _validate(data: OffBalanceInput) -> None:
    if data.kind not in KINDS:
        raise InvalidOffBalanceItem(f"Unknown kind {data.kind!r}; use one of {KINDS}")
    if not data.description.strip():
        raise InvalidOffBalanceItem("An off-balance-sheet item needs a description")
    if data.amount is None:
        return
    if not data.amount.is_finite():
        raise InvalidOffBalanceItem("The amount must be a finite number")
    if abs(data.amount) >= AMOUNT_LIMIT:
        raise InvalidOffBalanceItem(
            f"The amount is too large: it must be below {AMOUNT_LIMIT:,} USD"
        )


def _naive_utc(moment: datetime) -> datetime:
    # SQLite keeps no time zone: the columns hold UTC without one.
    return moment.astimezone(UTC).replace(tzinfo=None)
