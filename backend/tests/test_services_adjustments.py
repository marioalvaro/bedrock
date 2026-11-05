"""Adjustment CRUD: validation against the canonical items and the company's fiscal calendar."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.models.adjustment import Adjustment
from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.services.adjustments import (
    AdjustmentInput,
    create_adjustment,
    delete_adjustment,
    list_adjustments,
    update_adjustment,
)
from bedrock.services.errors import AdjustmentNotFound, InvalidAdjustment, user_message

from .seed import fake_sources, follow

NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)

SGA = AdjustmentInput(
    canonical_code="sga",
    fiscal_year=2024,
    fiscal_period="FY",
    amount=Decimal("-1000000000"),
    category="one-off",
    reason="Legal settlement",
)


@pytest.fixture
def aapl_db(seed_db: Callable[..., None]) -> None:
    seed_db("AAPL")


@pytest.fixture
def aapl(aapl_db: None, db_session: Session) -> Company:
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    return company


def test_create_stores_the_adjustment_with_the_clock_time_and_a_plain_amount(
    db_session: Session, aapl: Company
) -> None:
    created = create_adjustment(db_session, aapl, SGA, NOW)

    assert created.id is not None
    assert (created.canonical_code, created.fiscal_year, created.fiscal_period) == (
        "sga",
        2024,
        "FY",
    )
    assert str(created.amount) == "-1000000000"  # no Numeric padding (G15)
    assert created.created_at == created.updated_at == datetime(2026, 10, 8, 14, 30)  # naive UTC
    assert db_session.execute(select(Adjustment)).scalars().one().reason == "Legal settlement"


def test_the_reason_is_trimmed(db_session: Session, aapl: Company) -> None:
    created = create_adjustment(db_session, aapl, replace(SGA, reason="  One-off  "), NOW)

    assert created.reason == "One-off"


def test_list_is_ordered_by_year_then_period_then_id(db_session: Session, aapl: Company) -> None:
    for year, period in ((2024, "Q2"), (2023, "FY"), (2024, "FY"), (2024, "Q1"), (2024, "Q2")):
        create_adjustment(
            db_session, aapl, replace(SGA, fiscal_year=year, fiscal_period=period), NOW
        )

    listed = [(a.fiscal_year, a.fiscal_period, a.id) for a in list_adjustments(db_session, aapl)]

    assert [(y, p) for y, p, _ in listed] == [
        (2023, "FY"),
        (2024, "FY"),
        (2024, "Q1"),
        (2024, "Q2"),
        (2024, "Q2"),
    ]
    assert listed[3][2] < listed[4][2]


def test_update_replaces_the_fields_and_moves_updated_at_only(
    db_session: Session, aapl: Company
) -> None:
    created = create_adjustment(db_session, aapl, SGA, NOW)

    changed = update_adjustment(
        db_session,
        aapl,
        created.id,
        replace(SGA, amount=Decimal("-5"), category="reclass", reason="Moved to COGS"),
        LATER,
    )

    assert (changed.id, changed.amount, changed.category, changed.reason) == (
        created.id,
        Decimal("-5"),
        "reclass",
        "Moved to COGS",
    )
    assert changed.created_at == datetime(2026, 10, 8, 14, 30)
    assert changed.updated_at == datetime(2026, 10, 8, 16, 30)


def test_delete_removes_the_adjustment(db_session: Session, aapl: Company) -> None:
    created = create_adjustment(db_session, aapl, SGA, NOW)

    delete_adjustment(db_session, aapl, created.id)

    assert list_adjustments(db_session, aapl) == []


def test_an_unknown_id_is_not_found(db_session: Session, aapl: Company) -> None:
    with pytest.raises(AdjustmentNotFound):
        update_adjustment(db_session, aapl, 999, SGA, NOW)
    with pytest.raises(AdjustmentNotFound):
        delete_adjustment(db_session, aapl, 999)


def test_another_companys_adjustment_is_not_found(db_session: Session, aapl: Company) -> None:
    other = follow(db_session, fake_sources().edgar, "MSFT")
    theirs = create_adjustment(db_session, aapl, SGA, NOW)

    with pytest.raises(AdjustmentNotFound):
        update_adjustment(db_session, other, theirs.id, SGA, NOW)
    with pytest.raises(AdjustmentNotFound):
        delete_adjustment(db_session, other, theirs.id)
    assert len(list_adjustments(db_session, aapl)) == 1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"canonical_code": "nowhere"}, "Unknown line item"),
        ({"canonical_code": "total_debt"}, "cannot be adjusted"),
        ({"canonical_code": "free_cash_flow"}, "cannot be adjusted"),
        ({"canonical_code": "total_operating_costs"}, "cannot be adjusted"),
        ({"canonical_code": "eps_diluted"}, "cannot be adjusted"),
        ({"canonical_code": "shares_diluted"}, "cannot be adjusted"),
        ({"canonical_code": "goodwill_impairment"}, "cannot be adjusted"),
        ({"fiscal_year": 1990}, "not a fiscal period"),
        ({"fiscal_period": "Q5"}, "not a fiscal period"),
        ({"fiscal_period": "TTM"}, "not a fiscal period"),
        ({"reason": ""}, "reason"),
        ({"reason": "   "}, "reason"),
        ({"category": "whim"}, "category"),
    ],
)
def test_invalid_adjustments_are_rejected_and_nothing_is_stored(
    db_session: Session, aapl: Company, change: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidAdjustment) as info:
        create_adjustment(db_session, aapl, replace(SGA, **change), NOW)  # type: ignore[arg-type]

    assert message in user_message(info.value)
    assert list_adjustments(db_session, aapl) == []


def test_update_validates_like_create_and_keeps_the_stored_row(
    db_session: Session, aapl: Company
) -> None:
    created = create_adjustment(db_session, aapl, SGA, NOW)

    with pytest.raises(InvalidAdjustment):
        update_adjustment(
            db_session, aapl, created.id, replace(SGA, canonical_code="total_debt"), LATER
        )

    assert list_adjustments(db_session, aapl)[0].canonical_code == "sga"


UNSTORABLE_AMOUNTS = [
    pytest.param(Decimal("Infinity"), "finite", id="infinity"),
    pytest.param(Decimal("-Infinity"), "finite", id="minus-infinity"),
    pytest.param(Decimal("NaN"), "finite", id="nan"),
    pytest.param(Decimal("1e400"), "too large", id="1e400"),
    pytest.param(Decimal("1e15"), "too large", id="1e15"),
    pytest.param(Decimal("-1e15"), "too large", id="minus-1e15"),
    pytest.param(Decimal("1e18"), "too large", id="1e18"),
    pytest.param(Decimal("-1e18"), "too large", id="minus-1e18"),
]


@pytest.mark.parametrize(("amount", "message"), UNSTORABLE_AMOUNTS)
def test_a_non_finite_or_unbounded_amount_is_rejected_on_create_and_nothing_is_stored(
    db_session: Session, aapl: Company, amount: Decimal, message: str
) -> None:
    with pytest.raises(InvalidAdjustment) as info:
        create_adjustment(db_session, aapl, replace(SGA, amount=amount), NOW)

    assert message in user_message(info.value)
    assert list_adjustments(db_session, aapl) == []


@pytest.mark.parametrize(("amount", "message"), UNSTORABLE_AMOUNTS)
def test_a_non_finite_or_unbounded_amount_is_rejected_on_update_and_keeps_the_stored_row(
    db_session: Session, aapl: Company, amount: Decimal, message: str
) -> None:
    created = create_adjustment(db_session, aapl, SGA, NOW)

    with pytest.raises(InvalidAdjustment) as info:
        update_adjustment(db_session, aapl, created.id, replace(SGA, amount=amount), LATER)

    assert message in user_message(info.value)
    (kept,) = list_adjustments(db_session, aapl)
    assert (kept.amount, kept.updated_at) == (Decimal("-1000000000"), datetime(2026, 10, 8, 14, 30))


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("123456789012345"),
        Decimal("-999999999999999"),
        Decimal(
            "123456789.5"
        ),  # a dyadic fraction: exact in a REAL (non-dyadic cents are not, G15)
    ],
)
def test_an_amount_inside_the_bound_round_trips_exactly(
    db_session: Session, aapl: Company, amount: Decimal
) -> None:
    created = create_adjustment(db_session, aapl, replace(SGA, amount=amount), NOW)

    assert created.amount == amount
    (listed,) = list_adjustments(db_session, aapl)
    assert (listed.id, listed.amount) == (created.id, amount)


def test_a_stored_amount_can_be_saved_again_unchanged(db_session: Session, aapl: Company) -> None:
    amount = Decimal("-999999999999999")
    created = create_adjustment(db_session, aapl, replace(SGA, amount=amount), NOW)
    (listed,) = list_adjustments(db_session, aapl)

    updated = update_adjustment(
        db_session, aapl, created.id, replace(SGA, amount=listed.amount), LATER
    )

    assert updated.amount == amount


def test_a_company_without_data_has_no_fiscal_periods(db_session: Session) -> None:
    empty = follow(db_session, fake_sources().edgar, "MSFT")

    with pytest.raises(InvalidAdjustment, match="not a fiscal period"):
        create_adjustment(db_session, empty, SGA, NOW)


def test_removing_the_company_removes_its_adjustments(db_session: Session, aapl: Company) -> None:
    from bedrock.services.companies import remove_company

    create_adjustment(db_session, aapl, SGA, NOW)

    remove_company(db_session, "AAPL")

    assert db_session.execute(select(Adjustment)).scalars().all() == []
