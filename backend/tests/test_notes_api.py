"""Notes and their links to cells, lines and periods through the API (FR-NOTE-01/02)."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock
from bedrock.models.note import Note

from .conftest import TEST_PASSWORD

API = "/api/v1"
COMPANY = f"{API}/companies/AAPL"
NOTES = f"{COMPANY}/notes"
LINKS = f"{NOTES}/links"


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post(f"{API}/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def make(client: TestClient, body_md: str = "A note", **link: Any) -> dict[str, Any]:
    response = client.post(NOTES, json={"body_md": body_md, **link})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def notes(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    response = client.get(NOTES, params=params)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


def bodies(client: TestClient, **params: Any) -> list[str]:
    return [n["body_md"] for n in notes(client, **params)]


def _count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(Note)).scalar_one()


CELL: dict[str, Any] = {"canonical_code": "revenue", "fiscal_year": 2024, "fiscal_period": "FY"}
LINE: dict[str, Any] = {"canonical_code": "revenue"}
PERIOD: dict[str, Any] = {"fiscal_year": 2024, "fiscal_period": "FY"}


# --- guards ----------------------------------------------------------------------------------


def test_every_notes_route_requires_a_session(client: TestClient) -> None:
    body = {"body_md": "x"}
    assert client.get(NOTES).status_code == 401
    assert client.get(LINKS).status_code == 401
    assert client.post(NOTES, json=body).status_code == 401
    assert client.put(f"{NOTES}/1", json=body).status_code == 401
    assert client.delete(f"{NOTES}/1").status_code == 401


def test_an_unfollowed_ticker_is_a_404_on_every_route(authed_client: TestClient) -> None:
    body = {"body_md": "x"}
    assert authed_client.get(NOTES).status_code == 404
    assert authed_client.get(LINKS).status_code == 404
    assert authed_client.post(NOTES, json=body).status_code == 404
    assert authed_client.put(f"{NOTES}/1", json=body).status_code == 404
    assert authed_client.delete(f"{NOTES}/1").status_code == 404


# --- CRUD ------------------------------------------------------------------------------------


def test_create_list_update_and_delete_a_note(aapl_client: TestClient) -> None:
    created = make(aapl_client, "  # Thesis\nServices **grow**  ", note_date="2024-11-02")
    assert set(created) == {
        "id",
        "body_md",
        "canonical_code",
        "label",
        "fiscal_year",
        "fiscal_period",
        "note_date",
        "created_at",
        "updated_at",
    }
    assert created["body_md"] == "# Thesis\nServices **grow**"
    assert created["note_date"] == "2024-11-02"
    assert (created["canonical_code"], created["label"], created["fiscal_year"]) == (
        None,
        None,
        None,
    )
    assert created["created_at"].endswith(("Z", "+00:00"))

    assert notes(aapl_client) == [created]

    url = f"{NOTES}/{created['id']}"
    response = aapl_client.put(url, json={"body_md": "Edited", **CELL, "note_date": "2024-11-03"})
    assert response.status_code == 200, response.text
    edited = response.json()
    assert (edited["id"], edited["body_md"], edited["note_date"]) == (
        created["id"],
        "Edited",
        "2024-11-03",
    )
    assert (edited["canonical_code"], edited["label"]) == ("revenue", "Revenue")
    assert notes(aapl_client) == [edited]

    assert aapl_client.delete(url).status_code == 204
    assert notes(aapl_client) == []
    assert aapl_client.delete(url).status_code == 404


def test_an_update_replaces_the_link_so_a_missing_link_unlinks_the_note(
    aapl_client: TestClient,
) -> None:
    created = make(aapl_client, **CELL)
    response = aapl_client.put(f"{NOTES}/{created['id']}", json={"body_md": "Now free"})
    body = response.json()
    assert (body["canonical_code"], body["fiscal_year"], body["fiscal_period"]) == (None,) * 3
    assert aapl_client.get(LINKS).json() == []


def test_the_body_is_stored_markdown_as_written(aapl_client: TestClient) -> None:
    body_md = "- [x] item\n\n```py\nprint(1)\n```\n<script>alert(1)</script>"
    assert make(aapl_client, body_md)["body_md"] == body_md


# --- links -----------------------------------------------------------------------------------


def test_a_note_can_link_to_a_cell_a_line_a_period_or_nothing(aapl_client: TestClient) -> None:
    cell = make(aapl_client, "cell", **CELL)
    line = make(aapl_client, "line", **LINE)
    period = make(aapl_client, "period", **PERIOD)
    free = make(aapl_client, "free")

    def got(n: dict[str, Any]) -> tuple[Any, ...]:
        return (n["canonical_code"], n["fiscal_year"], n["fiscal_period"])

    assert got(cell) == ("revenue", 2024, "FY")
    assert got(line) == ("revenue", None, None)
    assert got(period) == (None, 2024, "FY")
    assert got(free) == (None, None, None)


def test_a_period_need_not_exist_in_the_statements(aapl_client: TestClient) -> None:
    far = make(aapl_client, "next year", fiscal_year=2031, fiscal_period="Q2")
    assert (far["fiscal_year"], far["fiscal_period"]) == (2031, "Q2")


@pytest.mark.parametrize(
    "link",
    [
        {"fiscal_year": 2024},
        {"fiscal_period": "FY"},
        {"canonical_code": "revenue", "fiscal_year": 2024},
        {"canonical_code": "not_a_line"},
        {"canonical_code": ""},
        {"canonical_code": "Revenue"},
        {"fiscal_year": 2024, "fiscal_period": "Q5"},
        {"fiscal_year": 99, "fiscal_period": "FY"},
        {"fiscal_year": 10000, "fiscal_period": "FY"},
    ],
)
def test_an_invalid_link_is_a_422_and_nothing_is_stored(
    aapl_client: TestClient, db_session: Session, link: dict[str, Any]
) -> None:
    response = aapl_client.post(NOTES, json={"body_md": "x", **link})
    assert response.status_code == 422, response.text
    assert _count(db_session) == 0


def test_the_link_422_names_the_problem(aapl_client: TestClient) -> None:
    detail = aapl_client.post(NOTES, json={"body_md": "x", "canonical_code": "revnue"}).json()
    assert "revnue" in detail["detail"]
    detail = aapl_client.post(NOTES, json={"body_md": "x", "fiscal_year": 2024}).json()
    assert "fiscal period" in detail["detail"].lower()


@pytest.mark.parametrize("body_md", ["", "   ", "\n\t\n", "x" * 20_001])
def test_a_blank_or_oversized_body_is_a_422(
    aapl_client: TestClient, db_session: Session, body_md: str
) -> None:
    assert aapl_client.post(NOTES, json={"body_md": body_md}).status_code == 422
    assert _count(db_session) == 0


def test_a_body_of_exactly_20000_characters_once_stripped_is_accepted(
    aapl_client: TestClient,
) -> None:
    created = make(aapl_client, "  " + "x" * 20_000 + "\n")
    assert len(created["body_md"]) == 20_000


def test_a_missing_body_is_a_422(aapl_client: TestClient) -> None:
    assert aapl_client.post(NOTES, json={}).status_code == 422
    assert aapl_client.post(NOTES, json={"body_md": None}).status_code == 422


def test_an_invalid_update_leaves_the_note_unchanged(aapl_client: TestClient) -> None:
    created = make(aapl_client, "keep", **CELL)
    response = aapl_client.put(f"{NOTES}/{created['id']}", json={"body_md": " ", **CELL})
    assert response.status_code == 422
    assert notes(aapl_client) == [created]


# --- filters ---------------------------------------------------------------------------------


@pytest.fixture
def mixed(aapl_client: TestClient) -> TestClient:
    make(aapl_client, "cell revenue FY24", **CELL)
    make(aapl_client, "cell revenue FY23", **{**CELL, "fiscal_year": 2023})
    make(aapl_client, "cell revenue Q1", **{**CELL, "fiscal_period": "Q1"})
    make(aapl_client, "line revenue", **LINE)
    make(aapl_client, "cell sga FY24", canonical_code="sga", fiscal_year=2024, fiscal_period="FY")
    make(aapl_client, "line sga", canonical_code="sga")
    make(aapl_client, "period FY24", **PERIOD)
    make(aapl_client, "period FY23", fiscal_year=2023, fiscal_period="FY")
    make(aapl_client, "free")
    return aapl_client


def test_no_filter_lists_every_note(mixed: TestClient) -> None:
    assert len(notes(mixed)) == 9


def test_a_code_alone_returns_the_lines_notes_and_those_of_all_its_cells(mixed: TestClient) -> None:
    assert set(bodies(mixed, code="revenue")) == {
        "cell revenue FY24",
        "cell revenue FY23",
        "cell revenue Q1",
        "line revenue",
    }
    assert set(bodies(mixed, code="sga")) == {"cell sga FY24", "line sga"}


def test_a_code_with_a_period_returns_that_cells_notes_and_the_lines_notes(
    mixed: TestClient,
) -> None:
    assert set(bodies(mixed, code="revenue", fiscal_year=2024, fiscal_period="FY")) == {
        "cell revenue FY24",
        "line revenue",
    }
    assert set(bodies(mixed, code="revenue", fiscal_year=2023, fiscal_period="FY")) == {
        "cell revenue FY23",
        "line revenue",
    }
    assert set(bodies(mixed, code="revenue", fiscal_year=2024, fiscal_period="Q1")) == {
        "cell revenue Q1",
        "line revenue",
    }


def test_a_period_alone_returns_the_period_notes_and_the_cell_notes_of_it(
    mixed: TestClient,
) -> None:
    assert set(bodies(mixed, fiscal_year=2024, fiscal_period="FY")) == {
        "cell revenue FY24",
        "cell sga FY24",
        "period FY24",
    }
    assert set(bodies(mixed, fiscal_year=2023, fiscal_period="FY")) == {
        "cell revenue FY23",
        "period FY23",
    }


def test_a_filter_matching_nothing_returns_an_empty_list(mixed: TestClient) -> None:
    assert notes(mixed, code="cash") == []
    # no cell in 1999, but the line's own notes still apply
    assert bodies(mixed, code="revenue", fiscal_year=1999, fiscal_period="FY") == ["line revenue"]
    assert notes(mixed, fiscal_year=2031, fiscal_period="Q4") == []


def test_a_filter_with_a_year_but_no_period_or_the_reverse_is_a_422(mixed: TestClient) -> None:
    assert mixed.get(NOTES, params={"fiscal_year": 2024}).status_code == 422
    assert mixed.get(NOTES, params={"fiscal_period": "FY"}).status_code == 422
    assert mixed.get(NOTES, params={"fiscal_year": 2024, "fiscal_period": "Q9"}).status_code == 422


def test_notes_are_newest_note_date_first_then_highest_id(aapl_client: TestClient) -> None:
    a = make(aapl_client, "a", note_date="2024-01-01")
    b = make(aapl_client, "b", note_date="2024-03-01")
    c = make(aapl_client, "c", note_date="2024-03-01")
    d = make(aapl_client, "d", note_date="2023-12-31")
    assert [n["id"] for n in notes(aapl_client)] == [c["id"], b["id"], a["id"], d["id"]]


# --- the links index -------------------------------------------------------------------------


def test_links_counts_notes_per_distinct_link_and_leaves_unlinked_notes_out(
    aapl_client: TestClient,
) -> None:
    make(aapl_client, "1", **CELL)
    make(aapl_client, "2", **CELL)
    make(aapl_client, "3", **LINE)
    make(aapl_client, "4", **PERIOD)
    make(aapl_client, "5", **{**CELL, "fiscal_period": "Q1"})
    make(aapl_client, "6")
    response = aapl_client.get(LINKS)
    assert response.status_code == 200
    links = response.json()
    assert all(
        set(link) == {"canonical_code", "fiscal_year", "fiscal_period", "count"} for link in links
    )
    counted = {
        (link["canonical_code"], link["fiscal_year"], link["fiscal_period"]): link["count"]
        for link in links
    }
    assert counted == {
        ("revenue", 2024, "FY"): 2,
        ("revenue", None, None): 1,
        (None, 2024, "FY"): 1,
        ("revenue", 2024, "Q1"): 1,
    }
    assert len(links) == 4


def test_links_follow_edits_and_deletes(aapl_client: TestClient) -> None:
    note = make(aapl_client, "x", **CELL)
    assert aapl_client.get(LINKS).json()[0]["count"] == 1
    aapl_client.put(f"{NOTES}/{note['id']}", json={"body_md": "x", **LINE})
    (link,) = aapl_client.get(LINKS).json()
    assert (link["canonical_code"], link["fiscal_year"], link["count"]) == ("revenue", None, 1)
    aapl_client.delete(f"{NOTES}/{note['id']}")
    assert aapl_client.get(LINKS).json() == []


def test_links_is_not_read_as_a_note_id(aapl_client: TestClient) -> None:
    assert aapl_client.get(LINKS).status_code == 200
    assert aapl_client.put(LINKS, json={"body_md": "x"}).status_code == 422  # {note_id} = "links"


# --- the date --------------------------------------------------------------------------------


def test_note_date_defaults_to_today_in_utc_from_the_injected_clock(
    app: FastAPI, client: TestClient
) -> None:
    late_in_new_york = datetime(2024, 6, 1, 23, 30, tzinfo=timezone(timedelta(hours=-4)))
    app.dependency_overrides[get_clock] = lambda: late_in_new_york
    assert client.post(f"{API}/auth/login", json={"password": TEST_PASSWORD}).status_code == 204
    assert client.post(f"{API}/companies", json={"ticker": "AAPL"}).status_code == 201

    created = make(client, "today")
    assert created["note_date"] == "2024-06-02"  # 03:30 UTC the next day
    assert created["created_at"].startswith("2024-06-02T03:30")
    explicit = client.put(
        f"{NOTES}/{created['id']}", json={"body_md": "x", "note_date": "2020-01-31"}
    ).json()
    assert explicit["note_date"] == "2020-01-31"
    # an update without a date keeps the stored one
    kept = client.put(f"{NOTES}/{created['id']}", json={"body_md": "y"}).json()
    assert kept["note_date"] == "2020-01-31"


def test_updated_at_moves_and_created_at_does_not(app: FastAPI, client: TestClient) -> None:
    first = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    app.dependency_overrides[get_clock] = lambda: first
    assert client.post(f"{API}/auth/login", json={"password": TEST_PASSWORD}).status_code == 204
    assert client.post(f"{API}/companies", json={"ticker": "AAPL"}).status_code == 201
    created = make(client, "v1")
    later = first + timedelta(hours=2)
    app.dependency_overrides[get_clock] = lambda: later
    edited = client.put(f"{NOTES}/{created['id']}", json={"body_md": "v2"}).json()
    assert edited["created_at"] == created["created_at"]
    assert edited["updated_at"].startswith("2024-06-01T14:00")


@pytest.mark.parametrize("bad", ["2024-13-01", "yesterday", ""])
def test_an_invalid_note_date_is_a_422(aapl_client: TestClient, bad: Any) -> None:
    response = aapl_client.post(NOTES, json={"body_md": "x", "note_date": bad})
    assert response.status_code == 422


# --- ownership and lifecycle -----------------------------------------------------------------


def test_a_note_of_another_company_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post(f"{API}/companies", json={"ticker": "MSFT"}).status_code == 201
    created = make(aapl_client, "mine", **CELL)
    other = f"{API}/companies/MSFT/notes/{created['id']}"
    assert aapl_client.put(other, json={"body_md": "stolen"}).status_code == 404
    assert aapl_client.delete(other).status_code == 404
    assert bodies(aapl_client) == ["mine"]
    assert aapl_client.get(f"{API}/companies/MSFT/notes").json() == []
    assert aapl_client.get(f"{API}/companies/MSFT/notes/links").json() == []


def test_deleting_the_company_removes_its_notes(
    aapl_client: TestClient, db_session: Session
) -> None:
    make(aapl_client, "one", **CELL)
    make(aapl_client, "two")
    assert _count(db_session) == 2
    assert aapl_client.delete(COMPANY).status_code == 204
    assert _count(db_session) == 0
