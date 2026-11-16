"""The assumption audit trail through the API (FR-ACC-04; docs/erd/accountability.md "Audit
trail", "API"), on the recorded fixtures with an injected clock."""

import csv
import io
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from bedrock.api.deps import get_clock
from bedrock.models.audit_log import AuditLog
from bedrock.models.company import Company
from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import ScenarioCase
from bedrock.models.valuation_input import ValuationInput
from bedrock.services import audit as audit_service
from bedrock.services.errors import DOMAIN_ERRORS, AuditRowNotFound, InvalidAuditRow

from .valuation_api import case_url, main_id, put_inputs, scenarios_url

API = "/api/v1/companies"
NOW = datetime(2026, 11, 10, 12, 30, tzinfo=UTC)
STAMP = datetime(2026, 11, 10, 12, 30)
STAMP_TEXT = "2026-11-10T12:30:00"


def audit_url(ticker: str = "AAPL") -> str:
    return f"{API}/{ticker}/audit"


def company_id(app: FastAPI, ticker: str) -> int:
    with app.state.session_factory() as session:
        return int(session.execute(select(Company.id).where(Company.ticker == ticker)).scalar_one())


def seed_rows(app: FastAPI, ticker: str, count: int, entity: str = "driver") -> None:
    """`count` audit rows on fields f00, f01, ..., through the service every writer uses."""
    with app.state.session_factory() as session:
        audit_service.record(
            session,
            company_id(app, ticker),
            entity,
            7,
            "Main · Base",
            "edit",
            {},
            {f"f{i:02d}": str(i) for i in range(count)},
            lambda field: (f"Label {field}", "pct"),
            STAMP,
        )
        session.commit()


def stored_row(app: FastAPI, row_id: int) -> dict[str, Any]:
    with app.state.session_factory() as session:
        row = session.get_one(AuditLog, row_id)
        return {c.name: getattr(row, c.name) for c in AuditLog.__table__.columns}


def page(client: TestClient, ticker: str = "AAPL", **params: Any) -> dict[str, Any]:
    response = client.get(audit_url(ticker), params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def clock(app: FastAPI) -> Generator[None, None, None]:
    app.dependency_overrides[get_clock] = lambda: NOW
    yield
    app.dependency_overrides.pop(get_clock)


@pytest.fixture
def aapl(seed_db: Callable[..., None], authed_client: TestClient, clock: None) -> TestClient:
    seed_db("AAPL")
    return authed_client


@pytest.fixture
def two(seed_db: Callable[..., None], authed_client: TestClient, clock: None) -> TestClient:
    seed_db("AAPL", "MSFT")
    return authed_client


# --- `record`


def test_record_adds_one_row_per_changed_field_in_field_order(
    app: FastAPI, aapl: TestClient
) -> None:
    with app.state.session_factory() as session:
        count = audit_service.record(
            session,
            company_id(app, "AAPL"),
            "driver",
            7,
            "Main · Bull",
            "edit",
            {"b": "1", "same": "x", "gone": "2"},
            {"b": "3", "same": "x", "a": "4"},
            lambda field: (f"Label {field}", "pct"),
            STAMP,
            rationale="why",
        )
        session.commit()

    assert count == 3
    rows = page(aapl)["rows"]
    assert [(r["field"], r["old_value"], r["new_value"]) for r in reversed(rows)] == [
        ("a", None, "4"),
        ("b", "1", "3"),
        ("gone", "2", None),
    ]
    assert rows[0]["entity"] == "driver"
    assert rows[0]["scope"] == "Main · Bull"
    assert rows[0]["label"] == "Label gone"
    assert rows[0]["unit"] == "pct"
    assert rows[0]["action"] == "edit"
    assert rows[0]["rationale"] == "why"
    assert rows[0]["changed_at"] == STAMP_TEXT


def test_record_does_not_commit(app: FastAPI, aapl: TestClient) -> None:
    with app.state.session_factory() as session:
        audit_service.record(
            session,
            company_id(app, "AAPL"),
            "driver",
            7,
            None,
            "edit",
            {},
            {"a": "1"},
            lambda field: (field, None),
            STAMP,
        )
        session.rollback()

    assert page(aapl)["rows"] == []


def test_record_writes_nothing_when_nothing_changed(app: FastAPI, aapl: TestClient) -> None:
    with app.state.session_factory() as session:
        count = audit_service.record(
            session,
            company_id(app, "AAPL"),
            "driver",
            7,
            None,
            "edit",
            {"a": "1"},
            {"a": "1"},
            lambda field: (field, None),
            STAMP,
        )
        session.commit()

    assert count == 0
    assert page(aapl)["rows"] == []


# --- GET


def test_the_routes_require_a_session(aapl: TestClient) -> None:
    aapl.cookies.clear()

    assert aapl.get(audit_url()).status_code == 401
    assert aapl.patch(f"{audit_url()}/1", json={"rationale": "x"}).status_code == 401


def test_a_company_with_no_changes_has_an_empty_page(aapl: TestClient) -> None:
    assert page(aapl) == {"rows": [], "next_before_id": None}


def test_rows_page_newest_first(app: FastAPI, aapl: TestClient) -> None:
    seed_rows(app, "AAPL", 5)

    first = page(aapl, limit=2)
    second = page(aapl, limit=2, before_id=first["next_before_id"])
    third = page(aapl, limit=2, before_id=second["next_before_id"])

    assert [r["field"] for r in first["rows"]] == ["f04", "f03"]
    assert first["next_before_id"] == first["rows"][-1]["id"]
    assert [r["field"] for r in second["rows"]] == ["f02", "f01"]
    assert [r["field"] for r in third["rows"]] == ["f00"]
    assert third["next_before_id"] is None


def test_a_full_last_page_has_no_next_page(app: FastAPI, aapl: TestClient) -> None:
    seed_rows(app, "AAPL", 2)

    assert page(aapl, limit=2)["next_before_id"] is None


def test_the_entity_filter_keeps_only_that_entity(app: FastAPI, aapl: TestClient) -> None:
    seed_rows(app, "AAPL", 2, entity="driver")
    seed_rows(app, "AAPL", 3, entity="scenario")

    rows = page(aapl, entity="driver")["rows"]

    assert [r["entity"] for r in rows] == ["driver", "driver"]


def test_paging_respects_the_entity_filter(app: FastAPI, aapl: TestClient) -> None:
    seed_rows(app, "AAPL", 2, entity="driver")
    seed_rows(app, "AAPL", 1, entity="scenario")

    first = page(aapl, entity="driver", limit=1)
    second = page(aapl, entity="driver", limit=1, before_id=first["next_before_id"])

    assert [r["field"] for r in first["rows"]] == ["f01"]
    assert [r["field"] for r in second["rows"]] == ["f00"]
    assert second["next_before_id"] is None


def test_an_unknown_entity_is_refused(aapl: TestClient) -> None:
    assert aapl.get(audit_url(), params={"entity": "nope"}).status_code == 422


@pytest.mark.parametrize(("limit", "status"), [(0, 422), (1, 200), (500, 200), (501, 422)])
def test_limit_bounds(aapl: TestClient, limit: int, status: int) -> None:
    assert aapl.get(audit_url(), params={"limit": limit}).status_code == status


def test_the_default_limit_is_100(app: FastAPI, aapl: TestClient) -> None:
    seed_rows(app, "AAPL", 101)

    body = page(aapl)

    assert len(body["rows"]) == 100
    assert body["next_before_id"] == body["rows"][-1]["id"]


def test_another_companys_rows_are_not_listed(app: FastAPI, two: TestClient) -> None:
    seed_rows(app, "MSFT", 2)

    assert page(two)["rows"] == []
    assert len(page(two, "MSFT")["rows"]) == 2


def test_an_unfollowed_ticker_is_not_found(aapl: TestClient) -> None:
    assert aapl.get(audit_url("ZZZZ")).status_code == 404


# --- PATCH


def only_row(client: TestClient, ticker: str = "AAPL") -> dict[str, Any]:
    rows = page(client, ticker)["rows"]
    assert len(rows) == 1
    row: dict[str, Any] = rows[0]
    return row


def test_patch_sets_the_rationale_and_nothing_else(app: FastAPI, aapl: TestClient) -> None:
    seed_rows(app, "AAPL", 1)
    row = only_row(aapl)
    before = stored_row(app, row["id"])

    response = aapl.patch(f"{audit_url()}/{row['id']}", json={"rationale": "  a margin reset  "})

    assert response.status_code == 200, response.text
    assert response.json() == {**row, "rationale": "a margin reset"}
    assert only_row(aapl) == {**row, "rationale": "a margin reset"}
    assert stored_row(app, row["id"]) == {**before, "rationale": "a margin reset"}


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_rationale_clears_it(app: FastAPI, aapl: TestClient, blank: str | None) -> None:
    seed_rows(app, "AAPL", 1)
    row_id = only_row(aapl)["id"]
    aapl.patch(f"{audit_url()}/{row_id}", json={"rationale": "a reason"})

    response = aapl.patch(f"{audit_url()}/{row_id}", json={"rationale": blank})

    assert response.status_code == 200, response.text
    assert response.json()["rationale"] is None
    assert only_row(aapl)["rationale"] is None


@pytest.mark.parametrize(("length", "status"), [(500, 200), (501, 422)])
def test_rationale_length_bound(app: FastAPI, aapl: TestClient, length: int, status: int) -> None:
    seed_rows(app, "AAPL", 1)
    row_id = only_row(aapl)["id"]

    response = aapl.patch(f"{audit_url()}/{row_id}", json={"rationale": "x" * length})

    assert response.status_code == status, response.text
    assert only_row(aapl)["rationale"] == ("x" * length if status == 200 else None)


def test_the_length_bound_applies_after_trimming(app: FastAPI, aapl: TestClient) -> None:
    seed_rows(app, "AAPL", 1)
    row_id = only_row(aapl)["id"]

    response = aapl.patch(f"{audit_url()}/{row_id}", json={"rationale": f"  {'x' * 500}  "})

    assert response.status_code == 200, response.text


def test_patch_on_an_unknown_row_is_not_found(aapl: TestClient) -> None:
    response = aapl.patch(f"{audit_url()}/999999", json={"rationale": "x"})

    assert response.status_code == 404
    assert response.json()["detail"] == "No such audit row: 999999"


def test_patch_on_another_companys_row_is_not_found(app: FastAPI, two: TestClient) -> None:
    seed_rows(app, "MSFT", 1)
    row = only_row(two, "MSFT")

    response = two.patch(f"{audit_url('AAPL')}/{row['id']}", json={"rationale": "x"})

    assert response.status_code == 404
    assert only_row(two, "MSFT")["rationale"] is None


# --- what the writers log: drivers


def case_id(app: FastAPI, scenario_id: int, case: str) -> int:
    with app.state.session_factory() as session:
        return int(
            session.execute(
                select(ScenarioCase.id).where(
                    ScenarioCase.scenario_id == scenario_id, ScenarioCase.case == case
                )
            ).scalar_one()
        )


def forecast_years(client: TestClient, scenario_id: int) -> list[int]:
    grid = client.get(case_url("AAPL", scenario_id, "base", "drivers"))
    assert grid.status_code == 200, grid.text
    return [int(y) for y in grid.json()["forecast_years"]]


def put_driver(
    client: TestClient,
    scenario_id: int,
    case: str,
    code: str,
    kind: str,
    cells: list[tuple[int, str, str | None]],
) -> Any:
    """`cells` are (fiscal year, period, value); the row's frequency follows the first period."""
    freq = "annual" if not cells or cells[0][1] == "FY" else "quarterly"
    values = [{"fiscal_year": y, "fiscal_period": p, "value": v} for y, p, v in cells]
    row = {"driver_code": code, "kind": kind, "freq": freq, "values": values}
    return client.put(case_url("AAPL", scenario_id, case, "drivers"), json={"rows": [row]})


def put_ok(*args: Any) -> None:
    response = put_driver(*args)
    assert response.status_code == 200, response.text


def logged(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    """The rows oldest first, without the database id."""
    rows = page(client, limit=500, **params)["rows"]
    return [{k: v for k, v in r.items() if k != "id"} for r in reversed(rows)]


def row_of(
    entity: str,
    scope: str | None,
    field: str,
    label: str,
    unit: str | None,
    old: str | None,
    new: str | None,
    action: str,
    rationale: str | None = None,
) -> dict[str, Any]:
    return {
        "entity": entity,
        "scope": scope,
        "field": field,
        "label": label,
        "unit": unit,
        "old_value": old,
        "new_value": new,
        "action": action,
        "rationale": rationale,
        "changed_at": STAMP_TEXT,
    }


def driver_row(
    case: str, field: str, label: str, old: str | None, new: str | None, action: str = "edit"
) -> dict[str, Any]:
    return row_of("driver", f"Main · {case}", field, label, "pct", old, new, action)


def yy(year: int) -> str:
    return f"{year % 100:02d}"


def test_a_driver_edit_logs_the_field_with_old_and_new(app: FastAPI, aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]

    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.45")])
    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.46")])

    field, label = f"gross_margin|{y}|FY", f"Gross margin FY{yy(y)}"
    assert logged(aapl) == [
        driver_row("Base", field, label, None, "0.45"),
        driver_row("Base", field, label, "0.45", "0.46"),
    ]
    first_id = page(aapl)["rows"][-1]["id"]
    assert stored_row(app, first_id)["entity_id"] == case_id(app, main, "base")


def test_a_driver_save_that_changes_nothing_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]
    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.45")])

    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.4500")])

    assert len(logged(aapl)) == 1


def test_a_driver_value_is_logged_as_it_was_stored(aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]

    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.123456789012")])
    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.123456789012")])

    rows = logged(aapl)
    assert [r["new_value"] for r in rows] == ["0.123456789"]


@pytest.mark.parametrize(
    ("code", "value", "status"), [("gross_margin", "5", 422), ("magic", "0.1", 422)]
)
def test_a_refused_driver_write_logs_nothing(
    aapl: TestClient, code: str, value: str, status: int
) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]

    response = put_driver(aapl, main, "base", code, "value", [(y, "FY", value)])

    assert response.status_code == status, response.text
    assert logged(aapl) == []


def test_a_cleared_driver_is_logged_with_no_new_value(aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]
    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.45")])

    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", None)])

    assert logged(aapl)[-1] == driver_row(
        "Base", f"gross_margin|{y}|FY", f"Gross margin FY{yy(y)}", "0.45", None
    )


def test_an_offset_changed_to_a_value_is_logged(aapl: TestClient) -> None:
    main = main_id(aapl)
    years = forecast_years(aapl, main)

    put_ok(aapl, main, "bull", "revenue_growth", "value", [(y, "FY", "0.2") for y in years])

    assert logged(aapl) == [
        driver_row(
            "Bull",
            f"revenue_growth|{y}|FY",
            f"Revenue growth FY{yy(y)}",
            "offset:0.03",
            "0.2",
        )
        for y in years
    ]


def test_a_kind_clash_logs_the_rows_it_drops(aapl: TestClient) -> None:
    main = main_id(aapl)
    years = forecast_years(aapl, main)
    y = years[1]  # the first year may be in progress; the second is whole
    url = f"{scenarios_url('AAPL')}/{main}/years/{y}/mode"
    assert aapl.put(url, json={"mode": "quarterly"}).status_code == 200
    before = len(logged(aapl))

    quarters = [(y, q, "0.02") for q in ("Q1", "Q2", "Q3", "Q4")]
    put_ok(aapl, main, "bull", "revenue_growth", "value", quarters)

    rows = {r["field"]: r for r in logged(aapl)[before:]}
    for year in years:
        field = f"revenue_growth|{year}|FY"
        assert rows[field] == driver_row(
            "Bull", field, f"Revenue growth FY{yy(year)}", "offset:0.03", None
        )
    second = rows[f"revenue_growth|{y}|Q2"]
    assert second["label"] == f"Revenue growth Q2 FY{yy(y)}"
    assert second["new_value"] == "0.02"
    assert second["action"] == "edit"


def test_a_segment_driver_is_labelled_with_its_segment(app: FastAPI, aapl: TestClient) -> None:
    main = main_id(aapl)
    series = aapl.post(
        f"{API}/AAPL/segment-series",
        json={"dimension": "business", "name": "iPhone", "metric": "revenue", "unit": "USD"},
    )
    assert series.status_code == 201, series.text
    updated = aapl.put(
        f"{scenarios_url('AAPL')}/{main}",
        json={"revenue_method": "segments", "segment_dimension": "business"},
    )
    assert updated.status_code == 200, updated.text
    grid = aapl.get(case_url("AAPL", main, "base", "drivers")).json()
    segment = next(r for r in grid["rows"] if r["code"].startswith("segment_growth:"))
    y = grid["forecast_years"][0]
    before = len(logged(aapl))

    put_ok(aapl, main, "base", segment["code"], "value", [(y, "FY", "0.1")])

    assert logged(aapl)[before:] == [
        driver_row(
            "Base", f"{segment['code']}|{y}|FY", f"{segment['label']} FY{yy(y)}", None, "0.1"
        )
    ]


def csv_with(content: bytes, code: str, column: str, value: str) -> bytes:
    table = list(csv.reader(io.StringIO(content.decode())))
    at = table[0].index(column)
    next(r for r in table if r[0] == code)[at] = value
    buffer = io.StringIO()
    csv.writer(buffer).writerows(table)
    return buffer.getvalue().encode()


def driver_file(client: TestClient, scenario_id: int, case: str) -> bytes:
    response = client.get(
        f"{scenarios_url('AAPL')}/{scenario_id}/cases/{case}/drivers/export",
        params={"format": "csv"},
    )
    assert response.status_code == 200, response.text
    return response.content


def import_file(
    client: TestClient, scenario_id: int, case: str, content: bytes, dry_run: bool
) -> None:
    response = client.post(
        f"{scenarios_url('AAPL')}/{scenario_id}/cases/{case}/drivers/import",
        files={"file": ("drivers.csv", content, "text/csv")},
        data={"dry_run": str(dry_run).lower()},
    )
    assert response.status_code == 200, response.text


def test_a_driver_file_import_is_logged(aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]
    edited = csv_with(driver_file(aapl, main, "bull"), "revenue_growth", f"FY{y}", "0.05")

    import_file(aapl, main, "bull", edited, dry_run=False)

    assert logged(aapl) == [
        driver_row(
            "Bull",
            f"revenue_growth|{y}|FY",
            f"Revenue growth FY{yy(y)}",
            "offset:0.03",
            "offset:0.05",
            "import",
        )
    ]


def test_a_dry_run_import_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]
    edited = csv_with(driver_file(aapl, main, "bull"), "revenue_growth", f"FY{y}", "0.05")

    import_file(aapl, main, "bull", edited, dry_run=True)

    assert logged(aapl) == []


def test_an_import_that_changes_nothing_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    import_file(aapl, main, "bull", driver_file(aapl, main, "bull"), dry_run=False)

    assert logged(aapl) == []


def test_a_case_reset_logs_the_whole_case_diff(aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]
    put_ok(aapl, main, "base", "gross_margin", "value", [(y, "FY", "0.45")])
    before = len(logged(aapl))

    response = aapl.post(case_url("AAPL", main, "base", "reset"))

    assert response.status_code == 200, response.text
    assert logged(aapl)[before:] == [
        driver_row("Base", f"gross_margin|{y}|FY", f"Gross margin FY{yy(y)}", "0.45", None, "reset")
    ]


def test_a_reset_of_a_case_at_its_defaults_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    response = aapl.post(case_url("AAPL", main, "bull", "reset"))

    assert response.status_code == 200, response.text
    assert logged(aapl) == []


def test_a_retired_driver_code_still_logs_under_its_code(app: FastAPI, aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[0]
    with app.state.session_factory() as session:
        session.add(
            DriverValue(
                case_id=case_id(app, main, "base"),
                driver_code="retired_driver",
                fiscal_year=y,
                fiscal_period="FY",
                kind="value",
                value=Decimal("0.5"),
                source="manual",
                created_at=STAMP,
                updated_at=STAMP,
            )
        )
        session.commit()

    response = aapl.post(case_url("AAPL", main, "base", "reset"))

    assert response.status_code == 200, response.text
    assert logged(aapl) == [
        row_of(
            "driver",
            "Main · Base",
            f"retired_driver|{y}|FY",
            f"retired_driver FY{yy(y)}",
            None,
            "0.5",
            None,
            "reset",
        )
    ]


# --- year modes


def set_mode(client: TestClient, scenario_id: int, year: int, mode: str) -> Any:
    return client.put(
        f"{scenarios_url('AAPL')}/{scenario_id}/years/{year}/mode", json={"mode": mode}
    )


def test_a_year_mode_change_logs_one_row_not_the_quarters_it_fills(
    app: FastAPI, aapl: TestClient
) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[1]

    assert set_mode(aapl, main, y, "quarterly").status_code == 200
    assert set_mode(aapl, main, y, "annual").status_code == 200

    field, label = f"FY{y}", f"FY{yy(y)} set by"
    assert logged(aapl) == [
        row_of("year_mode", "Main", field, label, None, "annual", "quarterly", "mode"),
        row_of("year_mode", "Main", field, label, None, "quarterly", "annual", "mode"),
    ]
    assert stored_row(app, page(aapl)["rows"][0]["id"])["entity_id"] == main


def test_a_year_already_in_that_mode_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)
    y = forecast_years(aapl, main)[1]

    assert set_mode(aapl, main, y, "annual").status_code == 200

    assert logged(aapl) == []


def test_a_refused_year_mode_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    assert set_mode(aapl, main, 1990, "quarterly").status_code == 422

    assert logged(aapl) == []


# --- engine choices


def put_engines(client: TestClient, scenario_id: int, **engines: str) -> Any:
    rows = [{"driver_code": c, "engine": e} for c, e in engines.items()]
    return client.put(f"{scenarios_url('AAPL')}/{scenario_id}/engines", json={"rows": rows})


def engine_row(old: str, new: str) -> dict[str, Any]:
    return row_of(
        "engine_choice",
        "Main",
        "revenue_growth",
        "Revenue growth engine",
        None,
        old,
        new,
        "edit",
    )


def test_an_engine_choice_is_logged_with_auto_for_a_missing_row(
    app: FastAPI, aapl: TestClient
) -> None:
    main = main_id(aapl)

    assert put_engines(aapl, main, revenue_growth="ets").status_code == 200
    assert put_engines(aapl, main, revenue_growth="auto").status_code == 200

    assert logged(aapl) == [engine_row("auto", "ets"), engine_row("ets", "auto")]
    assert stored_row(app, page(aapl)["rows"][0]["id"])["entity_id"] == main


def test_an_unchanged_engine_choice_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    assert put_engines(aapl, main, revenue_growth="auto").status_code == 200

    assert logged(aapl) == []


def test_a_refused_engine_choice_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    assert put_engines(aapl, main, magic="ets").status_code == 422

    assert logged(aapl) == []


# --- valuation inputs


def input_row(old: str | None, new: str | None, action: str = "edit") -> dict[str, Any]:
    return row_of(
        "valuation_input",
        "Main · Bull",
        "discount_rate",
        "Discount rate",
        "pct",
        old,
        new,
        action,
    )


def ok_inputs(client: TestClient, scenario_id: int, **values: str | None) -> None:
    response = put_inputs(client, scenario_id, "bull", **values)
    assert response.status_code == 200, response.text


def test_a_valuation_input_is_logged(app: FastAPI, aapl: TestClient) -> None:
    main = main_id(aapl)

    ok_inputs(aapl, main, discount_rate="0.1")
    ok_inputs(aapl, main, discount_rate="0.11")
    ok_inputs(aapl, main, discount_rate=None)

    assert logged(aapl) == [
        input_row(None, "0.1"),
        input_row("0.1", "0.11"),
        input_row("0.11", None),
    ]
    first_id = page(aapl)["rows"][-1]["id"]
    assert stored_row(app, first_id)["entity_id"] == case_id(app, main, "bull")


def test_an_unchanged_valuation_input_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)
    ok_inputs(aapl, main, discount_rate="0.1")

    ok_inputs(aapl, main, discount_rate="0.1")

    assert len(logged(aapl)) == 1


def test_a_refused_valuation_input_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    assert put_inputs(aapl, main, "bull", discount_rate="9").status_code == 422

    assert logged(aapl) == []


def test_a_valuation_reset_logs_each_input_it_clears(aapl: TestClient) -> None:
    main = main_id(aapl)
    ok_inputs(aapl, main, discount_rate="0.1")
    before = len(logged(aapl))

    response = aapl.post(case_url("AAPL", main, "bull", "valuation-inputs/reset"))

    assert response.status_code == 200, response.text
    assert logged(aapl)[before:] == [input_row("0.1", None, "reset")]


def test_a_valuation_reset_with_nothing_stored_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    response = aapl.post(case_url("AAPL", main, "bull", "valuation-inputs/reset"))

    assert response.status_code == 200, response.text
    assert logged(aapl) == []


def test_a_retired_valuation_input_still_logs_under_its_code(
    app: FastAPI, aapl: TestClient
) -> None:
    main = main_id(aapl)
    with app.state.session_factory() as session:
        session.add(
            ValuationInput(
                case_id=case_id(app, main, "bull"), code="retired", value="1", updated_at=STAMP
            )
        )
        session.commit()

    response = aapl.post(case_url("AAPL", main, "bull", "valuation-inputs/reset"))

    assert response.status_code == 200, response.text
    assert logged(aapl) == [
        row_of("valuation_input", "Main · Bull", "retired", "retired", None, "1", None, "reset")
    ]


# --- scenarios


def create_side(client: TestClient, name: str = "Side") -> int:
    response = client.post(scenarios_url("AAPL"), json={"name": name})
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def scenario_row(
    scope: str, field: str, label: str, old: str | None, new: str | None, action: str
) -> dict[str, Any]:
    return row_of("scenario", scope, field, label, None, old, new, action)


def test_the_automatic_default_scenario_logs_nothing(aapl: TestClient) -> None:
    main_id(aapl)

    assert logged(aapl) == []


def test_a_new_scenario_logs_its_settings_and_not_its_default_offsets(
    app: FastAPI, aapl: TestClient
) -> None:
    side = create_side(aapl)

    assert logged(aapl) == [
        scenario_row("Side", "name", "Name", None, "Side", "create"),
        scenario_row("Side", "revenue_method", "Revenue method", None, "growth", "create"),
    ]
    assert stored_row(app, page(aapl)["rows"][0]["id"])["entity_id"] == side


def test_a_scenario_edit_logs_what_changed_under_its_new_name(aapl: TestClient) -> None:
    side = create_side(aapl)
    before = len(logged(aapl))

    response = aapl.put(f"{scenarios_url('AAPL')}/{side}", json={"name": "Alt"})

    assert response.status_code == 200, response.text
    assert logged(aapl)[before:] == [scenario_row("Alt", "name", "Name", "Side", "Alt", "edit")]


def test_a_method_switch_logs_the_settings_and_not_the_automatic_offsets(aapl: TestClient) -> None:
    side = create_side(aapl)
    series = aapl.post(
        f"{API}/AAPL/segment-series",
        json={"dimension": "business", "name": "iPhone", "metric": "revenue", "unit": "USD"},
    )
    assert series.status_code == 201, series.text
    before = len(logged(aapl))

    response = aapl.put(
        f"{scenarios_url('AAPL')}/{side}",
        json={"revenue_method": "segments", "segment_dimension": "business"},
    )

    assert response.status_code == 200, response.text
    assert logged(aapl)[before:] == [
        scenario_row("Side", "revenue_method", "Revenue method", "growth", "segments", "edit"),
        scenario_row("Side", "segment_dimension", "Segment dimension", None, "business", "edit"),
    ]


def test_an_unchanged_scenario_save_logs_nothing(aapl: TestClient) -> None:
    side = create_side(aapl)
    before = len(logged(aapl))

    response = aapl.put(f"{scenarios_url('AAPL')}/{side}", json={"name": "Side"})

    assert response.status_code == 200, response.text
    assert len(logged(aapl)) == before


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"name": "Main"}, 409),
        ({"name": "   "}, 422),
        ({"revenue_method": "segments"}, 422),
    ],
)
def test_a_refused_scenario_edit_logs_nothing(
    aapl: TestClient, body: dict[str, str], status: int
) -> None:
    main_id(aapl)
    side = create_side(aapl)
    before = len(logged(aapl))

    response = aapl.put(f"{scenarios_url('AAPL')}/{side}", json=body)

    assert response.status_code == status, response.text
    assert len(logged(aapl)) == before


def test_a_refused_scenario_create_logs_nothing(aapl: TestClient) -> None:
    main_id(aapl)

    assert aapl.post(scenarios_url("AAPL"), json={"name": "Main"}).status_code == 409

    assert logged(aapl) == []


def test_a_deleted_scenarios_rows_remain_with_their_labels(aapl: TestClient) -> None:
    side = create_side(aapl)
    y = forecast_years(aapl, side)[0]
    put_ok(aapl, side, "base", "gross_margin", "value", [(y, "FY", "0.45")])
    before = logged(aapl)

    response = aapl.delete(f"{scenarios_url('AAPL')}/{side}")

    assert response.status_code == 204, response.text
    rows = logged(aapl)
    assert rows[: len(before)] == before
    assert rows[len(before) - 1]["scope"] == "Side · Base"
    assert rows[len(before) - 1]["label"] == f"Gross margin FY{yy(y)}"
    assert rows[len(before) :] == [
        scenario_row("Side", "name", "Name", "Side", None, "delete"),
        scenario_row("Side", "revenue_method", "Revenue method", "growth", None, "delete"),
    ]


def test_refusing_to_delete_the_default_scenario_logs_nothing(aapl: TestClient) -> None:
    main = main_id(aapl)

    assert aapl.delete(f"{scenarios_url('AAPL')}/{main}").status_code == 409

    assert logged(aapl) == []


# --- adjustments

ADJUSTMENTS = f"{API}/AAPL/adjustments"
SGA_FY2024 = {
    "canonical_code": "sga",
    "fiscal_year": 2024,
    "fiscal_period": "FY",
    "amount": "-1000000000",
    "category": "one-off",
    "reason": "  lawsuit  ",
}


def adjust(client: TestClient, **changes: Any) -> int:
    response = client.post(ADJUSTMENTS, json={**SGA_FY2024, **changes})
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def amend(client: TestClient, adjustment_id: int, **changes: Any) -> None:
    response = client.put(f"{ADJUSTMENTS}/{adjustment_id}", json={**SGA_FY2024, **changes})
    assert response.status_code == 200, response.text


def adjustment_row(
    field: str,
    old: str | None,
    new: str | None,
    action: str,
    rationale: str,
    period: str = "FY24",
) -> dict[str, Any]:
    unit = "USD" if field == "amount" else None
    label = f"Selling, general & administrative {period} {field}"
    return row_of("adjustment", None, field, label, unit, old, new, action, rationale)


def test_a_new_adjustment_logs_its_fields_with_the_reason_as_rationale(
    app: FastAPI, aapl: TestClient
) -> None:
    adjustment_id = adjust(aapl)

    assert logged(aapl) == [
        adjustment_row("amount", None, "-1000000000", "create", "lawsuit"),
        adjustment_row("category", None, "one-off", "create", "lawsuit"),
        adjustment_row("reason", None, "lawsuit", "create", "lawsuit"),
    ]
    assert stored_row(app, page(aapl)["rows"][0]["id"])["entity_id"] == adjustment_id


def test_a_quarter_adjustment_is_labelled_with_its_quarter(aapl: TestClient) -> None:
    adjust(aapl, fiscal_period="Q2")

    assert logged(aapl)[0]["label"] == "Selling, general & administrative Q2 FY24 amount"


def test_an_adjustment_amount_is_logged_without_padding(aapl: TestClient) -> None:
    adjust(aapl, amount="1234.50")

    assert logged(aapl)[0]["new_value"] == "1234.5"


def test_an_adjustment_edit_logs_only_what_changed(aapl: TestClient) -> None:
    adjustment_id = adjust(aapl)
    before = len(logged(aapl))

    amend(aapl, adjustment_id, amount="-2000000000", reason="settled")

    assert logged(aapl)[before:] == [
        adjustment_row("amount", "-1000000000", "-2000000000", "edit", "settled"),
        adjustment_row("reason", "lawsuit", "settled", "edit", "settled"),
    ]


def test_an_unchanged_adjustment_save_logs_nothing(aapl: TestClient) -> None:
    adjustment_id = adjust(aapl)
    before = len(logged(aapl))

    amend(aapl, adjustment_id)

    assert len(logged(aapl)) == before


def test_moving_an_adjustment_to_another_period_is_logged(aapl: TestClient) -> None:
    adjustment_id = adjust(aapl)
    before = len(logged(aapl))

    amend(aapl, adjustment_id, fiscal_year=2023)

    assert logged(aapl)[before:] == [
        adjustment_row("period", "FY24", "FY23", "edit", "lawsuit", period="FY23")
    ]


def test_moving_an_adjustment_to_another_line_is_logged(aapl: TestClient) -> None:
    adjustment_id = adjust(aapl)
    before = len(logged(aapl))

    amend(aapl, adjustment_id, canonical_code="cost_of_revenue")

    [row] = logged(aapl)[before:]
    assert (row["field"], row["old_value"], row["new_value"]) == (
        "line",
        "sga",
        "cost_of_revenue",
    )


def test_a_deleted_adjustment_logs_what_it_held(aapl: TestClient) -> None:
    adjustment_id = adjust(aapl)
    before = len(logged(aapl))

    assert aapl.delete(f"{ADJUSTMENTS}/{adjustment_id}").status_code == 204

    assert logged(aapl)[before:] == [
        adjustment_row("amount", "-1000000000", None, "delete", "lawsuit"),
        adjustment_row("category", "one-off", None, "delete", "lawsuit"),
        adjustment_row("reason", "lawsuit", None, "delete", "lawsuit"),
    ]


def test_a_refused_adjustment_logs_nothing(aapl: TestClient) -> None:
    response = aapl.post(ADJUSTMENTS, json={**SGA_FY2024, "reason": "   "})

    assert response.status_code == 422, response.text
    assert logged(aapl) == []


def test_a_refused_adjustment_edit_logs_nothing(aapl: TestClient) -> None:
    adjustment_id = adjust(aapl)
    before = len(logged(aapl))

    response = aapl.put(f"{ADJUSTMENTS}/{adjustment_id}", json={**SGA_FY2024, "reason": ""})

    assert response.status_code == 422, response.text
    assert len(logged(aapl)) == before


def test_deleting_an_unknown_adjustment_logs_nothing(aapl: TestClient) -> None:
    assert aapl.delete(f"{ADJUSTMENTS}/999999").status_code == 404

    assert logged(aapl) == []


def test_a_refused_rationale_is_a_domain_error_with_a_plain_message() -> None:
    """The CLI prints a `DOMAIN_ERRORS` member as a message rather than a traceback."""
    assert issubclass(InvalidAuditRow, DOMAIN_ERRORS)
    assert issubclass(AuditRowNotFound, DOMAIN_ERRORS)
