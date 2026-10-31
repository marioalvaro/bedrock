"""Driver files through the API: export as CSV or xlsx, import with a dry run and confirm
(FR-FCST-05; docs/erd/forecasting.md "Driver files (M4)"), on the recorded AAPL fixtures."""

import csv
import inspect
import io
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from bedrock.api.v1.scenarios import import_drivers

COMPANY = "/api/v1/companies/AAPL"
SCENARIOS = f"{COMPANY}/scenarios"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
D = Decimal


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def _ids(client: TestClient) -> dict[str, int]:
    response = client.get(SCENARIOS)
    assert response.status_code == 200, response.text
    return {s["name"]: s["id"] for s in response.json()}


def _export(client: TestClient, scenario_id: int, fmt: str) -> bytes:
    response = client.get(f"{SCENARIOS}/{scenario_id}/drivers/export", params={"format": fmt})
    assert response.status_code == 200, response.text
    return response.content


def _import(client: TestClient, scenario_id: int, content: bytes, fmt: str, dry_run: bool) -> Any:
    media = XLSX if fmt == "xlsx" else "text/csv"
    return client.post(
        f"{SCENARIOS}/{scenario_id}/drivers/import",
        files={"file": (f"drivers.{fmt}", content, media)},
        data={"dry_run": str(dry_run).lower()},
    )


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _grid(client: TestClient, scenario_id: int) -> dict[str, Any]:
    return _ok(client.get(f"{SCENARIOS}/{scenario_id}/drivers"))


def _forecast(client: TestClient, scenario_id: int, type_: str) -> dict[str, Any]:
    body = _ok(
        client.get(f"{SCENARIOS}/{scenario_id}/forecast", params={"type": type_, "freq": "annual"})
    )
    body.pop("scenario_id")
    return body


def _edit_csv(content: bytes, code: str, column: int, value: str) -> bytes:
    rows = list(csv.reader(io.StringIO(content.decode())))
    next(r for r in rows if r[0] == code)[column] = value
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue().encode()


def _edit_xlsx(content: bytes, code: str, column: int, value: float) -> bytes:
    book = load_workbook(io.BytesIO(content))
    sheet = book["Drivers"]
    number = next(r[0].row for r in sheet.iter_rows() if r[0].value == code)
    sheet.cell(row=number, column=column + 1, value=value)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_driver_file_routes_require_a_session(client: TestClient) -> None:
    assert client.get(f"{SCENARIOS}/1/drivers/export").status_code == 401
    response = client.post(
        f"{SCENARIOS}/1/drivers/import", files={"file": ("d.csv", b"x", "text/csv")}
    )
    assert response.status_code == 401


def test_the_upload_runs_in_the_threadpool_not_on_the_event_loop() -> None:
    """Parsing a workbook is blocking work (G36)."""
    assert not inspect.iscoroutinefunction(import_drivers)


def test_export_csv_and_xlsx_with_the_file_name(aapl_client: TestClient) -> None:
    bull = _ids(aapl_client)["Bull"]
    grid = _grid(aapl_client, bull)

    for fmt, media in (("csv", "text/csv"), ("xlsx", XLSX)):
        response = aapl_client.get(f"{SCENARIOS}/{bull}/drivers/export", params={"format": fmt})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(media)
        assert f'filename="AAPL-Bull-drivers.{fmt}"' in response.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(_export(aapl_client, bull, "csv").decode())))
    assert rows[0] == ["driver_code", "label", "unit", "kind"] + [
        f"FY{y}" for y in grid["forecast_years"]
    ]
    assert [r[0] for r in rows[1:]] == [r["code"] for r in grid["rows"]]
    growth = next(r for r in rows if r[0] == "revenue_growth")
    assert growth[3:] == ["offset"] + ["0.03"] * len(grid["forecast_years"])
    book = load_workbook(io.BytesIO(_export(aapl_client, bull, "xlsx")))
    assert book.sheetnames == ["Drivers", "Resolved"]


def test_the_file_name_keeps_only_safe_characters(aapl_client: TestClient) -> None:
    created = aapl_client.post(SCENARIOS, json={"name": 'Café "Q"/x'})
    assert created.status_code == 201, created.text

    response = aapl_client.get(f"{SCENARIOS}/{created.json()['id']}/drivers/export")

    disposition = response.headers["content-disposition"]
    assert 'filename="AAPL-Caf_ _Q__x-drivers.csv"' in disposition
    assert "filename*=UTF-8''AAPL-Caf%C3%A9%20%22Q%22%2Fx-drivers.csv" in disposition


def test_export_rejects_an_unknown_format(aapl_client: TestClient) -> None:
    bull = _ids(aapl_client)["Bull"]

    response = aapl_client.get(f"{SCENARIOS}/{bull}/drivers/export", params={"format": "pdf"})

    assert response.status_code == 422


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_an_unchanged_export_imports_as_nothing_to_change(
    aapl_client: TestClient, fmt: str
) -> None:
    bull = _ids(aapl_client)["Bull"]
    content = _export(aapl_client, bull, fmt)

    assert _ok(_import(aapl_client, bull, content, fmt, dry_run=True)) == {
        "dry_run": True,
        "changes": [],
        "grid": None,
    }
    confirmed = _ok(_import(aapl_client, bull, content, fmt, dry_run=False))
    assert confirmed["changes"] == []
    assert confirmed["grid"] == _grid(aapl_client, bull)


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_one_edited_cell_imports_as_exactly_that_change(aapl_client: TestClient, fmt: str) -> None:
    bull = _ids(aapl_client)["Bull"]
    before_grid = _grid(aapl_client, bull)
    before_is = _forecast(aapl_client, bull, "IS")
    year = before_grid["forecast_years"][1]
    content = _export(aapl_client, bull, fmt)
    edited = (
        _edit_csv(content, "gross_margin", 5, "0.02")
        if fmt == "csv"
        else _edit_xlsx(content, "gross_margin", 5, 0.02)
    )
    change = {
        "driver_code": "gross_margin",
        "fiscal_year": year,
        "old": "0.01",
        "new": "0.02",
        "old_kind": "offset",
        "new_kind": "offset",
    }

    dry = _ok(_import(aapl_client, bull, edited, fmt, dry_run=True))
    assert dry["changes"] == [change]
    assert _grid(aapl_client, bull) == before_grid  # a dry run writes nothing

    confirmed = _ok(_import(aapl_client, bull, edited, fmt, dry_run=False))
    assert (confirmed["dry_run"], confirmed["changes"]) == (False, [change])
    margin = next(r for r in confirmed["grid"]["rows"] if r["code"] == "gross_margin")
    assert margin["own"][1] == "0.02"
    assert confirmed["grid"] == _grid(aapl_client, bull)
    after_is = _forecast(aapl_client, bull, "IS")
    assert after_is != before_is
    assert _ok(_import(aapl_client, bull, edited, fmt, dry_run=True))["changes"] == []


def test_the_default_offsets_beyond_the_horizon_survive_a_round_trip(
    aapl_client: TestClient,
) -> None:
    """Bull's default offsets cover 10 years; the file shows the 5 of its horizon."""
    bull = _ids(aapl_client)["Bull"]
    content = _export(aapl_client, bull, "csv")
    _ok(_import(aapl_client, bull, content, "csv", dry_run=False))

    longer = aapl_client.put(f"{SCENARIOS}/{bull}", json={"horizon_years": 10})
    assert longer.status_code == 200, longer.text
    growth = next(r for r in _grid(aapl_client, bull)["rows"] if r["code"] == "revenue_growth")
    assert growth["own"] == ["0.03"] * 10


def test_bull_exported_into_a_new_scenario_gives_the_same_forecast(
    aapl_client: TestClient,
) -> None:
    bull = _ids(aapl_client)["Bull"]
    created = aapl_client.post(SCENARIOS, json={"name": "Copy"})
    assert created.status_code == 201, created.text
    copy = created.json()["id"]

    _ok(_import(aapl_client, copy, _export(aapl_client, bull, "xlsx"), "xlsx", dry_run=False))

    for statement in ("IS", "BS", "CF"):
        assert _forecast(aapl_client, copy, statement) == _forecast(aapl_client, bull, statement)


def test_an_invalid_file_is_a_422_listing_each_error(aapl_client: TestClient) -> None:
    base = _ids(aapl_client)["Base"]
    content = _export(aapl_client, _ids(aapl_client)["Bull"], "csv")

    response = _import(aapl_client, base, _edit_csv(content, "tax_rate", 4, "1e5"), "csv", True)

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "The file has 3 error(s)"
    messages = [(e["column"], e["message"]) for e in body["errors"]]
    assert ("D", "Base cannot hold offsets") in messages
    assert ("E", "'1e5' is not a number") in messages
    assert all(e["row"] is not None for e in body["errors"])


def test_a_file_over_one_megabyte_is_a_422(aapl_client: TestClient) -> None:
    bull = _ids(aapl_client)["Bull"]

    response = _import(aapl_client, bull, b"x" * (1024 * 1024 + 1), "csv", True)

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"row": None, "column": None, "message": "The file is larger than 1 MB"}
    ]


def test_another_company_s_scenario_is_a_404(aapl_client: TestClient) -> None:
    bull = _ids(aapl_client)["Bull"]
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    msft = "/api/v1/companies/MSFT/scenarios"
    aapl_client.get(msft)

    assert aapl_client.get(f"{msft}/{bull}/drivers/export").status_code == 404
    response = aapl_client.post(
        f"{msft}/{bull}/drivers/import", files={"file": ("d.csv", b"x", "text/csv")}
    )
    assert response.status_code == 404
