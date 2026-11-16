"""`scripts/coverage_report.py`: coverage and the empty-cell buckets for a set of companies
(M7b S1, docs/erd/data-coverage.md)."""

import hashlib
import importlib.util
import json
from collections.abc import Callable, Generator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from bedrock.core.config import Settings
from bedrock.statements.coverage import table_coverage
from tests.statements_pipeline import run_pipeline

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "coverage_report.py"


@pytest.fixture(autouse=True)
def script_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """The script reads its settings from the environment (`load_settings`): give it the secret
    the settings require and an empty data directory, so the tests pass without the developer's
    `.env` (CI has none, G11) and never read the developer's data."""
    from bedrock.core.config import load_settings

    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "no-data"))
    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("coverage_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aapl_report(script: ModuleType) -> dict[str, object]:
    return script.report(script.fixture_companies(["AAPL"]))  # type: ignore[no-any-return]


def test_the_totals_are_those_table_coverage_gives(aapl_report: dict) -> None:  # type: ignore[type-arg]
    pipeline = run_pipeline("AAPL")
    mapped = set(pipeline.mappings["canonical_code"])
    warnings = pipeline.annual["IS"].rule_warnings
    for freq, tables in (("annual", pipeline.annual), ("quarterly", pipeline.quarterly)):
        for statement, table in tables.items():
            coverage = table_coverage(
                table, pipeline.items, mapped, warnings, annual=pipeline.annual[statement]
            )
            causes = coverage.empty_by_cause
            row = aapl_report["companies"]["AAPL"][f"{statement}/{freq}"]
            assert row["cells"] == coverage.cells
            assert row["filled"] == coverage.filled
            assert row["strict_cells"] == coverage.cells - causes["no_filing_data"]
            assert row["applicable_cells"] == (
                row["strict_cells"] - causes["not_applicable"] - causes["included_in"]
            )
            assert Decimal(row["strict"]) == coverage.fraction
            assert Decimal(row["applicable"]) == coverage.fraction_applicable
            assert sum(row["buckets"].values()) == coverage.cells - coverage.filled
            # M7b S7: what the structure rules did, per table
            assert row["zero_inferred"] == coverage.by_provenance["zero_inferred"]
            assert row["derived"] == coverage.by_provenance["derived"]
            assert row["extension_unclassified"] == causes["extension_unclassified"]


def test_the_total_of_one_company_is_its_own_numbers(aapl_report: dict) -> None:  # type: ignore[type-arg]
    company = aapl_report["companies"]["AAPL"]
    for freq in ("annual", "quarterly"):
        rows = [company[f"{s}/{freq}"] for s in ("IS", "BS", "CF")]
        total = aapl_report["totals"][freq]
        assert total["filled"] == sum(r["filled"] for r in rows)
        for cells, ratio in (("strict_cells", "strict"), ("applicable_cells", "applicable")):
            assert total[cells] == sum(r[cells] for r in rows)
            assert Decimal(total[ratio]) == (
                Decimal(total["filled"]) / Decimal(total[cells])
            ).quantize(Decimal("0.000001"))


def test_the_rendered_totals_show_strict_and_applicable_coverage(
    script: ModuleType,
    aapl_report: dict,  # type: ignore[type-arg]
) -> None:
    text = script.render(aapl_report, totals_only=True)

    for freq in ("annual", "quarterly"):
        total = aapl_report["totals"][freq]
        line = next(x for x in text.splitlines() if x.startswith(f"Total {freq}:"))
        assert f"strict {Decimal(total['strict']) * 100:.1f}%" in line
        assert f"applicable {Decimal(total['applicable']) * 100:.1f}%" in line
    assert "not_applicable" in text  # the bucket shares list the new bucket


def test_the_top_lines_name_their_companies_and_leave_out_statements_not_presented(
    aapl_report: dict,  # type: ignore[type-arg]
) -> None:
    top = aapl_report["top_lines"]
    assert 0 < len(top) <= 40
    assert all(line["companies"] == {"AAPL": line["empty"]} for line in top)
    assert [line["empty"] for line in top] == sorted((line["empty"] for line in top), reverse=True)
    total = sum(
        n
        for key, row in aapl_report["companies"]["AAPL"].items()
        if key.endswith("/annual")
        for bucket, n in row["buckets"].items()
        if bucket not in ("statement_not_presented", "not_applicable", "included_in")
    )
    assert sum(line["empty"] for line in top) <= total


def test_main_prints_each_company_and_the_total(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--fixtures", "AAPL", "MSFT"]) == 0

    out = capsys.readouterr().out
    assert "AAPL" in out and "MSFT" in out and "Total" in out
    assert "candidate_exists" in out and "Top empty lines" in out


def test_json_round_trips(script: ModuleType, tmp_path: Path, aapl_report: dict) -> None:  # type: ignore[type-arg]
    out = tmp_path / "report.json"

    assert script.main(["--fixtures", "AAPL", "--json", str(out)]) == 0

    assert json.loads(out.read_text()) == json.loads(json.dumps(aapl_report))
    assert json.loads(out.read_text())["companies"]["AAPL"] == aapl_report["companies"]["AAPL"]


def test_without_a_source_the_usage_is_printed(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main([]) == 2
    assert "--fixtures" in capsys.readouterr().out


def test_evidence_lists_each_candidate_concept_by_year_with_its_us_gaap_text(
    script: ModuleType,
) -> None:
    rows = script.evidence(script.fixture_companies(["AAPL"]), "sga")

    mapped = [r for r in rows if r["concept"] == "SellingGeneralAndAdministrativeExpense"]
    assert mapped and all(r["mapped"] for r in mapped)
    assert len({r["fiscal_year"] for r in mapped}) >= 5
    assert all(r["ticker"] == "AAPL" and r["label"] and r["description"] for r in mapped)
    assert all(Decimal(r["value"]) > 0 for r in mapped)
    years = [(r["concept"], r["fiscal_year"]) for r in rows]
    assert len(years) == len(set(years))  # one row per concept and year: the latest vintage
    # the candidate index adds unmapped concepts (Apple's SG&A has none left since M7b S3 made
    # `SellingAndMarketingExpense + GeneralAndAdministrativeExpense` a default)
    interest = script.evidence(script.fixture_companies(["AAPL"]), "interest_expense")
    assert "InterestExpenseDebt" in {r["concept"] for r in interest if not r["mapped"]}


def test_evidence_of_an_unknown_code_is_an_error(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--fixtures", "AAPL", "--evidence", "no_such_line"]) == 2
    assert "no_such_line" in capsys.readouterr().err


def test_the_sweep_lists_unmapped_10k_concepts_and_residual_shares(script: ModuleType) -> None:
    entries = script.fixture_companies(["AAPL", "MSFT"])

    result = script.sweep(entries)

    mapped = {
        e.ticker: set(
            zip(e.coverage.mappings["taxonomy"], e.coverage.mappings["concept"], strict=True)
        )
        for e in entries
    }
    concepts = result["concepts"]
    assert concepts  # a concept counts for a company that does not map it
    assert all(
        ("us-gaap", row["concept"]) not in mapped[ticker]
        for row in concepts
        for ticker in row["shares"]
    )
    assert all(1 <= row["companies"] <= 2 for row in concepts)
    assert all(set(row["shares"]) <= {"AAPL", "MSFT"} for row in concepts)
    assert all(row["anchor"] in {"revenue", "total_assets"} for row in concepts)
    assert all(Decimal(row["median_share"]) >= 0 for row in concepts)
    residuals = {row["code"]: row for row in result["residuals"]}
    assert {"other_operating_expenses", "other_current_assets"} <= set(residuals)
    assert residuals["other_current_assets"]["parent"] == "total_current_assets"
    assert set(result["values"]) == {"AAPL", "MSFT"}
    assert "revenue" in result["values"]["AAPL"]


def test_a_database_is_read_from_a_copy_and_gives_the_fixture_numbers(
    script: ModuleType,
    seed_db: Callable[..., None],
    db_session: Session,
    settings: Settings,
    aapl_report: dict,  # type: ignore[type-arg]
) -> None:
    from bedrock.repositories import companies as companies_repo
    from tests.seed import read_recorded_filings

    seed_db("AAPL")
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    read_recorded_filings(db_session, company)  # as the fixture pipeline does (M7b S7)
    db_session.close()
    path = Path(settings.resolved_database_url.removeprefix("sqlite:///"))
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    stored = script.report(script.db_companies(path, settings.data_dir))

    assert stored["companies"]["AAPL"] == aapl_report["companies"]["AAPL"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_a_missing_database_is_an_error(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--db", str(tmp_path / "none.db")]) == 2
    assert "none.db" in capsys.readouterr().err


def test_the_sweep_leaves_out_concepts_of_other_taxonomies(script: ModuleType) -> None:
    (entry,) = script.fixture_companies(["AAPL"])
    tenk = entry.coverage.latest_10k
    year_end = script._latest_year(entry.coverage)[0]
    extra = tenk.iloc[[0]].assign(
        taxonomy="dei",
        concept="EntityPublicFloat",
        unit="USD",
        period_start=None,
        period_end=year_end,
        value=Decimal(10**12),
    )
    padded = replace(entry, coverage=replace(entry.coverage, latest_10k=pd.concat([tenk, extra])))

    concepts = {row["concept"] for row in script.sweep([padded])["concepts"]}

    assert "EntityPublicFloat" not in concepts
    assert concepts  # the us-gaap ones are still there


def test_evidence_and_sweep_together_are_rejected(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--fixtures", "AAPL", "--evidence", "sga", "--sweep"]) == 2
    assert "--evidence" in capsys.readouterr().err


def test_totals_only_prints_no_company_and_no_line(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--fixtures", "AAPL", "--totals-only"]) == 0

    out = capsys.readouterr().out
    assert "Total annual" in out and "candidate_exists" in out
    assert "AAPL" not in out and "Top empty lines" not in out and "goodwill" not in out


def test_evidence_is_refused_on_the_holdout(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--holdout", "--evidence", "sga"]) == 2
    assert "holdout" in capsys.readouterr().err


def test_the_holdout_json_has_totals_only(
    script: ModuleType,
    seed_db: Callable[..., None],
    db_session: Session,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_db("AAPL")
    db_session.close()
    holdout = tmp_path / "data"
    holdout.mkdir()
    path = Path(settings.resolved_database_url.removeprefix("sqlite:///"))
    (holdout / "holdout.db").write_bytes(path.read_bytes())
    monkeypatch.setenv("DATA_DIR", str(holdout))
    out = tmp_path / "h.json"

    assert script.main(["--holdout", "--json", str(out)]) == 0

    assert set(json.loads(out.read_text())) == {"totals"}
