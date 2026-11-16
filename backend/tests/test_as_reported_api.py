"""`GET /companies/{ticker}/as-reported` (M7d S1, docs/erd/face-tree.md "As reported route"):
one filing's statement as filed, over AAPL's recorded filings (no network)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo

AS_REPORTED = "/api/v1/companies/AAPL/as-reported"
NEWEST_10K = "0000320193-25-000079"
NEWEST_10Q = "0000320193-26-000020"
FY2010_10K = "0001193125-10-238044"
LINE_FIELDS = {
    "position",
    "taxonomy",
    "concept",
    "label",
    "unit",
    "depth",
    "is_total",
    "in_tree",
    "kind",
    "codes",
    "block",
    "values",
    "foots",
    "missing_children",
}


def _aapl(db_session: Session, seed_db: Callable[..., None]) -> Company:
    seed_db("AAPL")
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    return company


@pytest.fixture
def parsed(
    db_session: Session, seed_db: Callable[..., None], authed_client: TestClient
) -> TestClient:
    from tests.seed import read_recorded_filings

    read_recorded_filings(db_session, _aapl(db_session, seed_db))
    return authed_client


def _get(client: TestClient, **params: str) -> dict[str, Any]:
    response = client.get(AS_REPORTED, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _line(body: dict[str, Any], concept: str) -> dict[str, Any]:
    return next(ln for ln in body["lines"] if ln["concept"] == concept)


def test_the_route_requires_a_session(client: TestClient) -> None:
    assert client.get(AS_REPORTED, params={"statement": "BS"}).status_code == 401


def test_the_default_filing_is_the_newest_10k(parsed: TestClient) -> None:
    body = _get(parsed, statement="BS")

    assert set(body) == {"filing", "filings", "periods", "foots", "lines"}
    assert body["filing"] == {"accession_no": NEWEST_10K, "form": "10-K", "filed_at": "2025-10-31"}
    assert [f["accession_no"] for f in body["filings"]] == [
        NEWEST_10Q,
        NEWEST_10K,
        "0000320193-24-000123",
        FY2010_10K,
    ]
    assert body["filings"][0]["form"] == "10-Q"


def test_the_lines_are_placed_against_the_canonical_rows(parsed: TestClient) -> None:
    body = _get(parsed, statement="BS")

    assert body["periods"] == [
        {"start": None, "end": "2025-09-27"},
        {"start": None, "end": "2024-09-28"},
    ]
    assert body["foots"] is True
    assets = _line(body, "Assets")
    assert set(assets) == LINE_FIELDS
    assert assets["label"] == "Total assets"
    assert (assets["kind"], assets["is_total"], assets["depth"], assets["block"]) == (
        "mapped",
        True,
        0,
        None,
    )
    assert assets["codes"] == [{"code": "total_assets", "label": "Total assets"}]
    assert assets["foots"] == [True, True]
    assert all(isinstance(v, str) for v in assets["values"])  # decimals as JSON strings
    assert Decimal(assets["values"][0]) > 0
    cash = _line(body, "CashAndCashEquivalentsAtCarryingValue")
    assert cash["block"] == {"code": "total_current_assets", "label": "Total current assets"}
    assert cash["unit"] == "USD"
    assert [ln["position"] for ln in body["lines"]] == sorted(
        ln["position"] for ln in body["lines"]
    )


def test_a_named_accession_is_served(parsed: TestClient) -> None:
    body = _get(parsed, statement="IS", accession=FY2010_10K)

    assert body["filing"]["accession_no"] == FY2010_10K
    assert body["lines"]
    assert all(len(ln["values"]) == len(body["periods"]) for ln in body["lines"])


@pytest.mark.parametrize("accession", ["0000000000-00-000000", "not-an-accession"])
def test_an_accession_that_is_not_a_parsed_filing_is_a_404(
    parsed: TestClient, accession: str
) -> None:
    response = parsed.get(AS_REPORTED, params={"statement": "CF", "accession": accession})

    assert response.status_code == 404
    assert accession in response.json()["detail"]


def test_an_unknown_statement_is_a_422(parsed: TestClient) -> None:
    assert parsed.get(AS_REPORTED, params={"statement": "EQ"}).status_code == 422


def test_an_unfollowed_company_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(AS_REPORTED, params={"statement": "BS"}).status_code == 404


def test_a_company_with_no_parsed_filing_has_an_empty_view(
    db_session: Session, seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    _aapl(db_session, seed_db)

    body = _get(authed_client, statement="BS")

    assert body == {"filing": None, "filings": [], "periods": [], "foots": None, "lines": []}


def test_without_a_parsed_10k_the_newest_parsed_filing_is_the_default(
    db_session: Session, seed_db: Callable[..., None], authed_client: TestClient
) -> None:
    from bedrock.ingest.sources import Sources
    from bedrock.services.filings import ingest_filings

    from .fakes import FakeEdgar, FakeFilings, FakePrices

    company = _aapl(db_session, seed_db)
    sources = Sources(edgar=FakeEdgar(), prices=FakePrices(), filings=FakeFilings())
    ingest_filings(db_session, sources, company, limit=1)  # newest first: the 10-Q only

    body = _get(authed_client, statement="BS")

    assert body["filing"]["accession_no"] == NEWEST_10Q
    assert [f["accession_no"] for f in body["filings"]] == [NEWEST_10Q]
