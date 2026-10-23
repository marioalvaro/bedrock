"""Segment and KPI series through the API (FR-DATA-11), on the AAPL fixtures."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.models.segment_series import SegmentSeries
from bedrock.models.segment_value import SegmentValue

COMPANY = "/api/v1/companies/AAPL"
GRID = f"{COMPANY}/segments"
IMPORT = f"{GRID}/import"
SERIES = f"{COMPANY}/segment-series"
GEO_CSV = (Path(__file__).parent / "fixtures" / "segments" / "AAPL_geo.csv").read_text()

NEW_SERIES = {"dimension": "business", "name": "iPhone", "metric": "revenue", "unit": "USD"}
KPI = {"dimension": "kpi", "name": "Stores", "metric": "stores", "unit": "count"}


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def grid(client: TestClient, **params: str) -> dict[str, Any]:
    response = client.get(GRID, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def create(client: TestClient, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post(SERIES, json=body or NEW_SERIES)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def column(body: dict[str, Any], key: str) -> int:
    return [p["key"] for p in body["periods"]].index(key)


# --- guards ----------------------------------------------------------------------------------


def test_every_segment_route_requires_a_session(client: TestClient) -> None:
    values = {"values": []}
    imp = {"dimension": "geo", "text": GEO_CSV, "scale": "M"}
    assert client.get(GRID).status_code == 401
    assert client.post(SERIES, json=NEW_SERIES).status_code == 401
    assert client.put(f"{SERIES}/1", json={"name": "x", "display_order": 1}).status_code == 401
    assert client.delete(f"{SERIES}/1").status_code == 401
    assert client.put(f"{SERIES}/1/values", json=values).status_code == 401
    assert client.post(IMPORT, json=imp).status_code == 401


def test_an_unfollowed_ticker_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get(GRID).status_code == 404
    assert authed_client.post(SERIES, json=NEW_SERIES).status_code == 404
    assert authed_client.delete(f"{SERIES}/1").status_code == 404
    imp = {"dimension": "geo", "text": GEO_CSV, "scale": "M"}
    assert authed_client.post(IMPORT, json=imp).status_code == 404


# --- series CRUD -----------------------------------------------------------------------------


def test_create_update_and_delete_a_series(aapl_client: TestClient) -> None:
    created = create(aapl_client)
    assert set(created) == {"id", "dimension", "name", "metric", "unit", "display_order"}
    assert (created["dimension"], created["name"], created["unit"]) == ("business", "iPhone", "USD")

    url = f"{SERIES}/{created['id']}"
    updated = aapl_client.put(url, json={"name": " Phone ", "display_order": 7})
    assert updated.status_code == 200, updated.text
    assert (updated.json()["name"], updated.json()["display_order"]) == ("Phone", 7)
    assert updated.json()["unit"] == "USD"

    assert aapl_client.delete(url).status_code == 204
    assert aapl_client.delete(url).status_code == 404
    assert grid(aapl_client)["blocks"] == []


def test_a_series_of_another_company_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    created = create(aapl_client)
    theirs = f"/api/v1/companies/MSFT/segment-series/{created['id']}"

    assert aapl_client.put(theirs, json={"name": "x", "display_order": 1}).status_code == 404
    assert aapl_client.put(f"{theirs}/values", json={"values": []}).status_code == 404
    assert aapl_client.delete(theirs).status_code == 404
    assert grid(aapl_client)["blocks"][0]["series"][0]["name"] == "iPhone"


@pytest.mark.parametrize(
    "override",
    [
        {"name": "   "},
        {"dimension": "region"},
        {"unit": "EUR"},
        {"unit": "pct"},  # business/geo are USD only
    ],
)
def test_an_invalid_series_is_a_422(aapl_client: TestClient, override: dict[str, str]) -> None:
    response = aapl_client.post(SERIES, json={**NEW_SERIES, **override})
    assert response.status_code == 422, response.text
    assert grid(aapl_client)["blocks"] == []


def test_a_duplicate_kpi_code_is_a_422(aapl_client: TestClient) -> None:
    create(aapl_client, KPI)
    response = aapl_client.post(SERIES, json={**KPI, "name": "Other stores"})
    assert response.status_code == 422, response.text
    assert "detail" in response.json()


# --- values and the grid ---------------------------------------------------------------------


def test_values_upsert_and_null_deletes(aapl_client: TestClient) -> None:
    created = create(aapl_client)
    url = f"{SERIES}/{created['id']}/values"
    cells = [
        {"fiscal_year": 2024, "fiscal_period": "FY", "value": "1000"},
        {"fiscal_year": 2023, "fiscal_period": "FY", "value": "900"},
    ]
    response = aapl_client.put(url, json={"values": cells})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == created["id"]

    body = grid(aapl_client)
    row = body["blocks"][0]["series"][0]
    assert Decimal(row["values"][column(body, "FY2024")]) == 1000
    assert Decimal(row["values"][column(body, "FY2023")]) == 900

    edit = {"values": [{"fiscal_year": 2024, "fiscal_period": "FY", "value": "1100"}]}
    assert aapl_client.put(url, json=edit).status_code == 200
    delete = {"values": [{"fiscal_year": 2023, "fiscal_period": "FY", "value": None}]}
    assert aapl_client.put(url, json=delete).status_code == 200

    body = grid(aapl_client)
    row = body["blocks"][0]["series"][0]
    assert Decimal(row["values"][column(body, "FY2024")]) == 1100
    assert row["values"][column(body, "FY2023")] is None


def test_quarterly_grid_shows_only_quarter_values_and_blocks_keep_their_order(
    aapl_client: TestClient,
) -> None:
    kpi = create(aapl_client, KPI)
    geo = create(aapl_client, {**NEW_SERIES, "dimension": "geo", "name": "Americas"})
    biz = create(aapl_client, {**NEW_SERIES, "metric": "operating_income"})
    cells = [
        {"fiscal_year": 2024, "fiscal_period": "FY", "value": "10"},
        {"fiscal_year": 2024, "fiscal_period": "Q1", "value": "3"},
    ]
    for series in (kpi, geo, biz):
        assert (
            aapl_client.put(f"{SERIES}/{series['id']}/values", json={"values": cells}).status_code
            == 200
        )

    body = grid(aapl_client, freq="quarterly")
    assert body["ticker"] == "AAPL" and body["freq"] == "quarterly"
    assert all(p["fiscal_period"] != "FY" for p in body["periods"])
    assert [(b["dimension"], b["metric"]) for b in body["blocks"]] == [
        ("business", "operating_income"),
        ("geo", "revenue"),
        ("kpi", None),
    ]
    assert body["blocks"][-1]["unallocated"] is None
    for block in body["blocks"]:
        values = block["series"][0]["values"]
        assert Decimal(values[column(body, "FY2024Q1")]) == 3
        assert len([v for v in values if v is not None]) == 1

    annual = grid(aapl_client)
    assert annual["freq"] == "annual"
    assert all(p["fiscal_period"] == "FY" for p in annual["periods"])


def test_an_invalid_freq_is_a_422(aapl_client: TestClient) -> None:
    assert aapl_client.get(GRID, params={"freq": "ttm"}).status_code == 422


# --- import ----------------------------------------------------------------------------------


def import_geo(client: TestClient, text: str = GEO_CSV) -> Any:
    return client.post(IMPORT, json={"dimension": "geo", "text": text, "scale": "M"})


def test_importing_apple_geography_reconciles_to_revenue(aapl_client: TestClient) -> None:
    response = import_geo(aapl_client)

    assert response.status_code == 200, response.text
    assert response.json() == {"series_created": 5, "values_created": 5, "values_updated": 0}

    # Apple FY2024 10-K, Note 13 "Segment Information and Geographic Data": net sales by reportable
    # segment sum to total net sales of $391,035 million, so there is no unallocated remainder.
    body = grid(aapl_client)
    assert [(b["dimension"], b["metric"]) for b in body["blocks"]] == [("geo", "revenue")]
    block = body["blocks"][0]
    index = column(body, "FY2024")
    assert [s["name"] for s in block["series"]] == [
        "Americas",
        "Europe",
        "Greater China",
        "Japan",
        "Rest of Asia Pacific",
    ]
    assert Decimal(block["series"][0]["values"][index]) == 167_045_000_000
    assert Decimal(block["unallocated"][index]) == 0


def test_a_second_identical_import_only_updates(aapl_client: TestClient) -> None:
    assert import_geo(aapl_client).status_code == 200

    response = import_geo(aapl_client)

    assert response.status_code == 200, response.text
    assert response.json() == {"series_created": 0, "values_created": 0, "values_updated": 5}


def test_a_bad_import_lists_every_error_and_stores_nothing(aapl_client: TestClient) -> None:
    text = (
        "name,metric,unit,FY2024\n"
        "Americas,revenue,USD,167045\n"
        "Europe,revenue,USD,abc\n"
        "Japan,revenue,USD,12x\n"
    )

    response = import_geo(aapl_client, text)

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"]
    assert len(body["errors"]) == 2
    for error in body["errors"]:
        assert set(error) == {"row", "column", "message"}
        assert error["message"]
    assert [(e["row"], e["column"]) for e in body["errors"]] == [(3, 4), (4, 4)]
    assert grid(aapl_client)["blocks"] == []


# --- lifecycle -------------------------------------------------------------------------------


def test_deleting_the_company_removes_its_series(
    aapl_client: TestClient, db_session: Session
) -> None:
    assert import_geo(aapl_client).status_code == 200
    assert _count(db_session, SegmentSeries) == 5 and _count(db_session, SegmentValue) == 5
    assert aapl_client.delete(COMPANY).status_code == 204

    assert _count(db_session, SegmentSeries) == 0 and _count(db_session, SegmentValue) == 0
    assert aapl_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    assert grid(aapl_client)["blocks"] == []


# --- more edge cases -------------------------------------------------------------------------


def test_unallocated_ignores_adjustments(aapl_client: TestClient) -> None:
    adjustment = {
        "canonical_code": "revenue",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "amount": "1000000000",
        "category": "one-off",
        "reason": "test",
    }
    posted = aapl_client.post(f"{COMPANY}/adjustments", json=adjustment)
    assert posted.status_code == 201, posted.text
    assert import_geo(aapl_client).status_code == 200

    body = grid(aapl_client)

    assert Decimal(body["blocks"][0]["unallocated"][column(body, "FY2024")]) == 0


def test_grid_periods_equal_the_income_statement_periods(aapl_client: TestClient) -> None:
    assert import_geo(aapl_client).status_code == 200
    statement = aapl_client.get(f"{COMPANY}/statements", params={"type": "IS", "freq": "annual"})
    assert statement.status_code == 200, statement.text

    body = grid(aapl_client)

    assert [p["key"] for p in body["periods"]] == [p["key"] for p in statement.json()["periods"]]


def test_a_value_before_xbrl_adds_a_dateless_period(aapl_client: TestClient) -> None:
    created = create(aapl_client)
    cells = [{"fiscal_year": 2001, "fiscal_period": "FY", "value": "5"}]
    assert (
        aapl_client.put(f"{SERIES}/{created['id']}/values", json={"values": cells}).status_code
        == 200
    )
    statement = aapl_client.get(f"{COMPANY}/statements", params={"type": "IS", "freq": "annual"})
    reported = {p["key"]: p for p in statement.json()["periods"]}

    body = grid(aapl_client)

    first = body["periods"][0]
    assert first["key"] == "FY2001"
    assert first["period_start"] is None and first["period_end"] is None
    fy24 = body["periods"][column(body, "FY2024")]
    assert fy24["period_start"] == reported["FY2024"]["period_start"]
    assert fy24["period_end"] == reported["FY2024"]["period_end"]


def test_an_unknown_ticker_is_a_404_on_series_and_values_updates(
    aapl_client: TestClient,
) -> None:
    missing = "/api/v1/companies/ZZZZ/segment-series/1"

    assert aapl_client.put(missing, json={"name": "x", "display_order": 1}).status_code == 404
    assert aapl_client.put(f"{missing}/values", json={"values": []}).status_code == 404


def test_a_blank_name_on_update_is_a_422(aapl_client: TestClient) -> None:
    created = create(aapl_client)

    response = aapl_client.put(f"{SERIES}/{created['id']}", json={"name": " ", "display_order": 1})

    assert response.status_code == 422, response.text
    assert grid(aapl_client)["blocks"][0]["series"][0]["name"] == "iPhone"


@pytest.mark.parametrize("order", [-1, 1_000_001, 2**63])
def test_an_out_of_range_display_order_is_a_422(aapl_client: TestClient, order: int) -> None:
    created = create(aapl_client)

    response = aapl_client.put(
        f"{SERIES}/{created['id']}", json={"name": "iPhone", "display_order": order}
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("year", [2**63, 20244, -5, 999, 10000])
def test_an_out_of_range_fiscal_year_is_a_422(aapl_client: TestClient, year: int) -> None:
    created = create(aapl_client)
    cells = [{"fiscal_year": year, "fiscal_period": "FY", "value": "1"}]

    response = aapl_client.put(f"{SERIES}/{created['id']}/values", json={"values": cells})

    assert response.status_code == 422, response.text


def test_an_unknown_fiscal_period_is_a_422(aapl_client: TestClient) -> None:
    created = create(aapl_client)
    cells = [{"fiscal_year": 2024, "fiscal_period": "H1", "value": "1"}]

    response = aapl_client.put(f"{SERIES}/{created['id']}/values", json={"values": cells})

    assert response.status_code == 422, response.text


def test_an_unknown_scale_or_dimension_on_import_is_a_422(aapl_client: TestClient) -> None:
    bad_scale = {"dimension": "geo", "text": GEO_CSV, "scale": "T"}
    bad_dimension = {"dimension": "region", "text": GEO_CSV, "scale": "M"}

    assert aapl_client.post(IMPORT, json=bad_scale).status_code == 422
    assert aapl_client.post(IMPORT, json=bad_dimension).status_code == 422


# --- fill annual from quarterly (S4f) --------------------------------------------------------

FILL = f"{GRID}/fill-annual"


def put_values(client: TestClient, series_id: int, values: dict[str, str | None]) -> None:
    """`values` maps "FY2024" or "Q1 FY2024" style keys, e.g. {"Q1:2024": "10"}, to amounts."""
    body = []
    for key, amount in values.items():
        period, year = key.split(":")
        body.append({"fiscal_year": int(year), "fiscal_period": period, "value": amount})
    response = client.put(f"{SERIES}/{series_id}/values", json={"values": body})
    assert response.status_code == 200, response.text


def quarters(year: int, *amounts: str) -> dict[str, str | None]:
    return {f"Q{i}:{year}": a for i, a in enumerate(amounts, start=1)}


def annual(client: TestClient, series_id: int, year: int) -> Decimal | None:
    body = grid(client, freq="annual")
    for block in body["blocks"]:
        for row in block["series"]:
            if row["id"] == series_id:
                value = row["values"][column(body, f"FY{year}")]
                return None if value is None else Decimal(value)
    raise AssertionError("series not in the grid")


def fill(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post(FILL, json=body)
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    return out


def test_fill_annual_requires_a_session(client: TestClient) -> None:
    assert client.post(FILL, json={}).status_code == 401


def test_fill_annual_on_an_unfollowed_ticker_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.post(FILL, json={}).status_code == 404


def test_fill_annual_sums_the_quarters_into_the_fy_value(aapl_client: TestClient) -> None:
    sid = create(aapl_client)["id"]
    put_values(aapl_client, sid, quarters(2024, "10.5", "20", "30", "40.25"))

    out = fill(aapl_client)

    assert out == {"values_created": 1, "values_overwritten": 0, "values_unchanged": 0}
    assert annual(aapl_client, sid, 2024) == Decimal("100.75")


def test_fill_annual_dry_run_reports_the_counts_and_writes_nothing(
    aapl_client: TestClient, db_session: Session
) -> None:
    sid = create(aapl_client)["id"]
    put_values(aapl_client, sid, {**quarters(2024, "1", "2", "3", "4"), "FY:2024": "7"})
    before = _count(db_session, SegmentValue)

    out = fill(aapl_client, dry_run=True)

    assert out == {"values_created": 0, "values_overwritten": 1, "values_unchanged": 0}
    assert annual(aapl_client, sid, 2024) == Decimal("7")
    db_session.expire_all()
    assert _count(db_session, SegmentValue) == before


def test_fill_annual_overwrites_a_different_fy_value_and_counts_an_equal_one_unchanged(
    aapl_client: TestClient,
) -> None:
    sid = create(aapl_client)["id"]
    put_values(
        aapl_client,
        sid,
        {
            **quarters(2023, "1", "2", "3", "4"),
            "FY:2023": "10",  # equal to the sum
            **quarters(2024, "5", "5", "5", "5"),
            "FY:2024": "99",  # differs
            **quarters(2022, "1", "1", "1", "1"),  # no FY yet
        },
    )

    out = fill(aapl_client)

    assert out == {"values_created": 1, "values_overwritten": 1, "values_unchanged": 1}
    assert annual(aapl_client, sid, 2024) == Decimal("20")
    assert annual(aapl_client, sid, 2022) == Decimal("4")
    assert annual(aapl_client, sid, 2023) == Decimal("10")


def test_fill_annual_is_idempotent(aapl_client: TestClient) -> None:
    sid = create(aapl_client)["id"]
    put_values(aapl_client, sid, quarters(2024, "1", "2", "3", "4"))
    fill(aapl_client)

    assert fill(aapl_client) == {
        "values_created": 0,
        "values_overwritten": 0,
        "values_unchanged": 1,
    }


def test_fill_annual_leaves_incomplete_years_and_non_additive_units_alone(
    aapl_client: TestClient,
) -> None:
    usd = create(aapl_client)["id"]
    put_values(aapl_client, usd, quarters(2024, "1", "2", "3"))  # Q4 missing
    stores = create(aapl_client, KPI)["id"]
    put_values(aapl_client, stores, quarters(2024, "1", "2", "3", "4"))
    pct = create(aapl_client, {"dimension": "kpi", "name": "GM", "metric": "gm", "unit": "pct"})[
        "id"
    ]
    put_values(aapl_client, pct, quarters(2024, "0.1", "0.1", "0.1", "0.1"))

    out = fill(aapl_client)

    assert out == {"values_created": 0, "values_overwritten": 0, "values_unchanged": 0}
    for sid in (usd, stores, pct):
        assert annual(aapl_client, sid, 2024) is None


def test_fill_annual_with_no_series_is_all_zero(aapl_client: TestClient) -> None:
    assert fill(aapl_client) == {
        "values_created": 0,
        "values_overwritten": 0,
        "values_unchanged": 0,
    }


def test_fill_annual_refuses_a_sum_over_the_limit_and_writes_nothing(
    aapl_client: TestClient,
) -> None:
    ok = create(aapl_client)["id"]
    put_values(aapl_client, ok, quarters(2024, "1", "1", "1", "1"))
    big = create(aapl_client, {**NEW_SERIES, "name": "Big"})["id"]
    put_values(aapl_client, big, quarters(2024, *["600000000000000"] * 4))

    response = aapl_client.post(FILL, json={})

    assert response.status_code == 422
    assert "below" in response.json()["detail"]
    assert annual(aapl_client, ok, 2024) is None
    assert annual(aapl_client, big, 2024) is None
