"""The statement routes over a followed AAPL (recorded fixtures, no network)."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

STATEMENTS = "/api/v1/companies/AAPL/statements"


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def _statement(client: TestClient, type_: str, freq: str, **extra: str) -> dict[str, object]:
    response = client.get(STATEMENTS, params={"type": type_, "freq": freq, **extra})
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def _row(body: dict[str, object], code: str) -> dict[str, object]:
    return next(r for r in body["rows"] if r["code"] == code)  # type: ignore[attr-defined,union-attr]


def test_statements_require_a_session(client: TestClient) -> None:
    for path in (STATEMENTS, f"{STATEMENTS}/cell", "/api/v1/companies/AAPL/mapping-gaps"):
        assert client.get(path).status_code == 401


def test_annual_income_statement_has_the_documented_shape(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "IS", "annual")

    assert (body["ticker"], body["statement"], body["freq"]) == ("AAPL", "IS", "annual")
    assert (body["basis"], body["currency"], body["balance_check"]) == ("reported", "USD", None)
    periods = body["periods"]
    assert len(periods) >= 10  # type: ignore[arg-type]
    assert set(periods[-1]) == {  # type: ignore[index]
        "key",
        "label",
        "fiscal_year",
        "fiscal_period",
        "period_start",
        "period_end",
        "is_forecast",
    }
    assert periods[-1]["is_forecast"] is False  # type: ignore[index]
    revenue = _row(body, "revenue")
    assert set(revenue) == {
        "code",
        "label",
        "unit",
        "kind",
        "depth",
        "values",
        "provenance",
        "yoy",
        "common_size",
    }
    for field in ("values", "provenance", "yoy", "common_size"):
        assert len(revenue[field]) == len(periods)  # type: ignore[arg-type]


def test_decimals_are_json_strings_and_ratios_are_fractions(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "IS", "annual")
    revenue = _row(body, "revenue")
    latest = revenue["values"][-1]  # type: ignore[index]

    assert isinstance(latest, str)
    assert Decimal(latest) > 10**11
    assert "." not in latest and "E" not in latest  # no Numeric(28, 10) padding
    yoy = revenue["yoy"][-1]  # type: ignore[index]
    assert yoy is None or (isinstance(yoy, str) and abs(Decimal(yoy)) < 5)
    assert _row(body, "eps_diluted")["unit"] == "USD/shares"


def test_no_period_is_empty_in_every_row(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "IS", "annual")

    columns = zip(*(r["values"] for r in body["rows"]), strict=True)  # type: ignore[attr-defined,union-attr]
    assert all(any(v is not None for v in column) for column in columns)


def test_quarterly_has_a_derived_q4(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "IS", "quarterly")
    revenue = _row(body, "revenue")

    q4 = [i for i, p in enumerate(body["periods"]) if p["fiscal_period"] == "Q4"]  # type: ignore[attr-defined,union-attr]
    assert q4
    assert all(revenue["provenance"][i] == "derived" for i in q4 if revenue["values"][i])  # type: ignore[index]


def test_balance_sheet_comes_with_an_all_ok_balance_check(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "BS", "quarterly")

    checks = body["balance_check"]
    assert checks and len(checks) == len(body["periods"])  # type: ignore[arg-type]
    assert all(c["ok"] for c in checks)  # type: ignore[union-attr]
    assert set(checks[0]) == {"period_key", "difference", "ok"}  # type: ignore[index]


def test_ttm_income_statement_is_served(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "IS", "ttm")

    assert body["periods"][-1]["key"].startswith("TTM-")  # type: ignore[index]


def test_a_ttm_balance_sheet_is_a_422(aapl_client: TestClient) -> None:
    response = aapl_client.get(STATEMENTS, params={"type": "BS", "freq": "ttm"})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [{"type": "XX", "freq": "annual"}, {"type": "IS", "freq": "weekly"}, {"freq": "annual"}],
)
def test_bad_query_values_are_a_422(aapl_client: TestClient, params: dict[str, str]) -> None:
    assert aapl_client.get(STATEMENTS, params=params).status_code == 422


def test_normalized_equals_reported_until_adjustments_exist(aapl_client: TestClient) -> None:
    reported = _statement(aapl_client, "IS", "annual")
    normalized = _statement(aapl_client, "IS", "annual", basis="normalized")

    assert normalized["basis"] == "normalized"
    assert normalized["rows"] == reported["rows"] and normalized["periods"] == reported["periods"]


def test_statements_of_an_unfollowed_company_are_a_404(authed_client: TestClient) -> None:
    response = authed_client.get(STATEMENTS, params={"type": "IS", "freq": "annual"})

    assert response.status_code == 404


def test_a_reported_cell_has_source_filing_and_vintages(aapl_client: TestClient) -> None:
    year = _statement(aapl_client, "IS", "annual")["periods"][-1]["fiscal_year"]  # type: ignore[index]

    response = aapl_client.get(
        f"{STATEMENTS}/cell", params={"code": "revenue", "fiscal_year": year, "fiscal_period": "FY"}
    )

    assert response.status_code == 200
    cell = response.json()
    assert (cell["code"], cell["label"], cell["fiscal_period"]) == ("revenue", "Revenue", "FY")
    assert cell["provenance"] == "reported"
    assert set(cell["source"]) == {"taxonomy", "concept", "unit"}
    assert set(cell["filing"]) == {"accession_no", "form", "filed_at"}
    assert cell["filing"]["form"].startswith("10-K")
    assert cell["derivation"] is None
    assert cell["vintages"] and set(cell["vintages"][0]) == {
        "value",
        "accession_no",
        "form",
        "filed_at",
    }
    assert cell["adjustments"] == []
    assert isinstance(cell["value"], str)


def test_a_derived_cell_has_its_derivation(aapl_client: TestClient) -> None:
    quarterly = _statement(aapl_client, "IS", "quarterly")
    q4 = next(p for p in reversed(quarterly["periods"]) if p["fiscal_period"] == "Q4")  # type: ignore[attr-defined,union-attr]

    cell = aapl_client.get(
        f"{STATEMENTS}/cell",
        params={"code": "revenue", "fiscal_year": q4["fiscal_year"], "fiscal_period": "Q4"},
    ).json()

    assert cell["provenance"] == "derived"
    assert cell["source"] is None and cell["filing"] is None
    assert cell["derivation"]["formula"]
    assert {"code", "fiscal_period", "value"} <= set(cell["derivation"]["inputs"][0])


@pytest.mark.parametrize(
    "params",
    [
        {"code": "nope", "fiscal_year": 2024, "fiscal_period": "FY"},
        {"code": "revenue", "fiscal_year": 1850, "fiscal_period": "FY"},
        {"code": "revenue", "fiscal_year": 2024, "fiscal_period": "Q9"},
    ],
)
def test_an_unknown_cell_is_a_404(aapl_client: TestClient, params: dict[str, object]) -> None:
    assert aapl_client.get(f"{STATEMENTS}/cell", params=params).status_code == 404


def test_mapping_gaps_list_missing_items_and_unmapped_concepts(aapl_client: TestClient) -> None:
    response = aapl_client.get("/api/v1/companies/AAPL/mapping-gaps")

    assert response.status_code == 200
    gaps = response.json()
    missing = {m["code"]: m for m in gaps["missing_items"]}
    assert set(missing["short_term_debt"]) == {"code", "label", "statement", "missing_periods"}
    assert missing["short_term_debt"]["statement"] == "BS"
    assert missing["short_term_debt"]["missing_periods"]
    unmapped = gaps["unmapped_concepts"][0]
    assert set(unmapped) == {
        "taxonomy",
        "concept",
        "unit",
        "latest_value",
        "latest_period_end",
        "facts",
        "suggested_codes",
    }
    assert isinstance(unmapped["latest_value"], str)
    assert isinstance(unmapped["suggested_codes"], list)
    suggested = [bool(u["suggested_codes"]) for u in gaps["unmapped_concepts"]]
    assert suggested[0] and suggested == sorted(suggested, reverse=True)  # suggested ones first


def test_the_openapi_schema_types_decimals_as_strings(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    row = schemas["RowOut"]["properties"]["values"]["items"]
    assert any(option.get("type") == "string" for option in row["anyOf"])
    assert not any(option.get("type") == "number" for option in row["anyOf"])
