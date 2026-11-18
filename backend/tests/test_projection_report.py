"""`scripts/projection_report.py` (M7d S1, docs/erd/face-tree.md "Report"): it loads and prints;
the counting is `statements/projection_stats.py`, tested on its own."""

import hashlib
import importlib.util
from collections.abc import Callable, Generator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy.orm import Session

from bedrock.core.config import Settings
from bedrock.statements.projection import project_all
from bedrock.statements.projection_stats import tally
from tests.statements_pipeline import run_pipeline

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "projection_report.py"


@pytest.fixture(autouse=True)
def script_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """As for `coverage_report.py`: no developer `.env`, no developer data."""
    from bedrock.core.config import load_settings

    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "no-data"))
    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("projection_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aapl_report(script: ModuleType) -> dict[str, Any]:
    return script.report(script.fixture_companies(["AAPL"]))  # type: ignore[no-any-return]


def test_the_groups_are_those_the_counting_gives(aapl_report: dict[str, Any]) -> None:
    pipeline = run_pipeline("AAPL")
    assert pipeline.rules.filing_lines is not None
    stats = tally(project_all(pipeline.rules.filing_lines, pipeline.items))

    groups = aapl_report["groups"]

    assert set(groups) == {f"{g}/{s}" for g, s in stats}
    sheet = groups["10-K/BS"]
    assert (sheet["statements"], sheet["lines"]) == (
        stats[("10-K", "BS")].statements,
        stats[("10-K", "BS")].lines,
    )
    assert set(sheet["kinds"]) <= {"mapped", "other", "open"}
    assert aapl_report["companies"] == ["AAPL"]


def test_the_face_disagreements_are_counted_per_code(aapl_report: dict[str, Any]) -> None:
    disagreements = aapl_report["face_disagreements"]

    assert isinstance(disagreements, dict)
    assert all(isinstance(n, int) and n > 0 for n in disagreements.values())


def test_the_fixtures_print_the_tables(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--fixtures", "AAPL", "MSFT"]) == 0

    out = capsys.readouterr().out
    for heading in ("10-K", "10-Q", "Lines by kind", "Parent checks", "Face disagreements"):
        assert heading in out
    assert "AAPL" in out


def test_the_holdout_prints_totals_only(script: ModuleType, aapl_report: dict[str, Any]) -> None:
    text = script.render(aapl_report, totals_only=True)

    assert "AAPL" not in text
    assert "Face disagreements" in text


def test_one_source_is_required(script: ModuleType) -> None:
    assert script.main([]) == 2
    assert script.main(["--fixtures", "AAPL", "--holdout"]) == 2


def test_a_missing_database_is_an_error(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--db", str(tmp_path / "none.db")]) == 2
    assert "none.db" in capsys.readouterr().err


def test_a_database_is_read_from_a_copy_and_gives_the_fixture_numbers(
    script: ModuleType,
    seed_db: Callable[..., None],
    db_session: Session,
    settings: Settings,
    aapl_report: dict[str, Any],
) -> None:
    from bedrock.repositories import companies as companies_repo
    from tests.seed import read_recorded_filings

    seed_db("AAPL")
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    read_recorded_filings(db_session, company)
    db_session.close()
    path = Path(settings.resolved_database_url.removeprefix("sqlite:///"))
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    stored = script.report(script.db_companies(path))

    assert stored["groups"] == aapl_report["groups"]
    assert stored["face_disagreements"] == aapl_report["face_disagreements"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
