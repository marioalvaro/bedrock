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


def _main(client: TestClient) -> int:
    """The id of the company's default scenario "Main"."""
    response = client.get(SCENARIOS)
    assert response.status_code == 200, response.text
    return int(next(s["id"] for s in response.json() if s["name"] == "Main"))


def _export(client: TestClient, scenario_id: int, case: str, fmt: str) -> bytes:
    response = client.get(
        f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers/export", params={"format": fmt}
    )
    assert response.status_code == 200, response.text
    return response.content


def _import(
    client: TestClient, scenario_id: int, case: str, content: bytes, fmt: str, dry_run: bool
) -> Any:
    media = XLSX if fmt == "xlsx" else "text/csv"
    return client.post(
        f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers/import",
        files={"file": (f"drivers.{fmt}", content, media)},
        data={"dry_run": str(dry_run).lower()},
    )


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _grid(client: TestClient, scenario_id: int, case: str) -> dict[str, Any]:
    return _ok(client.get(f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers"))


def _forecast(client: TestClient, scenario_id: int, case: str, type_: str) -> dict[str, Any]:
    body = _ok(
        client.get(
            f"{SCENARIOS}/{scenario_id}/cases/{case}/forecast",
            params={"type": type_, "freq": "annual"},
        )
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
    assert client.get(f"{SCENARIOS}/1/cases/bull/drivers/export").status_code == 401
    response = client.post(
        f"{SCENARIOS}/1/cases/bull/drivers/import", files={"file": ("d.csv", b"x", "text/csv")}
    )
    assert response.status_code == 401


def test_the_upload_runs_in_the_threadpool_not_on_the_event_loop() -> None:
    """Parsing a workbook is blocking work (G36)."""
    assert not inspect.iscoroutinefunction(import_drivers)


def test_export_csv_and_xlsx_with_the_file_name(aapl_client: TestClient) -> None:
    main = _main(aapl_client)
    grid = _grid(aapl_client, main, "bull")

    for fmt, media in (("csv", "text/csv"), ("xlsx", XLSX)):
        response = aapl_client.get(
            f"{SCENARIOS}/{main}/cases/bull/drivers/export", params={"format": fmt}
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(media)
        assert f'filename="AAPL-Main-Bull-drivers.{fmt}"' in response.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(_export(aapl_client, main, "bull", "csv").decode())))
    # the years, then the forecast quarters (checked in the quarter tests below)
    assert rows[0][: 4 + len(grid["forecast_years"])] == [
        "driver_code",
        "label",
        "unit",
        "kind",
    ] + [f"FY{y}" for y in grid["forecast_years"]]
    assert all("Q" in c for c in rows[0][4 + len(grid["forecast_years"]) :])
    assert [r[0] for r in rows[1:]] == [r["code"] for r in grid["rows"]]
    growth = next(r for r in rows if r[0] == "revenue_growth")
    years = len(grid["forecast_years"])
    assert growth[3 : 4 + years] == ["offset"] + ["0.03"] * years
    book = load_workbook(io.BytesIO(_export(aapl_client, main, "bull", "xlsx")))
    assert book.sheetnames == ["Drivers", "Resolved"]


def test_the_file_name_keeps_only_safe_characters(aapl_client: TestClient) -> None:
    created = aapl_client.post(SCENARIOS, json={"name": 'Café "Q"/x'})
    assert created.status_code == 201, created.text

    response = aapl_client.get(f"{SCENARIOS}/{created.json()['id']}/cases/base/drivers/export")

    disposition = response.headers["content-disposition"]
    assert 'filename="AAPL-Caf_ _Q__x-Base-drivers.csv"' in disposition
    assert "filename*=UTF-8''AAPL-Caf%C3%A9%20%22Q%22%2Fx-Base-drivers.csv" in disposition


def test_export_rejects_an_unknown_format(aapl_client: TestClient) -> None:
    main = _main(aapl_client)

    response = aapl_client.get(
        f"{SCENARIOS}/{main}/cases/bull/drivers/export", params={"format": "pdf"}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_an_unchanged_export_imports_as_nothing_to_change(
    aapl_client: TestClient, fmt: str
) -> None:
    main = _main(aapl_client)
    content = _export(aapl_client, main, "bull", fmt)

    assert _ok(_import(aapl_client, main, "bull", content, fmt, dry_run=True)) == {
        "dry_run": True,
        "changes": [],
        "grid": None,
    }
    confirmed = _ok(_import(aapl_client, main, "bull", content, fmt, dry_run=False))
    assert confirmed["changes"] == []
    assert confirmed["grid"] == _grid(aapl_client, main, "bull")


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_one_edited_cell_imports_as_exactly_that_change(aapl_client: TestClient, fmt: str) -> None:
    main = _main(aapl_client)
    before_grid = _grid(aapl_client, main, "bull")
    before_is = _forecast(aapl_client, main, "bull", "IS")
    year = before_grid["forecast_years"][1]
    content = _export(aapl_client, main, "bull", fmt)
    edited = (
        _edit_csv(content, "gross_margin", 5, "0.02")
        if fmt == "csv"
        else _edit_xlsx(content, "gross_margin", 5, 0.02)
    )
    change = {
        "driver_code": "gross_margin",
        "fiscal_year": year,
        "fiscal_period": "FY",
        "old": "0.01",
        "new": "0.02",
        "old_kind": "offset",
        "new_kind": "offset",
    }

    dry = _ok(_import(aapl_client, main, "bull", edited, fmt, dry_run=True))
    assert dry["changes"] == [change]
    assert _grid(aapl_client, main, "bull") == before_grid  # a dry run writes nothing

    confirmed = _ok(_import(aapl_client, main, "bull", edited, fmt, dry_run=False))
    assert (confirmed["dry_run"], confirmed["changes"]) == (False, [change])
    margin = next(r for r in confirmed["grid"]["rows"] if r["code"] == "gross_margin")
    assert margin["own"][1] == "0.02"
    assert confirmed["grid"] == _grid(aapl_client, main, "bull")
    after_is = _forecast(aapl_client, main, "bull", "IS")
    assert after_is != before_is
    assert _ok(_import(aapl_client, main, "bull", edited, fmt, dry_run=True))["changes"] == []


def test_the_default_offsets_fill_the_forecast_years_so_a_round_trip_keeps_them_all(
    aapl_client: TestClient,
) -> None:
    """The horizon is fixed at 5 years: Bull's default offsets are exactly the file's 5 years."""
    main = _main(aapl_client)
    content = _export(aapl_client, main, "bull", "csv")
    assert _ok(_import(aapl_client, main, "bull", content, "csv", dry_run=False))["changes"] == []

    growth = next(
        r for r in _grid(aapl_client, main, "bull")["rows"] if r["code"] == "revenue_growth"
    )
    assert growth["own"] == ["0.03"] * 5


def test_bull_exported_into_a_new_scenario_gives_the_same_forecast(
    aapl_client: TestClient,
) -> None:
    main = _main(aapl_client)
    created = aapl_client.post(SCENARIOS, json={"name": "Copy"})
    assert created.status_code == 201, created.text
    copy = created.json()["id"]
    content = _export(aapl_client, main, "bull", "xlsx")

    _ok(_import(aapl_client, copy, "bull", content, "xlsx", dry_run=False))

    for statement in ("IS", "BS", "CF"):
        assert _forecast(aapl_client, copy, "bull", statement) == _forecast(
            aapl_client, main, "bull", statement
        )


def test_an_invalid_file_is_a_422_listing_each_error(aapl_client: TestClient) -> None:
    main = _main(aapl_client)
    content = _export(aapl_client, main, "bull", "csv")

    response = _import(
        aapl_client, main, "base", _edit_csv(content, "tax_rate", 4, "1e5"), "csv", True
    )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "The file has 3 error(s)"
    messages = [(e["column"], e["message"]) for e in body["errors"]]
    assert ("D", "Base cannot hold offsets") in messages
    assert ("E", "'1e5' is not a number") in messages
    assert all(e["row"] is not None for e in body["errors"])


def test_a_file_over_one_megabyte_is_a_422(aapl_client: TestClient) -> None:
    main = _main(aapl_client)

    response = _import(aapl_client, main, "bull", b"x" * (1024 * 1024 + 1), "csv", True)

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"row": None, "column": None, "message": "The file is larger than 1 MB"}
    ]


def test_another_company_s_scenario_is_a_404(aapl_client: TestClient) -> None:
    main = _main(aapl_client)
    assert aapl_client.post("/api/v1/companies", json={"ticker": "MSFT"}).status_code == 201
    msft = "/api/v1/companies/MSFT/scenarios"
    aapl_client.get(msft)

    assert aapl_client.get(f"{msft}/{main}/cases/bull/drivers/export").status_code == 404
    response = aapl_client.post(
        f"{msft}/{main}/cases/bull/drivers/import", files={"file": ("d.csv", b"x", "text/csv")}
    )
    assert response.status_code == 404


@pytest.mark.parametrize("case", ["base", "bull", "bear"])
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_every_case_exports_and_imports_its_own_file(
    aapl_client: TestClient, case: str, fmt: str
) -> None:
    main = _main(aapl_client)
    content = _export(aapl_client, main, case, fmt)

    dry = _ok(_import(aapl_client, main, case, content, fmt, dry_run=True))
    confirmed = _ok(_import(aapl_client, main, case, content, fmt, dry_run=False))

    assert dry["changes"] == confirmed["changes"] == []
    assert confirmed["grid"]["case"] == case


def test_an_unknown_case_is_422_on_import(aapl_client: TestClient) -> None:
    main = _main(aapl_client)

    response = _import(aapl_client, main, "worst", b"x", "csv", dry_run=True)

    assert response.status_code == 422


# --- quarter columns (docs/erd/forecasting.md "Quarterly drivers" -> Driver files) --------------


def _qgrid(client: TestClient, scenario_id: int, case: str) -> dict[str, Any]:
    return _ok(
        client.get(f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers", params={"freq": "quarterly"})
    )


def _span_years(client: TestClient, scenario_id: int) -> list[int]:
    years = _ok(client.get(f"{SCENARIOS}/{scenario_id}/years"))["years"]
    return [y["fiscal_year"] for y in years if y["in_span"]]


def _switch(client: TestClient, scenario_id: int, year: int, mode: str = "quarterly") -> None:
    response = client.put(f"{SCENARIOS}/{scenario_id}/years/{year}/mode", json={"mode": mode})
    assert response.status_code == 200, response.text


def _put_quarters(
    client: TestClient,
    scenario_id: int,
    case: str,
    code: str,
    kind: str,
    value: str,
    years: list[int],
) -> None:
    """Sets the driver to `value` in every forecast quarter of `years` (each already switched to
    by quarter: a PUT row gives all of a year's quarters)."""
    periods = _qgrid(client, scenario_id, case)["forecast_periods"]
    response = client.put(
        f"{SCENARIOS}/{scenario_id}/cases/{case}/drivers",
        json={
            "rows": [
                {
                    "driver_code": code,
                    "kind": kind,
                    "freq": "quarterly",
                    "values": [
                        {
                            "fiscal_year": p["fiscal_year"],
                            "fiscal_period": p["fiscal_period"],
                            "value": value,
                        }
                        for p in periods
                        if p["fiscal_year"] in years
                    ],
                }
            ]
        },
    )
    _ok(response)


def test_the_export_has_a_column_per_forecast_quarter_holding_the_quarter_values(
    aapl_client: TestClient,
) -> None:
    main = _main(aapl_client)
    first = _span_years(aapl_client, main)[0]
    _switch(aapl_client, main, first)
    _put_quarters(aapl_client, main, "base", "tax_rate", "value", "0.3", [first])
    quarters = _qgrid(aapl_client, main, "base")["forecast_periods"]
    in_first = sum(p["fiscal_year"] == first for p in quarters)

    rows = list(csv.reader(io.StringIO(_export(aapl_client, main, "base", "csv").decode())))

    keys = [f"FY{p['fiscal_year']}{p['fiscal_period']}" for p in quarters]
    assert rows[0][-len(keys) :] == keys
    tax = next(r for r in rows if r[0] == "tax_rate")
    assert tax[3] == "value"
    assert tax[-len(keys) :] == ["0.3"] * in_first + [""] * (len(keys) - in_first)
    assert tax[4] == ""  # the annual cell of a year set by quarter is hidden
    book = load_workbook(io.BytesIO(_export(aapl_client, main, "base", "xlsx")))
    resolved = [r for r in book["Resolved"].iter_rows(values_only=True)]
    assert any(str(c).endswith("Q4E source") for c in resolved[0] if c)


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_a_file_with_quarter_values_imports_unchanged_and_one_edit_is_one_change(
    aapl_client: TestClient, fmt: str
) -> None:
    main = _main(aapl_client)
    years = _span_years(aapl_client, main)[:2]
    for year in years:
        _switch(aapl_client, main, year)
    _put_quarters(aapl_client, main, "bull", "gross_margin", "value", "0.5", years)
    content = _export(aapl_client, main, "bull", fmt)

    unchanged = _ok(_import(aapl_client, main, "bull", content, fmt, dry_run=True))
    assert unchanged["changes"] == []

    quarters = _qgrid(aapl_client, main, "bull")["forecast_periods"]
    column = list(csv.reader(io.StringIO(_export(aapl_client, main, "bull", "csv").decode())))[
        0
    ].index(f"FY{quarters[1]['fiscal_year']}{quarters[1]['fiscal_period']}")
    edited = (
        _edit_csv(content, "gross_margin", column, "0.55")
        if fmt == "csv"
        else _edit_xlsx(content, "gross_margin", column, 0.55)
    )
    preview = _ok(_import(aapl_client, main, "bull", edited, fmt, dry_run=True))
    assert preview["changes"] == [
        {
            "driver_code": "gross_margin",
            "fiscal_year": quarters[1]["fiscal_year"],
            "fiscal_period": quarters[1]["fiscal_period"],
            "old": "0.5",
            "new": "0.55",
            "old_kind": "value",
            "new_kind": "value",
        }
    ]

    applied = _ok(_import(aapl_client, main, "bull", edited, fmt, dry_run=False))
    assert applied["changes"] == preview["changes"]
    row = next(r for r in _qgrid(aapl_client, main, "bull")["rows"] if r["code"] == "gross_margin")
    assert row["own"][:2] == ["0.5", "0.55"]
    again = _ok(_import(aapl_client, main, "bull", edited, fmt, dry_run=True))
    assert again["changes"] == []


def test_a_value_in_a_year_set_the_other_way_is_a_located_error(aapl_client: TestClient) -> None:
    main = _main(aapl_client)
    first, second = _span_years(aapl_client, main)[:2]
    _switch(aapl_client, main, first)
    rows = list(csv.reader(io.StringIO(_export(aapl_client, main, "bull", "csv").decode())))
    header = rows[0]
    annual_of_first = header.index(f"FY{first}")
    quarter_of_second = next(i for i, h in enumerate(header) if h.startswith(f"FY{second}Q"))
    gross = next(r for r in rows if r[0] == "gross_margin")
    gross[annual_of_first] = "0.5"  # FY first is set by quarter
    gross[quarter_of_second] = "0.5"  # FY second is set annually
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)

    response = _import(aapl_client, main, "bull", out.getvalue().encode(), "csv", dry_run=True)

    assert response.status_code == 422
    messages = {e["message"] for e in response.json()["errors"]}
    assert messages == {
        f"FY{first} is set by quarter",
        f"FY{second} is set annually; switch it to by quarter first",
    }


def test_a_quarter_column_outside_the_span_is_a_located_error(aapl_client: TestClient) -> None:
    main = _main(aapl_client)
    content = _export(aapl_client, main, "bull", "csv")
    rows = list(csv.reader(io.StringIO(content.decode())))
    rows[0][-1] = "FY2099Q1"
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)

    response = _import(aapl_client, main, "bull", out.getvalue().encode(), "csv", dry_run=True)

    assert response.status_code == 422
    (error,) = response.json()["errors"]
    assert error["row"] == 1
    assert error["message"].startswith("Column 'FY2099Q1' is not a forecast quarter")
