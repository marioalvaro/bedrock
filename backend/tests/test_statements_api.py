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
        "common_size_base",
        "adjustable",
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


def test_common_size_defaults_to_revenue_and_total_assets(aapl_client: TestClient) -> None:
    income = _statement(aapl_client, "IS", "annual")
    balance = _statement(aapl_client, "BS", "annual")

    assert {r["common_size_base"] for r in income["rows"]} == {"Revenue"}  # type: ignore[attr-defined,union-attr]
    assert {r["common_size_base"] for r in balance["rows"]} == {"Total assets"}  # type: ignore[attr-defined,union-attr]
    assert _row(income, "revenue")["common_size"][-1] == "1.000000"  # type: ignore[index]


def test_common_size_base_parent_divides_by_the_parent_row(aapl_client: TestClient) -> None:
    income = _statement(aapl_client, "IS", "annual", common_size_base="parent")
    balance = _statement(aapl_client, "BS", "annual", common_size_base="parent")

    assert _row(income, "rnd")["common_size_base"] == "Total operating costs"
    assert _row(income, "revenue")["common_size_base"] == "Revenue"  # a root keeps the total base
    assert _row(balance, "cash")["common_size_base"] == "Total current assets"
    assert _row(balance, "total_current_assets")["common_size_base"] == "Total assets"
    total_assets = _row(balance, "total_assets")["common_size"]
    assert total_assets[-1] == "1.000000"  # type: ignore[index]
    cash = Decimal(_row(balance, "cash")["common_size"][-1])  # type: ignore[index,arg-type]
    assert 0 < cash < 1


def test_a_bad_common_size_base_is_a_422(aapl_client: TestClient) -> None:
    response = aapl_client.get(
        STATEMENTS, params={"type": "IS", "freq": "annual", "common_size_base": "peers"}
    )

    assert response.status_code == 422


def test_normalized_equals_reported_while_there_are_no_adjustments(aapl_client: TestClient) -> None:
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
    assert cell["adjustments"] == [] and cell["normalized_value"] is None
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


def test_an_inferred_zero_has_its_own_provenance_and_derivation(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "IS", "annual")
    row = _row(body, "net_income_nci")
    assert set(row["provenance"]) == {"zero_inferred"}  # type: ignore[arg-type]
    assert set(row["values"]) == {"0"}  # type: ignore[arg-type]
    year = body["periods"][-1]["fiscal_year"]  # type: ignore[index]

    cell = aapl_client.get(
        f"{STATEMENTS}/cell",
        params={"code": "net_income_nci", "fiscal_year": year, "fiscal_period": "FY"},
    ).json()

    assert (cell["value"], cell["provenance"]) == ("0", "zero_inferred")
    assert cell["source"] is None and cell["filing"] is None
    assert cell["derivation"]["formula"].startswith(
        "no NCI-inclusive total or NCI concept tagged in 10-K "
    )
    assert cell["derivation"]["inputs"] == []


def test_an_identity_solved_cell_explains_the_identity(aapl_client: TestClient) -> None:
    body = _statement(aapl_client, "BS", "annual")
    row = _row(body, "temporary_equity")
    latest = len(row["values"]) - 1  # type: ignore[arg-type]
    assert (row["values"][latest], row["provenance"][latest]) == ("0", "zero_inferred")  # type: ignore[index]

    cell = aapl_client.get(
        f"{STATEMENTS}/cell",
        params={
            "code": "temporary_equity",
            "fiscal_year": body["periods"][latest]["fiscal_year"],  # type: ignore[index]
            "fiscal_period": "FY",
        },
    ).json()

    assert cell["derivation"]["formula"] == (
        "identity balance_sheet: temporary_equity = "
        "total_liabilities_and_equity - total_liabilities - total_equity"
    )
    assert [i["code"] for i in cell["derivation"]["inputs"]] == [
        "total_liabilities_and_equity",
        "total_liabilities",
        "total_equity",
    ]


def _annual(client: TestClient, code: str) -> dict[int, str]:
    body = _statement(client, "IS", "annual")
    values = _row(body, code)["values"]
    return {
        p["fiscal_year"]: v  # type: ignore[index]
        for p, v in zip(body["periods"], values, strict=True)  # type: ignore[arg-type]
    }


def test_per_share_figures_are_split_adjusted_by_filing_date(aapl_client: TestClient) -> None:
    eps = _annual(aapl_client, "eps_diluted")

    assert Decimal(eps[2013]) == Decimal("1.42")  # 5.68 in the FY2015 10-K, before the 4-for-1
    assert Decimal(eps[2019]) == Decimal("2.97")  # its newest filing is after the last split
    assert Decimal(eps[2020]) / Decimal(eps[2019]) < 2  # no 4x jump across the 2020 split


def test_share_counts_are_multiplied_by_later_splits(aapl_client: TestClient) -> None:
    shares = _annual(aapl_client, "shares_diluted")

    assert Decimal(shares[2013]) == Decimal(6_521_634_000) * 4
    assert Decimal(shares[2019]) == Decimal(18_595_651_000)


def test_a_split_adjusted_cell_shows_its_derivation_and_as_reported_vintages(
    aapl_client: TestClient,
) -> None:
    cell = aapl_client.get(
        f"{STATEMENTS}/cell",
        params={"code": "eps_diluted", "fiscal_year": 2013, "fiscal_period": "FY"},
    ).json()

    assert Decimal(cell["value"]) == Decimal("1.42") and cell["provenance"] == "derived"
    assert cell["derivation"]["formula"] == "as reported ÷ 4 (split 2020-08-31)"
    assert [
        (i["code"], i["fiscal_period"], Decimal(i["value"])) for i in cell["derivation"]["inputs"]
    ] == [("eps_diluted", "FY", Decimal("5.68"))]
    assert cell["filing"]["filed_at"] == "2015-10-28"
    assert Decimal("5.68") in {Decimal(v["value"]) for v in cell["vintages"]}
    assert all(
        Decimal(v["value"]) not in (Decimal("1.42"), Decimal("1.4200")) for v in cell["vintages"]
    )


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
        "classification",
    }
    assert isinstance(unmapped["latest_value"], str)
    assert isinstance(unmapped["suggested_codes"], list)
    unclassified = [u for u in gaps["unmapped_concepts"] if u["classification"] is None]
    suggested = [bool(u["suggested_codes"]) for u in unclassified]
    assert suggested == sorted(suggested, reverse=True)  # suggested ones first, among the open ones


def test_mapping_gaps_carry_the_triage_verdict_and_list_the_classified_last(
    aapl_client: TestClient,
) -> None:
    gaps = aapl_client.get("/api/v1/companies/AAPL/mapping-gaps").json()["unmapped_concepts"]

    by_name = {u["concept"]: u for u in gaps}
    ladder = by_name["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"]
    assert set(ladder["classification"]) == {"type", "reason", "codes"}
    assert ladder["classification"]["type"] == "disclosure"
    assert ladder["classification"]["reason"]
    assert ladder["suggested_codes"]  # a classified concept keeps its suggestion
    component = by_name["LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"]
    assert isinstance(component["classification"]["codes"], list)
    classified = [u["classification"] is not None for u in gaps]
    assert classified == sorted(classified)  # every unclassified concept before the classified
    assert any(classified)


def test_the_openapi_schema_types_decimals_as_strings(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    row = schemas["RowOut"]["properties"]["values"]["items"]
    assert any(option.get("type") == "string" for option in row["anyOf"])
    assert not any(option.get("type") == "number" for option in row["anyOf"])
