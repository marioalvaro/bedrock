"""Adjustments through the API, and what they do to the normalized statements (AAPL fixtures)."""

from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

COMPANY = "/api/v1/companies/AAPL"
ADJUSTMENTS = f"{COMPANY}/adjustments"
STATEMENTS = f"{COMPANY}/statements"
BILLION = Decimal(1_000_000_000)

SGA_FY2024 = {
    "canonical_code": "sga",
    "fiscal_year": 2024,
    "fiscal_period": "FY",
    "amount": "-1000000000",
    "category": "one-off",
    "reason": "test",
}


@pytest.fixture
def aapl_db(seed_db: Callable[..., None]) -> None:
    seed_db("AAPL")


@pytest.fixture
def aapl_client(aapl_db: None, authed_client: TestClient) -> TestClient:
    return authed_client


def statement(client: TestClient, type_: str, freq: str, basis: str) -> dict[str, object]:
    response = client.get(STATEMENTS, params={"type": type_, "freq": freq, "basis": basis})
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def cell(body: dict[str, object], code: str, period: str) -> tuple[Decimal | None, str | None]:
    row = next(r for r in body["rows"] if r["code"] == code)  # type: ignore[attr-defined,union-attr]
    index = [p["key"] for p in body["periods"]].index(period)  # type: ignore[attr-defined,union-attr]
    value = row["values"][index]
    return (None if value is None else Decimal(value)), row["provenance"][index]


# --- guards ----------------------------------------------------------------------------------


def test_every_adjustment_route_requires_a_session(client: TestClient) -> None:
    assert client.get(ADJUSTMENTS).status_code == 401
    assert client.post(ADJUSTMENTS, json=SGA_FY2024).status_code == 401
    assert client.put(f"{ADJUSTMENTS}/1", json=SGA_FY2024).status_code == 401
    assert client.delete(f"{ADJUSTMENTS}/1").status_code == 401


def test_an_unfollowed_company_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(ADJUSTMENTS).status_code == 404
    assert authed_client.post(ADJUSTMENTS, json=SGA_FY2024).status_code == 404
    assert authed_client.delete(f"{ADJUSTMENTS}/1").status_code == 404


# --- CRUD ------------------------------------------------------------------------------------


def test_a_new_adjustment_is_created_with_the_documented_shape(aapl_client: TestClient) -> None:
    response = aapl_client.post(ADJUSTMENTS, json=SGA_FY2024)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "canonical_code",
        "label",
        "fiscal_year",
        "fiscal_period",
        "amount",
        "category",
        "reason",
        "created_at",
        "updated_at",
    }
    assert (body["canonical_code"], body["label"], body["fiscal_year"]) == (
        "sga",
        "Selling, general & administrative",
        2024,
    )
    assert body["amount"] == "-1000000000"  # a JSON string, no padding
    assert body["created_at"].endswith("Z") and body["updated_at"].endswith("Z")


def test_list_returns_the_company_adjustments_by_year_and_period(aapl_client: TestClient) -> None:
    for year, period in ((2024, "Q1"), (2023, "FY"), (2024, "FY")):
        body = {**SGA_FY2024, "fiscal_year": year, "fiscal_period": period}
        assert aapl_client.post(ADJUSTMENTS, json=body).status_code == 201

    listed = aapl_client.get(ADJUSTMENTS).json()

    assert [(a["fiscal_year"], a["fiscal_period"]) for a in listed] == [
        (2023, "FY"),
        (2024, "FY"),
        (2024, "Q1"),
    ]


def test_put_replaces_the_adjustment_and_delete_removes_it(aapl_client: TestClient) -> None:
    created = aapl_client.post(ADJUSTMENTS, json=SGA_FY2024).json()
    changed = {**SGA_FY2024, "amount": "-5", "category": "reclass", "reason": "Moved to COGS"}

    put = aapl_client.put(f"{ADJUSTMENTS}/{created['id']}", json=changed)

    assert put.status_code == 200, put.text
    assert (put.json()["id"], put.json()["amount"], put.json()["category"]) == (
        created["id"],
        "-5",
        "reclass",
    )
    assert aapl_client.delete(f"{ADJUSTMENTS}/{created['id']}").status_code == 204
    assert aapl_client.get(ADJUSTMENTS).json() == []
    assert aapl_client.delete(f"{ADJUSTMENTS}/{created['id']}").status_code == 404
    assert aapl_client.put(f"{ADJUSTMENTS}/{created['id']}", json=changed).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"canonical_code": "total_debt"},  # computed only
        {"canonical_code": "free_cash_flow"},
        {"canonical_code": "eps_diluted"},
        {"canonical_code": "shares_diluted"},
        {"canonical_code": "goodwill_impairment"},
        {"canonical_code": "nowhere"},
        {"fiscal_year": 1990},  # not a fiscal year of AAPL
        {"fiscal_period": "Q5"},
        {"fiscal_period": "TTM"},
        {"reason": ""},
        {"reason": "  "},
        {"category": "whim"},
        {"amount": "lots"},
        {"amount": "1e400"},  # would come back from SQLite as Infinity
        {"amount": "1e15"},  # beyond what a SQLite REAL stores exactly
        {"amount": "-1e15"},
        {"amount": "1e18"},  # beyond Numeric(28, 10)
        {"amount": "-1e18"},
    ],
    ids=lambda c: next(iter(c.values())).__str__(),
)
def test_invalid_adjustments_are_422_and_not_stored(
    aapl_client: TestClient, change: dict[str, object]
) -> None:
    response = aapl_client.post(ADJUSTMENTS, json={**SGA_FY2024, **change})

    assert response.status_code == 422, response.text
    assert aapl_client.get(ADJUSTMENTS).json() == []


def test_a_large_amount_inside_the_bound_is_created_and_lists_back(
    aapl_client: TestClient,
) -> None:
    response = aapl_client.post(ADJUSTMENTS, json={**SGA_FY2024, "amount": "123456789012345"})

    assert response.status_code == 201, response.text
    listed = aapl_client.get(ADJUSTMENTS)
    assert listed.status_code == 200, listed.text
    assert [a["id"] for a in listed.json()] == [response.json()["id"]]


def test_an_unbounded_amount_on_put_is_422_and_keeps_the_stored_row(
    aapl_client: TestClient,
) -> None:
    created = aapl_client.post(ADJUSTMENTS, json=SGA_FY2024).json()

    response = aapl_client.put(
        f"{ADJUSTMENTS}/{created['id']}", json={**SGA_FY2024, "amount": "1e400"}
    )

    assert response.status_code == 422, response.text
    assert "too large" in response.json()["detail"]
    assert [a["amount"] for a in aapl_client.get(ADJUSTMENTS).json()] == ["-1000000000"]


def test_a_422_from_a_rule_carries_a_readable_detail(aapl_client: TestClient) -> None:
    response = aapl_client.post(ADJUSTMENTS, json={**SGA_FY2024, "canonical_code": "total_debt"})

    assert "cannot be adjusted" in response.json()["detail"]


def test_a_missing_field_is_422(aapl_client: TestClient) -> None:
    body = {k: v for k, v in SGA_FY2024.items() if k != "reason"}

    assert aapl_client.post(ADJUSTMENTS, json=body).status_code == 422


def test_another_companys_adjustment_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    created = aapl_client.post(ADJUSTMENTS, json=SGA_FY2024).json()
    theirs = f"/api/v1/companies/MSFT/adjustments/{created['id']}"

    assert aapl_client.put(theirs, json=SGA_FY2024).status_code == 404
    assert aapl_client.delete(theirs).status_code == 404
    assert aapl_client.get("/api/v1/companies/MSFT/adjustments").json() == []
    assert len(aapl_client.get(ADJUSTMENTS).json()) == 1


# --- the normalized view -------------------------------------------------------------------


def test_the_round_trip_post_changes_the_normalized_statement_and_delete_restores_it(
    aapl_client: TestClient,
) -> None:
    reported = statement(aapl_client, "IS", "annual", "reported")
    created = aapl_client.post(ADJUSTMENTS, json=SGA_FY2024)
    assert created.status_code == 201

    normalized = statement(aapl_client, "IS", "annual", "normalized")
    after_reported = statement(aapl_client, "IS", "annual", "reported")

    assert after_reported == reported  # the reported basis never moves
    assert normalized["basis"] == "normalized"
    for code in ("operating_income", "net_income_common", "pretax_income", "net_income"):
        before, _ = cell(reported, code, "FY2024")
        value, mark = cell(normalized, code, "FY2024")
        assert before is not None and value == before + BILLION, code
        assert mark == "normalized", code
    sga_before, _ = cell(reported, "sga", "FY2024")
    assert cell(normalized, "sga", "FY2024") == (sga_before - BILLION, "normalized")  # type: ignore[operator]
    assert cell(normalized, "revenue", "FY2024")[1] == "reported"
    assert cell(normalized, "operating_income", "FY2023") == cell(
        reported, "operating_income", "FY2023"
    )

    detail = aapl_client.get(
        f"{STATEMENTS}/cell",
        params={"code": "operating_income", "fiscal_year": 2024, "fiscal_period": "FY"},
    ).json()
    assert detail["value"] == str(cell(reported, "operating_income", "FY2024")[0])
    assert Decimal(detail["normalized_value"]) == cell(normalized, "operating_income", "FY2024")[0]
    (listed,) = detail["adjustments"]
    assert set(listed) == {
        "id",
        "canonical_code",
        "label",
        "fiscal_year",
        "fiscal_period",
        "amount",
        "category",
        "reason",
        "created_at",
        "updated_at",
        "via",
    }
    assert (listed["id"], listed["canonical_code"], listed["via"]) == (
        created.json()["id"],
        "sga",
        "sga",
    )
    assert (listed["amount"], listed["reason"], listed["category"]) == (
        "-1000000000",
        "test",
        "one-off",
    )

    assert aapl_client.delete(f"{ADJUSTMENTS}/{created.json()['id']}").status_code == 204
    assert statement(aapl_client, "IS", "annual", "normalized")["rows"] == reported["rows"]


def test_the_adjusted_line_lists_its_own_adjustment_without_via(aapl_client: TestClient) -> None:
    created = aapl_client.post(ADJUSTMENTS, json=SGA_FY2024).json()

    detail = aapl_client.get(
        f"{STATEMENTS}/cell", params={"code": "sga", "fiscal_year": 2024, "fiscal_period": "FY"}
    ).json()

    assert [(a["id"], a["via"]) for a in detail["adjustments"]] == [(created["id"], None)]
    assert Decimal(detail["normalized_value"]) == Decimal(detail["value"]) - BILLION


def test_an_unrelated_cell_has_no_adjustments(aapl_client: TestClient) -> None:
    aapl_client.post(ADJUSTMENTS, json=SGA_FY2024)

    detail = aapl_client.get(
        f"{STATEMENTS}/cell", params={"code": "revenue", "fiscal_year": 2024, "fiscal_period": "FY"}
    ).json()

    assert detail["adjustments"] == [] and detail["normalized_value"] is None


def test_rows_say_which_lines_are_adjustable(aapl_client: TestClient) -> None:
    body = statement(aapl_client, "IS", "annual", "reported")

    flags = {r["code"]: r["adjustable"] for r in body["rows"]}  # type: ignore[attr-defined,union-attr]
    assert flags["sga"] is True and flags["revenue"] is True
    assert flags["total_operating_costs"] is False and flags["eps_diluted"] is False


def test_normalized_ttm_and_quarterly_follow_the_adjustment(aapl_client: TestClient) -> None:
    quarterly_body = {**SGA_FY2024, "fiscal_period": "Q4", "reason": "Q4 only"}
    assert aapl_client.post(ADJUSTMENTS, json=quarterly_body).status_code == 201

    quarterly = statement(aapl_client, "IS", "quarterly", "normalized")
    reported = statement(aapl_client, "IS", "quarterly", "reported")
    ttm = statement(aapl_client, "IS", "ttm", "normalized")

    value, mark = cell(quarterly, "operating_income", "FY2024Q4")
    before, _ = cell(reported, "operating_income", "FY2024Q4")
    assert before is not None and value == before + BILLION and mark == "normalized"
    assert cell(quarterly, "operating_income", "FY2024Q3") == cell(
        reported, "operating_income", "FY2024Q3"
    )
    assert cell(ttm, "operating_income", "TTM-FY2024Q4")[1] == "normalized"


def test_an_unbalanced_balance_sheet_adjustment_fails_the_normalized_balance_check(
    aapl_client: TestClient,
) -> None:
    body = {**SGA_FY2024, "canonical_code": "cash", "amount": "1000000000"}
    assert aapl_client.post(ADJUSTMENTS, json=body).status_code == 201

    normalized = statement(aapl_client, "BS", "annual", "normalized")
    reported = statement(aapl_client, "BS", "annual", "reported")

    check = {c["period_key"]: c for c in normalized["balance_check"]}  # type: ignore[attr-defined,union-attr]
    assert Decimal(check["FY2024"]["difference"]) == BILLION and check["FY2024"]["ok"] is False
    assert all(c["ok"] for c in reported["balance_check"])  # type: ignore[attr-defined,union-attr]


def test_a_balanced_pair_keeps_the_normalized_balance_sheet_balanced(
    aapl_client: TestClient,
) -> None:
    cash = {**SGA_FY2024, "canonical_code": "cash", "amount": "1000000000"}
    debt = {**SGA_FY2024, "canonical_code": "long_term_debt", "amount": "1000000000"}
    for body in (cash, debt):
        assert aapl_client.post(ADJUSTMENTS, json=body).status_code == 201

    normalized = statement(aapl_client, "BS", "annual", "normalized")

    check = {c["period_key"]: c for c in normalized["balance_check"]}  # type: ignore[attr-defined,union-attr]
    assert check["FY2024"]["ok"] is True
    assert Decimal(check["FY2024"]["difference"]) == (
        Decimal(
            next(
                c
                for c in statement(aapl_client, "BS", "annual", "reported")["balance_check"]  # type: ignore[attr-defined,union-attr]
                if c["period_key"] == "FY2024"
            )["difference"]
        )
    )
