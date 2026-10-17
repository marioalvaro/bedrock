"""Off-balance-sheet items through the API (FR-ANL-05; AAPL and MSFT fixtures)."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock
from bedrock.models.company import Company
from bedrock.models.off_balance_item import OffBalanceItem
from bedrock.services import analysis
from bedrock.services.analysis import OffBalanceInput
from bedrock.services.errors import InvalidOffBalanceItem

COMPANY = "/api/v1/companies/AAPL"
ITEMS = f"{COMPANY}/off-balance-items"

LEASE = {
    "kind": "lease",
    "description": "Retail store leases not yet commenced",
    "amount": "1500000000",
    "as_of": "2024-09-28",
    "source_note": "Note 10",
}

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def advance(app: FastAPI) -> Callable[[timedelta], None]:
    """Pins the app clock at START; calling the result moves it forward."""
    moment = [START]
    app.dependency_overrides[get_clock] = lambda: moment[0]

    def step(by: timedelta) -> None:
        moment[0] += by

    return step


@pytest.fixture
def aapl_client(advance: Callable[[timedelta], None], authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


# --- guards ----------------------------------------------------------------------------------


def test_every_off_balance_route_requires_a_session(client: TestClient) -> None:
    assert client.get(ITEMS).status_code == 401
    assert client.post(ITEMS, json=LEASE).status_code == 401
    assert client.put(f"{ITEMS}/1", json=LEASE).status_code == 401
    assert client.delete(f"{ITEMS}/1").status_code == 401


def test_an_unfollowed_company_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(ITEMS).status_code == 404
    assert authed_client.post(ITEMS, json=LEASE).status_code == 404
    assert authed_client.put(f"{ITEMS}/1", json=LEASE).status_code == 404
    assert authed_client.delete(f"{ITEMS}/1").status_code == 404


# --- CRUD ------------------------------------------------------------------------------------


def test_a_new_item_is_created_with_the_documented_shape(aapl_client: TestClient) -> None:
    response = aapl_client.post(
        ITEMS, json={**LEASE, "description": "  Store leases  ", "source_note": " Note 10 "}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "kind",
        "description",
        "amount",
        "as_of",
        "source_note",
        "created_at",
        "updated_at",
    }
    assert (body["kind"], body["description"], body["as_of"], body["source_note"]) == (
        "lease",
        "Store leases",
        "2024-09-28",
        "Note 10",
    )
    assert body["amount"] == "1500000000"  # a plain decimal string: no exponent, no padding
    assert body["created_at"].endswith("Z") and body["updated_at"].endswith("Z")
    assert aapl_client.get(ITEMS).json() == [body]


def test_a_fractional_amount_round_trips_without_padding(aapl_client: TestClient) -> None:
    created = aapl_client.post(ITEMS, json={**LEASE, "amount": "-12.5"})

    assert created.json()["amount"] == "-12.5"
    assert [i["amount"] for i in aapl_client.get(ITEMS).json()] == ["-12.5"]


@pytest.mark.parametrize("note", [None, "", "   "])
def test_a_null_amount_and_an_empty_source_note_are_stored_as_null(
    aapl_client: TestClient, note: str | None
) -> None:
    response = aapl_client.post(ITEMS, json={**LEASE, "amount": None, "source_note": note})

    assert response.status_code == 201, response.text
    assert (response.json()["amount"], response.json()["source_note"]) == (None, None)


def test_a_missing_amount_and_source_note_default_to_null(aapl_client: TestClient) -> None:
    body = {k: v for k, v in LEASE.items() if k not in ("amount", "source_note")}

    response = aapl_client.post(ITEMS, json=body)

    assert response.status_code == 201, response.text
    assert (response.json()["amount"], response.json()["source_note"]) == (None, None)


def test_list_is_newest_as_of_first_then_newest_id(aapl_client: TestClient) -> None:
    ids = {}
    for name, as_of in (("a", "2023-09-30"), ("b", "2024-09-28"), ("c", "2024-09-28")):
        created = aapl_client.post(ITEMS, json={**LEASE, "description": name, "as_of": as_of})
        ids[name] = created.json()["id"]

    listed = aapl_client.get(ITEMS)

    assert listed.status_code == 200, listed.text
    assert [i["description"] for i in listed.json()] == ["c", "b", "a"]
    assert [i["id"] for i in listed.json()] == [ids["c"], ids["b"], ids["a"]]


def test_an_empty_list(aapl_client: TestClient) -> None:
    assert aapl_client.get(ITEMS).json() == []


def test_put_replaces_every_field_and_bumps_updated_at(
    aapl_client: TestClient, advance: Callable[[timedelta], None]
) -> None:
    created = aapl_client.post(ITEMS, json=LEASE).json()
    advance(timedelta(minutes=5))
    changed = {
        "kind": "guarantee",
        "description": " Supplier debt guarantee ",
        "amount": "-250",
        "as_of": "2025-09-27",
        "source_note": None,
    }

    put = aapl_client.put(f"{ITEMS}/{created['id']}", json=changed)

    assert put.status_code == 200, put.text
    body = put.json()
    assert (body["id"], body["kind"], body["description"]) == (
        created["id"],
        "guarantee",
        "Supplier debt guarantee",
    )
    assert (body["amount"], body["as_of"], body["source_note"]) == ("-250", "2025-09-27", None)
    assert body["created_at"] == created["created_at"]
    updated = datetime.fromisoformat(body["updated_at"])
    assert updated == START + timedelta(minutes=5)
    assert updated > datetime.fromisoformat(created["updated_at"])
    assert aapl_client.get(ITEMS).json() == [body]


def test_delete_removes_the_item(aapl_client: TestClient) -> None:
    created = aapl_client.post(ITEMS, json=LEASE).json()

    assert aapl_client.delete(f"{ITEMS}/{created['id']}").status_code == 204
    assert aapl_client.get(ITEMS).json() == []
    assert aapl_client.delete(f"{ITEMS}/{created['id']}").status_code == 404
    assert aapl_client.put(f"{ITEMS}/{created['id']}", json=LEASE).status_code == 404


def test_an_unknown_id_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.put(f"{ITEMS}/999", json=LEASE).status_code == 404
    assert aapl_client.delete(f"{ITEMS}/999").status_code == 404


def test_an_unknown_id_with_an_invalid_body_is_a_404(aapl_client: TestClient) -> None:
    # Not-found is checked before the service rules.
    response = aapl_client.put(f"{ITEMS}/999", json={**LEASE, "description": "  "})

    assert response.status_code == 404, response.text


def test_another_companys_item_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    created = aapl_client.post(ITEMS, json=LEASE).json()
    theirs = f"/api/v1/companies/MSFT/off-balance-items/{created['id']}"

    assert aapl_client.put(theirs, json=LEASE).status_code == 404
    assert aapl_client.delete(theirs).status_code == 404
    assert aapl_client.get("/api/v1/companies/MSFT/off-balance-items").json() == []
    assert [i["id"] for i in aapl_client.get(ITEMS).json()] == [created["id"]]


# --- validation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"description": ""},
        {"description": "   "},
        {"kind": "operating_lease"},
        {"as_of": None},
        {"as_of": "not-a-date"},
        {"amount": "lots"},
        {"amount": "1e400"},  # would come back from SQLite as Infinity
        {"amount": "1e15"},  # beyond what a SQLite REAL stores exactly (G15)
        {"amount": "-1e15"},
        {"amount": "1e18"},
    ],
    ids=lambda c: f"{next(iter(c))}={next(iter(c.values()))!r}",
)
def test_invalid_items_are_422_and_not_stored(
    aapl_client: TestClient, change: dict[str, object]
) -> None:
    response = aapl_client.post(ITEMS, json={**LEASE, **change})

    assert response.status_code == 422, response.text
    assert aapl_client.get(ITEMS).json() == []


@pytest.mark.parametrize("field", ["kind", "description", "as_of"])
def test_a_missing_required_field_is_422(aapl_client: TestClient, field: str) -> None:
    body = {k: v for k, v in LEASE.items() if k != field}

    assert aapl_client.post(ITEMS, json=body).status_code == 422


def test_a_blank_description_carries_a_readable_detail(aapl_client: TestClient) -> None:
    response = aapl_client.post(ITEMS, json={**LEASE, "description": " "})

    assert response.status_code == 422
    assert "description" in response.json()["detail"]


def test_an_amount_just_inside_the_bound_is_accepted(aapl_client: TestClient) -> None:
    response = aapl_client.post(ITEMS, json={**LEASE, "amount": "999999999999999"})

    assert response.status_code == 201, response.text
    assert [i["amount"] for i in aapl_client.get(ITEMS).json()] == ["999999999999999"]


def test_an_invalid_put_is_422_and_keeps_the_stored_item(aapl_client: TestClient) -> None:
    created = aapl_client.post(ITEMS, json=LEASE).json()

    response = aapl_client.put(f"{ITEMS}/{created['id']}", json={**LEASE, "amount": "1e400"})

    assert response.status_code == 422, response.text
    assert "too large" in response.json()["detail"]
    assert aapl_client.get(ITEMS).json() == [created]


# --- cascade ---------------------------------------------------------------------------------


def test_unfollowing_a_company_deletes_its_items(
    aapl_client: TestClient, db_session: Session
) -> None:
    assert aapl_client.post(ITEMS, json=LEASE).status_code == 201

    assert aapl_client.delete(COMPANY).status_code == 204

    assert db_session.scalars(select(OffBalanceItem)).all() == []
    assert aapl_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    assert aapl_client.get(ITEMS).json() == []


# --- service rules the schema cannot reach ---------------------------------------------------


def _input(kind: str = "lease", amount: Decimal | None = Decimal("1500000000")) -> OffBalanceInput:
    return OffBalanceInput(
        kind=kind,
        description="Store leases",
        amount=amount,
        as_of=date(2024, 9, 28),
        source_note=None,
    )


@pytest.mark.parametrize(
    "data",
    [_input(kind="warrant"), _input(amount=Decimal("NaN"))],
    ids=["unknown-kind", "nan-amount"],
)
def test_the_service_rejects_what_the_schema_cannot_send(
    aapl_client: TestClient, db_session: Session, data: OffBalanceInput
) -> None:
    company: Company = db_session.scalars(select(Company).where(Company.ticker == "AAPL")).one()

    with pytest.raises(InvalidOffBalanceItem):
        analysis.create_off_balance_item(db_session, company, data, START)

    db_session.expire_all()
    assert db_session.scalars(select(OffBalanceItem)).all() == []
