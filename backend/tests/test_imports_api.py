"""The statement import routes over a followed AAPL (recorded fixtures, no network)."""

import inspect
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from bedrock.api.v1.imports import import_statements

from .import_data import add_line, filled, mark_complete, save

BASE = "/api/v1/companies/AAPL"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def aapl_client(authed_client: TestClient) -> TestClient:
    assert authed_client.post("/api/v1/companies", json={"ticker": "AAPL"}).status_code == 201
    return authed_client


def _template(client: TestClient, **params: str) -> bytes:
    response = client.get(f"{BASE}/import-template", params=params)
    assert response.status_code == 200, response.text
    return response.content


def _typed(client: TestClient, cells: list[tuple[str, str, str, object]]) -> bytes:
    book = load_workbook(io.BytesIO(_template(client, format="xlsx", prefill="true")))
    for sheet, code, period, value in cells:
        filled(book, sheet, code, period, value)  # type: ignore[arg-type]
    return save(book)


def _upload(
    client: TestClient, content: bytes, dry_run: bool, name: str = "aapl.xlsx", **extra: str
):  # type: ignore[no-untyped-def]
    return client.post(
        f"{BASE}/imports",
        files={"file": (name, content, XLSX)},
        data={"dry_run": str(dry_run).lower(), **extra},
    )


EMPTY = [("IS", "interest_expense", "FY2008", 12), ("CF", "buybacks", "FY2008", 7)]


def test_every_route_requires_a_session(client: TestClient) -> None:
    for method, path in (
        ("get", f"{BASE}/import-template"),
        ("get", f"{BASE}/imports"),
        ("post", f"{BASE}/imports"),
        ("delete", f"{BASE}/imports/1"),
    ):
        assert getattr(client, method)(path).status_code == 401


def test_the_template_downloads_as_xlsx_with_a_file_name(aapl_client: TestClient) -> None:
    response = aapl_client.get(f"{BASE}/import-template", params={"format": "xlsx"})

    assert response.headers["content-type"] == XLSX
    assert "AAPL-import-template.xlsx" in response.headers["content-disposition"]
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Instructions", "IS", "BS", "CF"]


def test_the_csv_template_and_its_prefill(aapl_client: TestClient) -> None:
    blank = aapl_client.get(f"{BASE}/import-template", params={"format": "csv", "scale": "units"})
    prefilled = aapl_client.get(
        f"{BASE}/import-template", params={"format": "csv", "prefill": "true", "scale": "units"}
    )

    assert blank.headers["content-type"].startswith("text/csv")
    assert blank.text.splitlines()[:2] == ["scale,units", "fiscal_year_end,2025-09-27"]
    assert "391035000000" not in blank.text
    assert "391035000000" in prefilled.text  # AAPL FY2024 revenue, in units


def test_the_downloaded_template_has_the_fiscal_year_end_and_no_dates(
    aapl_client: TestClient,
) -> None:
    content = _template(aapl_client, format="xlsx")

    book = load_workbook(io.BytesIO(content), data_only=True)
    guide = {r[0]: r[1] for r in book["Instructions"].iter_rows(values_only=True) if r[0]}
    assert guide["fiscal_year_end"] == "2025-09-27"  # AAPL's latest completed fiscal year
    names = [r[0] for r in book["IS"].iter_rows(values_only=True)]
    assert names[:3] == ["fiscal_year", "fiscal_period", "code"]
    assert "period_start" not in names and "period_end" not in names


@pytest.mark.parametrize("params", [{"format": "pdf"}, {"scale": "tons"}, {"prefill": "maybe"}])
def test_a_bad_template_parameter_is_a_422(aapl_client: TestClient, params: dict[str, str]) -> None:
    assert aapl_client.get(f"{BASE}/import-template", params=params).status_code == 422


def test_the_template_of_an_unknown_company_is_a_404(authed_client: TestClient) -> None:
    assert authed_client.get("/api/v1/companies/NOPE/import-template").status_code == 404


def test_a_dry_run_reports_the_counts_and_stores_nothing(aapl_client: TestClient) -> None:
    content = _typed(aapl_client, [*EMPTY, ("IS", "revenue", "FY2024", 1)])

    response = _upload(aapl_client, content, dry_run=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "dry_run",
        "format",
        "scale",
        "import_id",
        "fills",
        "ignored",
        "unchanged",
        "warnings",
        "lines",
        "built",
    }
    assert (body["dry_run"], body["format"], body["scale"], body["import_id"]) == (
        True,
        "xlsx",
        "millions",
        None,
    )
    assert {(f["code"], f["period_key"]) for f in body["fills"]} == {
        ("interest_expense", "FY2008"),
        ("buybacks", "FY2008"),
    }
    assert set(body["fills"][0]) == {
        "statement",
        "code",
        "label",
        "unit",
        "period_key",
        "value",
        "previous",
    }
    (ignored,) = body["ignored"]
    assert (ignored["code"], ignored["reason"], ignored["imported_value"]) == (
        "revenue",
        "sec",
        "1000000",
    )
    assert set(ignored) == {
        "statement",
        "code",
        "label",
        "unit",
        "period_key",
        "existing_value",
        "imported_value",
        "reason",
    }
    assert body["unchanged"] > 1_000
    assert aapl_client.get(f"{BASE}/imports").json() == []


def test_confirming_imports_lists_and_shows_in_the_statements_then_delete_reverts(
    aapl_client: TestClient,
) -> None:
    content = _typed(aapl_client, EMPTY)

    response = _upload(aapl_client, content, dry_run=False)

    assert response.status_code == 200, response.text
    import_id = response.json()["import_id"]
    assert isinstance(import_id, int) and response.json()["dry_run"] is False
    (listed,) = aapl_client.get(f"{BASE}/imports").json()
    assert set(listed) == {"id", "filename", "format", "scale", "imported_at", "cells"}
    assert (listed["id"], listed["filename"], listed["cells"]) == (import_id, "aapl.xlsx", 2)
    statement = aapl_client.get(
        f"{BASE}/statements", params={"type": "IS", "freq": "annual"}
    ).json()
    row = next(r for r in statement["rows"] if r["code"] == "interest_expense")
    at = [p["key"] for p in statement["periods"]].index("FY2008")
    assert (row["values"][at], row["provenance"][at]) == ("12000000", "imported")

    assert aapl_client.delete(f"{BASE}/imports/{import_id}").status_code == 204

    assert aapl_client.get(f"{BASE}/imports").json() == []
    statement = aapl_client.get(
        f"{BASE}/statements", params={"type": "IS", "freq": "annual"}
    ).json()
    row = next(r for r in statement["rows"] if r["code"] == "interest_expense")
    assert row["values"][at] is None


def test_the_cell_details_of_an_imported_cell_name_the_import(aapl_client: TestClient) -> None:
    import_id = _upload(aapl_client, _typed(aapl_client, EMPTY), dry_run=False).json()["import_id"]

    cell = aapl_client.get(
        f"{BASE}/statements/cell",
        params={"code": "interest_expense", "fiscal_year": 2008, "fiscal_period": "FY"},
    ).json()

    assert cell["provenance"] == "imported"
    assert cell["filing"]["accession_no"] == f"import:{import_id}"
    assert [v["accession_no"] for v in cell["vintages"]] == [f"import:{import_id}"]


def test_a_file_that_fills_nothing_stores_nothing(aapl_client: TestClient) -> None:
    response = _upload(aapl_client, _template(aapl_client, format="xlsx", prefill="true"), False)

    assert response.status_code == 200
    assert response.json()["import_id"] is None and response.json()["unchanged"] > 1_000
    assert aapl_client.get(f"{BASE}/imports").json() == []


def test_a_parse_error_is_a_422_with_its_location(aapl_client: TestClient) -> None:
    content = _typed(aapl_client, [("IS", "interest_expense", "FY2008", "abc")])

    response = _upload(aapl_client, content, dry_run=False)

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail", "errors"}
    (error,) = body["errors"]
    assert set(error) == {"sheet", "row", "column", "message"}
    assert error["sheet"] == "IS" and "abc" in error["message"]
    assert aapl_client.get(f"{BASE}/imports").json() == []


def test_a_scale_form_field_stands_in_for_a_file_without_one(aapl_client: TestClient) -> None:
    csv = _template(aapl_client, format="csv", prefill="true", scale="units").decode()
    content = "\n".join(csv.splitlines()[1:]).encode()  # without its scale row

    missing = _upload(aapl_client, content, dry_run=True, name="a.csv")
    given = _upload(aapl_client, content, dry_run=True, name="a.csv", scale="units")

    assert missing.status_code == 422 and "scale" in missing.json()["errors"][0]["message"]
    assert given.status_code == 200 and given.json()["scale"] == "units"
    assert given.json()["fills"] == [] and given.json()["unchanged"] > 1_000


def test_an_unsupported_file_is_a_422(aapl_client: TestClient) -> None:
    response = _upload(aapl_client, b"%PDF", dry_run=True, name="aapl.pdf")

    assert response.status_code == 422


def test_deleting_an_unknown_import_is_a_404(aapl_client: TestClient) -> None:
    assert aapl_client.delete(f"{BASE}/imports/999").status_code == 404


def _with_breakdown(client: TestClient) -> bytes:
    book = load_workbook(io.BytesIO(_template(client, format="xlsx", prefill="true")))
    add_line(book, "IS", "interest_expense", "Notes", {"FY2008": 3})
    add_line(book, "IS", "interest_expense", "Loans", {"FY2008": 4})
    mark_complete(book, "IS", "interest_expense")
    return save(book)


def test_the_dry_run_reports_new_custom_lines_and_the_parents_they_build(
    aapl_client: TestClient,
) -> None:
    response = _upload(aapl_client, _with_breakdown(aapl_client), True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lines"] == [
        {
            "statement": "IS",
            "code": "custom:notes",
            "label": "Notes",
            "parent": "interest_expense",
            "parent_label": "Interest expense",
        },
        {
            "statement": "IS",
            "code": "custom:loans",
            "label": "Loans",
            "parent": "interest_expense",
            "parent_label": "Interest expense",
        },
    ]
    assert body["built"] == [
        {
            "statement": "IS",
            "code": "interest_expense",
            "label": "Interest expense",
            "unit": "USD",
            "period_key": "FY2008",
            "value": "7000000",
        }
    ]
    assert [c["code"] for c in body["fills"]] == ["custom:notes", "custom:loans"]


def test_a_confirmed_breakdown_shows_in_the_statement_payload(aapl_client: TestClient) -> None:
    assert _upload(aapl_client, _with_breakdown(aapl_client), False).status_code == 200

    rows = aapl_client.get(f"{BASE}/statements", params={"type": "IS", "freq": "annual"}).json()[
        "rows"
    ]

    by_code = {r["code"]: r for r in rows}
    assert (by_code["custom:notes"]["custom"], by_code["custom:notes"]["parent"]) == (
        True,
        "interest_expense",
    )
    assert by_code["custom:notes"]["depth"] == by_code["interest_expense"]["depth"] + 1
    assert by_code["other:interest_expense"]["label"] == "Other Interest expense"
    assert (by_code["revenue"]["custom"], by_code["revenue"]["parent"]) == (False, None)
    codes = [r["code"] for r in rows]
    at = codes.index("interest_expense")
    assert codes[at + 1 : at + 4] == ["custom:notes", "custom:loans", "other:interest_expense"]


def test_a_custom_line_error_is_a_422_with_its_location(aapl_client: TestClient) -> None:
    book = load_workbook(io.BytesIO(_template(aapl_client, format="xlsx")))
    add_line(book, "BS", "total_current_assets", "Cash like", {"FY2024": 1})

    response = _upload(aapl_client, save(book), True)

    assert response.status_code == 422
    (error,) = response.json()["errors"]
    assert (error["sheet"], error["column"]) == ("BS", "C") and "leaf" in error["message"]


def test_a_file_over_10_mb_is_a_422(aapl_client: TestClient) -> None:
    response = _upload(aapl_client, b"x" * (10 * 1024 * 1024 + 1), dry_run=True)

    assert response.status_code == 422
    assert "10 MB" in response.text


def test_the_upload_runs_in_the_threadpool_not_on_the_event_loop() -> None:
    """Parsing and solving a file takes seconds; a coroutine handler would block every request."""
    assert not inspect.iscoroutinefunction(import_statements)
