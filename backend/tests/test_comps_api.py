"""Comps sets, peer suggestions and the peer comparison through the API (FR-ANL-08), on the
recorded AAPL, MSFT, COST and DE fixtures."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.comps_member import CompsMember
from bedrock.models.comps_set import CompsSet

API = "/api/v1"
AAPL = f"{API}/companies/AAPL"
SETS = f"{AAPL}/comps-sets"
SUGGESTIONS = f"{AAPL}/peer-suggestions"
ALL = ("AAPL", "MSFT", "COST", "DE")


@pytest.fixture
def followed_db(seed_db: Callable[..., None]) -> None:
    seed_db(*ALL)


@pytest.fixture
def followed(followed_db: None, authed_client: TestClient) -> TestClient:
    return authed_client


def create(client: TestClient, name: str = "Peers", members: list[str] | None = None) -> Any:
    body = {"name": name, "members": ["MSFT", "COST", "DE"] if members is None else members}
    response = client.post(SETS, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def comparison(client: TestClient, set_id: int, **params: str) -> dict[str, Any]:
    response = client.get(f"{SETS}/{set_id}/comparison", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def row(body: dict[str, Any], code: str) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in body["rows"] if r["code"] == code)
    return found


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


# --- guards ----------------------------------------------------------------------------------


def test_every_comps_route_requires_a_session(client: TestClient) -> None:
    body = {"name": "x", "members": []}
    assert client.get(SETS).status_code == 401
    assert client.post(SETS, json=body).status_code == 401
    assert client.put(f"{SETS}/1", json=body).status_code == 401
    assert client.delete(f"{SETS}/1").status_code == 401
    assert client.get(SUGGESTIONS).status_code == 401
    assert client.get(f"{SETS}/1/comparison").status_code == 401


def test_an_unfollowed_ticker_is_a_404_on_every_route(authed_client: TestClient) -> None:
    body = {"name": "x", "members": []}
    assert authed_client.get(SETS).status_code == 404
    assert authed_client.post(SETS, json=body).status_code == 404
    assert authed_client.put(f"{SETS}/1", json=body).status_code == 404
    assert authed_client.delete(f"{SETS}/1").status_code == 404
    assert authed_client.get(SUGGESTIONS).status_code == 404
    assert authed_client.get(f"{SETS}/1/comparison").status_code == 404


# --- set CRUD --------------------------------------------------------------------------------


def test_create_list_update_and_delete_a_set(followed: TestClient) -> None:
    created = create(followed, "  Hardware  ", ["DE", "msft"])
    assert set(created) == {"id", "name", "members"}
    assert created["name"] == "Hardware"
    assert created["members"] == [
        {"ticker": "DE", "name": "DEERE & CO"},
        {"ticker": "MSFT", "name": "MICROSOFT CORP"},
    ]

    listed = followed.get(SETS)
    assert listed.status_code == 200 and listed.json() == [created]

    url = f"{SETS}/{created['id']}"
    updated = followed.put(url, json={"name": "Big tech", "members": ["COST"]})
    assert updated.status_code == 200, updated.text
    assert updated.json() == {
        "id": created["id"],
        "name": "Big tech",
        "members": [{"ticker": "COST", "name": updated.json()["members"][0]["name"]}],
    }
    assert [m["ticker"] for m in followed.get(SETS).json()[0]["members"]] == ["COST"]

    assert followed.delete(url).status_code == 204
    assert followed.get(SETS).json() == []
    assert followed.delete(url).status_code == 404


def test_sets_are_listed_by_name_and_members_by_ticker(followed: TestClient) -> None:
    create(followed, "b set", ["MSFT", "DE", "COST"])
    create(followed, "a set", [])
    listed = followed.get(SETS).json()
    assert [s["name"] for s in listed] == ["a set", "b set"]
    assert [m["ticker"] for m in listed[1]["members"]] == ["COST", "DE", "MSFT"]


def test_a_set_may_be_empty_and_two_companies_may_reuse_a_name(followed: TestClient) -> None:
    create(followed, "Peers", [])
    other = followed.post(f"{API}/companies/DE/comps-sets", json={"name": "Peers", "members": []})
    assert other.status_code == 201


def test_renaming_a_set_to_its_own_name_is_allowed(followed: TestClient) -> None:
    created = create(followed, "Peers", ["DE"])
    same = followed.put(
        f"{SETS}/{created['id']}", json={"name": "Peers", "members": ["DE", "COST"]}
    )
    assert same.status_code == 200 and len(same.json()["members"]) == 2


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"name": "   ", "members": []}, "name"),
        ({"name": "x" * 61, "members": []}, "name"),
        ({"name": "Peers", "members": ["AAPL"]}, "itself"),
        ({"name": "Peers", "members": ["DE", "de"]}, "twice"),
        ({"name": "Peers", "members": ["TSLA"]}, "not a followed company"),
    ],
    ids=["blank-name", "long-name", "itself", "duplicate-member", "unfollowed-member"],
)
def test_a_set_that_breaks_a_rule_is_a_422_and_stores_nothing(
    followed: TestClient, db_session: Session, body: dict[str, Any], message: str
) -> None:
    response = followed.post(SETS, json=body)
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert _count(db_session, CompsSet) == 0 and _count(db_session, CompsMember) == 0


def test_a_sixty_character_name_is_accepted(followed: TestClient) -> None:
    assert create(followed, "x" * 60, [])["name"] == "x" * 60


def test_a_duplicate_name_is_a_422_on_create_and_update(followed: TestClient) -> None:
    create(followed, "Peers", [])
    other = create(followed, "Other", [])
    assert followed.post(SETS, json={"name": " Peers ", "members": []}).status_code == 422
    clash = followed.put(f"{SETS}/{other['id']}", json={"name": "Peers", "members": []})
    assert clash.status_code == 422


def test_a_failed_update_leaves_the_set_unchanged(followed: TestClient) -> None:
    created = create(followed, "Peers", ["DE"])
    bad = followed.put(f"{SETS}/{created['id']}", json={"name": "New", "members": ["TSLA"]})
    assert bad.status_code == 422
    assert followed.get(SETS).json() == [created]


def test_another_companys_set_is_a_404(followed: TestClient) -> None:
    created = create(followed)
    theirs = f"{API}/companies/DE/comps-sets/{created['id']}"
    body = {"name": "x", "members": []}
    assert followed.put(theirs, json=body).status_code == 404
    assert followed.delete(theirs).status_code == 404
    assert followed.get(f"{theirs}/comparison").status_code == 404
    assert (
        followed.get(
            f"{API}/companies/DE/peer-suggestions", params={"set_id": created["id"]}
        ).status_code
        == 404
    )
    assert followed.get(SETS).json() == [created]


def test_unfollowing_a_peer_removes_it_from_every_set(followed: TestClient) -> None:
    create(followed, "Peers", ["MSFT", "DE"])
    assert followed.delete(f"{API}/companies/DE").status_code == 204
    assert [m["ticker"] for m in followed.get(SETS).json()[0]["members"]] == ["MSFT"]


def test_unfollowing_the_company_removes_its_sets(
    followed: TestClient, db_session: Session
) -> None:
    create(followed)
    assert _count(db_session, CompsSet) == 1 and _count(db_session, CompsMember) == 3
    assert followed.delete(AAPL).status_code == 204
    assert _count(db_session, CompsSet) == 0 and _count(db_session, CompsMember) == 0


# --- peer suggestions ------------------------------------------------------------------------


def test_aapl_is_suggested_de_as_a_major_group_match(followed: TestClient) -> None:
    response = followed.get(SUGGESTIONS)
    assert response.status_code == 200
    (suggestion,) = response.json()
    assert set(suggestion) == {"ticker", "name", "sic", "match", "market_cap", "in_set"}
    assert (suggestion["ticker"], suggestion["sic"], suggestion["match"]) == (
        "DE",
        "3523",
        "major group",
    )
    assert suggestion["in_set"] is False
    assert Decimal(suggestion["market_cap"]) > 0


def test_de_is_suggested_aapl_and_msft_gets_none(followed: TestClient) -> None:
    de = followed.get(f"{API}/companies/DE/peer-suggestions").json()
    assert [s["ticker"] for s in de] == ["AAPL"]
    assert followed.get(f"{API}/companies/MSFT/peer-suggestions").json() == []


def test_in_set_is_true_for_a_member_of_the_chosen_set(followed: TestClient) -> None:
    created = create(followed, "Peers", ["DE"])
    with_set = followed.get(SUGGESTIONS, params={"set_id": created["id"]}).json()
    assert [s["in_set"] for s in with_set] == [True]
    without = followed.get(SUGGESTIONS).json()
    assert [s["in_set"] for s in without] == [False]


def test_an_unknown_set_id_on_suggestions_is_a_404(followed: TestClient) -> None:
    assert followed.get(SUGGESTIONS, params={"set_id": 999}).status_code == 404


# --- comparison ------------------------------------------------------------------------------


def current_multiple(client: TestClient, ticker: str, code: str) -> Decimal | None:
    rows = client.get(f"{API}/companies/{ticker}/multiples").json()["rows"]
    raw = next(r for r in rows if r["code"] == code)["current"]
    return None if raw is None else Decimal(raw)


def last_ttm_ratio(client: TestClient, ticker: str, code: str, **params: str) -> Decimal | None:
    body = client.get(f"{API}/companies/{ticker}/ratios", params={"freq": "ttm", **params}).json()
    values = next(r for r in body["rows"] if r["code"] == code)["values"]
    last = next((v for v in reversed(values) if v is not None), None)
    return None if last is None else Decimal(last)


def ttm_revenue_growth(client: TestClient, ticker: str) -> Decimal | None:
    body = client.get(
        f"{API}/companies/{ticker}/statements", params={"type": "IS", "freq": "ttm"}
    ).json()
    raw = next(r for r in body["rows"] if r["code"] == "revenue")["yoy"][-1]
    return None if raw is None else Decimal(raw)


def test_the_comparison_has_the_documented_shape(followed: TestClient) -> None:
    created = create(followed)
    body = comparison(followed, created["id"])
    assert set(body) == {"ticker", "set_id", "name", "basis", "companies", "rows"}
    assert (body["ticker"], body["set_id"], body["name"], body["basis"]) == (
        "AAPL",
        created["id"],
        "Peers",
        "reported",
    )
    assert [c["ticker"] for c in body["companies"]] == ["AAPL", "COST", "DE", "MSFT"]
    assert set(body["companies"][0]) == {"ticker", "name", "price_date", "ttm_period"}
    for company in body["companies"]:
        ticker = company["ticker"]
        multiples = followed.get(f"{API}/companies/{ticker}/multiples").json()
        ttm = followed.get(f"{API}/companies/{ticker}/ratios", params={"freq": "ttm"}).json()
        assert company["price_date"] == multiples["price_date"] is not None
        assert company["ttm_period"] == ttm["periods"][-1]["label"]
        assert company["name"] == followed.get(f"{API}/companies/{ticker}").json()["name"]
    assert set(body["rows"][0]) == {
        "code",
        "label",
        "category",
        "unit",
        "target",
        "peers",
        "peer_median",
        "peer_min",
        "peer_max",
        "n",
        "target_vs_median",
        "target_rank",
        "caveats",
    }
    assert [r["category"] for r in body["rows"]][0] == "Valuation"
    assert body["rows"][-1]["code"] == "revenue_growth"
    assert all(len(r["peers"]) == 3 for r in body["rows"])


def _assert_cells_equal(
    cells: list[Any],
    expected: list[Decimal | None],
    code: str,  # target first, then the peers
) -> None:
    for got, want in zip(cells, expected, strict=True):
        assert (got is None) == (want is None), code
        if got is not None and want is not None:
            assert Decimal(got) == want, code


def test_valuation_cells_equal_each_companys_current_multiple(followed: TestClient) -> None:
    # One comparison for every code: it is the same response, only the row differs.
    body = comparison(followed, create(followed)["id"])
    for code in ("pe", "ev_ebitda", "ps", "fcf_yield"):
        r = row(body, code)
        expected = [current_multiple(followed, t, code) for t in ("AAPL", "COST", "DE", "MSFT")]
        _assert_cells_equal([r["target"], *r["peers"]], expected, code)


def test_ratio_cells_equal_each_companys_last_ttm_value(followed: TestClient) -> None:
    body = comparison(followed, create(followed)["id"])
    for code in ("gross_margin", "net_margin", "roe", "net_debt_to_ebitda", "ccc"):
        r = row(body, code)
        expected = [last_ttm_ratio(followed, t, code) for t in ("AAPL", "COST", "DE", "MSFT")]
        _assert_cells_equal([r["target"], *r["peers"]], expected, code)


def test_revenue_growth_is_the_ttm_revenue_yoy_of_each_company(followed: TestClient) -> None:
    r = row(comparison(followed, create(followed)["id"]), "revenue_growth")
    expected = [ttm_revenue_growth(followed, t) for t in ("AAPL", "COST", "DE", "MSFT")]
    assert all(e is not None for e in expected)
    assert [Decimal(v) for v in [r["target"], *r["peers"]]] == expected
    assert (r["label"], r["unit"], r["category"]) == ("Revenue growth (TTM YoY)", "pct", "Growth")


def test_the_median_of_three_peers_is_the_middle_value(followed: TestClient) -> None:
    r = row(comparison(followed, create(followed)["id"]), "gross_margin")
    peers = sorted(Decimal(v) for v in r["peers"])
    assert r["n"] == 3
    assert Decimal(r["peer_median"]) == peers[1]
    assert (Decimal(r["peer_min"]), Decimal(r["peer_max"])) == (peers[0], peers[2])
    assert Decimal(r["target_vs_median"]) == Decimal(r["target"]) - peers[1]
    assert r["target_rank"] == 1 + sum(p > Decimal(r["target"]) for p in peers)


def test_des_ev_rows_carry_the_deere_caveat(followed: TestClient) -> None:
    body = comparison(followed, create(followed)["id"])
    de_rows = followed.get(f"{API}/companies/DE/multiples").json()["rows"]
    expected = next(r for r in de_rows if r["code"] == "ev_ebitda")["caveat"]
    assert expected
    cells = row(body, "ev_ebitda")["caveats"]
    assert {"ticker": "DE", "text": expected} in cells
    assert all(c["ticker"] == "DE" for c in cells)
    assert row(body, "pe")["caveats"] == []


def test_a_set_with_no_members_compares_the_target_alone(followed: TestClient) -> None:
    body = comparison(followed, create(followed, "Alone", [])["id"])
    assert [c["ticker"] for c in body["companies"]] == ["AAPL"]
    r = row(body, "gross_margin")
    assert r["target"] is not None
    assert (r["peers"], r["peer_median"], r["n"]) == ([], None, 0)


def test_the_normalized_basis_changes_the_target_only(followed: TestClient) -> None:
    created = create(followed)
    periods = followed.get(f"{AAPL}/ratios", params={"freq": "ttm"}).json()["periods"]
    latest = periods[-1]
    adjustment = {
        "canonical_code": "sga",
        "fiscal_year": latest["fiscal_year"],
        "fiscal_period": latest["fiscal_period"],
        "amount": "-1000000000",
        "category": "one-off",
        "reason": "test",
    }
    assert followed.post(f"{AAPL}/adjustments", json=adjustment).status_code == 201

    reported = comparison(followed, created["id"])
    normalized = comparison(followed, created["id"], basis="normalized")
    assert normalized["basis"] == "normalized"

    before, after = row(reported, "net_margin"), row(normalized, "net_margin")
    assert Decimal(after["target"]) > Decimal(before["target"])
    assert after["peers"] == before["peers"]
    assert (after["peer_median"], after["n"]) == (before["peer_median"], before["n"])
    assert Decimal(after["target"]) == last_ttm_ratio(
        followed, "AAPL", "net_margin", basis="normalized"
    )


def test_the_basis_must_be_reported_or_normalized(followed: TestClient) -> None:
    created = create(followed)
    bad = followed.get(f"{SETS}/{created['id']}/comparison", params={"basis": "adjusted"})
    assert bad.status_code == 422


def test_an_unknown_set_id_on_comparison_is_a_404(followed: TestClient) -> None:
    assert followed.get(f"{SETS}/999/comparison").status_code == 404


def test_the_normalized_basis_applies_to_peers_too(followed: TestClient) -> None:
    created = create(followed)
    de = f"{API}/companies/DE"
    latest = followed.get(f"{de}/ratios", params={"freq": "ttm"}).json()["periods"][-1]
    adjustment = {
        "canonical_code": "sga",
        "fiscal_year": latest["fiscal_year"],
        "fiscal_period": latest["fiscal_period"],
        "amount": "-1000000000",
        "category": "one-off",
        "reason": "test",
    }
    assert followed.post(f"{de}/adjustments", json=adjustment).status_code == 201

    reported = row(comparison(followed, created["id"]), "net_margin")
    normalized = row(comparison(followed, created["id"], basis="normalized"), "net_margin")
    de_index = 1  # peers are COST, DE, MSFT
    assert Decimal(normalized["peers"][de_index]) == last_ttm_ratio(
        followed, "DE", "net_margin", basis="normalized"
    )
    assert Decimal(normalized["peers"][de_index]) > Decimal(reported["peers"][de_index])
    assert normalized["target"] == reported["target"]
