"""The statement import routes over a followed AAPL (recorded fixtures, no network)."""

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from .import_data import filled, save

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
    assert blank.text.splitlines()[0] == "scale,units"
    assert "391035000000" not in blank.text
    assert "391035000000" in prefilled.text  # AAPL FY2024 revenue, in units


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
