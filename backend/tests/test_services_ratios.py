"""The ratios use-case and its one-load statement helper over a test database (FR-ANL-01..04)."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.ratios.calculator import RatioInputs, compute_ratios
from bedrock.ratios.caveats import load_caveats
from bedrock.ratios.registry import RATIOS
from bedrock.repositories import companies as companies_repo
from bedrock.services.ratios import ratios
from bedrock.services.statements import statement_tables
from bedrock.statements import build
from bedrock.statements.build import build_statement

from .seed import fake_sources, follow
from .statements_pipeline import run_pipeline

NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)
CODES = [r.code for r in RATIOS]


@pytest.fixture
def aapl_db(seed_db: Callable[..., None]) -> None:
    seed_db("AAPL")


@pytest.fixture
def aapl(aapl_db: None, db_session: Session) -> Company:
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    return company


# --- statement_tables ------------------------------------------------------------------------


def test_statement_tables_returns_every_requested_table_untrimmed(
    db_session: Session, aapl: Company
) -> None:
    wanted = [("IS", "annual"), ("BS", "quarterly"), ("CF", "ttm")]
    pipeline = run_pipeline("AAPL")

    tables = statement_tables(db_session, aapl, wanted)  # type: ignore[arg-type]

    assert list(tables) == wanted
    assert tables[("IS", "annual")] == pipeline.annual["IS"]  # untrimmed: same as the engine
    assert tables[("BS", "quarterly")] == pipeline.quarterly["BS"]
    assert tables[("CF", "ttm")].periods[-1].key.startswith("TTM-")
    assert all(table.statement == s and table.freq == f for (s, f), table in tables.items())


def test_statement_tables_uses_the_requested_common_size_base(
    db_session: Session, aapl: Company
) -> None:
    pipeline = run_pipeline("AAPL")
    expected = build_statement(
        pipeline.canonical, pipeline.items, "IS", "annual", "parent", rules=pipeline.rules
    )

    tables = statement_tables(db_session, aapl, [("IS", "annual")], common_size_base="parent")

    assert tables[("IS", "annual")] == expected


def test_statement_tables_of_a_company_without_facts_are_empty(db_session: Session) -> None:
    company = follow(db_session, fake_sources().edgar, "AAPL")

    tables = statement_tables(db_session, company, [("IS", "annual"), ("BS", "quarterly")])

    assert tables[("IS", "annual")].periods == [] and tables[("IS", "annual")].rows == []
    assert tables[("BS", "quarterly")].balance_check is None


def test_statement_tables_solves_the_cells_once_for_every_table(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = build.solve_cells

    def counting(*args, **kwargs):  # type: ignore[no-untyped-def]  # a spy on the real solver
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(build, "solve_cells", counting)
    wanted = [(s, f) for f in ("annual", "quarterly") for s in ("IS", "BS", "CF")]

    statement_tables(db_session, aapl, wanted, "normalized")  # type: ignore[arg-type]

    assert len(calls) == 1


def test_statement_tables_rejects_a_ttm_balance_sheet(db_session: Session, aapl: Company) -> None:
    with pytest.raises(ValueError, match="TTM"):
        statement_tables(db_session, aapl, [("IS", "annual"), ("BS", "ttm")])


# --- ratios ----------------------------------------------------------------------------------


def test_annual_ratios_match_the_calculator_over_the_engine_pipeline(
    db_session: Session, aapl: Company
) -> None:
    pipeline = run_pipeline("AAPL")
    expected = compute_ratios(
        RatioInputs(pipeline.annual["IS"], pipeline.annual["CF"], pipeline.annual["BS"]), "annual"
    )

    table = ratios(db_session, aapl, "annual", "reported")

    assert table == expected
    assert len(table.periods) >= 10


def test_ttm_ratios_read_quarterly_balance_and_income(db_session: Session, aapl: Company) -> None:
    table = ratios(db_session, aapl, "ttm", "reported")

    assert table.freq == "ttm"
    assert table.periods and all(p.key.startswith("TTM-") for p in table.periods)
    eps = next(r for r in table.rows if r.code == "eps_diluted")
    assert eps.values[-1] is not None and eps.values[-1] > 0
    roe = next(r for r in table.rows if r.code == "roe")  # averaged over the quarterly BS
    assert roe.values[-1] is not None


@pytest.mark.parametrize("freq", ["annual", "ttm"])
def test_a_company_without_facts_has_every_ratio_row_and_no_period(
    db_session: Session, freq: str
) -> None:
    company = follow(db_session, fake_sources().edgar, "AAPL")

    table = ratios(db_session, company, freq, "reported")  # type: ignore[arg-type]

    assert table.periods == []
    assert [r.code for r in table.rows] == CODES
    assert all(r.values == [] for r in table.rows)


def test_de_rows_carry_their_caveats_and_aapl_rows_none(db_session: Session) -> None:
    sources = fake_sources()
    de = follow(db_session, sources.edgar, "DE")
    aapl = follow(db_session, sources.edgar, "AAPL")
    expected = {code: c.text for c in load_caveats()["DE"] for code in c.codes}

    de_rows = ratios(db_session, de, "annual", "reported").rows
    aapl_rows = ratios(db_session, aapl, "annual", "reported").rows

    assert expected
    assert {r.code: r.caveat for r in de_rows} == {code: expected.get(code) for code in CODES}
    assert all(r.caveat is None for r in aapl_rows)
