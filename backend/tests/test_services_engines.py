"""Engine choices of a scenario and the engine defaults they set (FR-FCST-07, -08, -11; docs/erd/
forecasting.md "Statistical engines (M6)" → Engine choice, Service), on the recorded AAPL
fixtures."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.forecast.history import default_drivers
from bedrock.forecast.interface import SeriesInput, annual_values
from bedrock.models.company import Company
from bedrock.models.driver_engine import DriverEngineChoice
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import engines as engines_repo
from bedrock.services import engines as engines_service
from bedrock.services import scenarios as scenarios_service
from bedrock.services.errors import InvalidEngineChoice, ScenarioNotFound
from bedrock.services.scenarios import driver_grid, get_engines, list_scenarios, put_engines

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
D = Decimal


@pytest.fixture
def aapl(seed_db: Callable[..., None], db_session: Session) -> Company:
    seed_db("AAPL")
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    return company


def _main_id(session: Session, company: Company) -> int:
    return list_scenarios(session, company, NOW)[0].id


def _row(grid: scenarios_service.DriverGrid, code: str) -> scenarios_service.GridRow:
    return next(r for r in grid.rows if r.code == code)


def _stored(session: Session, scenario_id: int) -> dict[str, str]:
    stmt = select(DriverEngineChoice).where(DriverEngineChoice.scenario_id == scenario_id)
    return {r.driver_code: r.engine_code for r in session.execute(stmt).scalars()}


def test_a_fresh_scenario_reads_auto_everywhere_in_catalog_order(
    db_session: Session, aapl: Company
) -> None:
    view = get_engines(db_session, aapl, _main_id(db_session, aapl))

    assert view.rows[0].driver_code == "revenue_growth"
    assert {r.engine for r in view.rows} == {"auto"}
    gross = next(r for r in view.rows if r.driver_code == "gross_margin")
    assert gross.seasonal is True
    assert gross.used in ("arima", "ets", "blend", "mean")
    growth = next(r for r in view.rows if r.driver_code == "revenue_growth")
    assert growth.seasonal is False


def test_put_stores_the_choice_and_every_case_shows_it(db_session: Session, aapl: Company) -> None:
    scenario_id = _main_id(db_session, aapl)

    view = put_engines(db_session, aapl, scenario_id, [("sga_pct_revenue", "ets")], NOW)

    assert next(r for r in view.rows if r.driver_code == "sga_pct_revenue").engine == "ets"
    assert _stored(db_session, scenario_id) == {"sga_pct_revenue": "ets"}
    for case in ("base", "bull", "bear"):
        row = _row(driver_grid(db_session, aapl, scenario_id, case), "sga_pct_revenue")
        assert row.engine == "ets"
        assert row.engine_used == "ets"
        assert set(row.sources) == {"engine"}


def test_bull_s_offset_sits_on_base_s_engine_value(db_session: Session, aapl: Company) -> None:
    scenario_id = _main_id(db_session, aapl)
    put_engines(db_session, aapl, scenario_id, [("gross_margin", "ets")], NOW)

    base = _row(driver_grid(db_session, aapl, scenario_id, "base"), "gross_margin")
    bull = _row(driver_grid(db_session, aapl, scenario_id, "bull"), "gross_margin")

    assert set(base.sources) == {"engine"}
    assert set(bull.sources) == {"offset"}
    assert [b - a for a, b in zip(base.values, bull.values, strict=True) if a and b] == [
        D("0.01")
    ] * len(base.values)


def test_put_auto_deletes_the_row(db_session: Session, aapl: Company) -> None:
    scenario_id = _main_id(db_session, aapl)
    put_engines(db_session, aapl, scenario_id, [("sga_pct_revenue", "ets")], NOW)

    view = put_engines(db_session, aapl, scenario_id, [("sga_pct_revenue", "auto")], NOW)

    assert _stored(db_session, scenario_id) == {}
    assert next(r for r in view.rows if r.driver_code == "sga_pct_revenue").engine == "auto"


def test_a_second_put_updates_the_row_and_leaves_the_others(
    db_session: Session, aapl: Company
) -> None:
    scenario_id = _main_id(db_session, aapl)
    put_engines(
        db_session, aapl, scenario_id, [("sga_pct_revenue", "ets"), ("tax_rate", "arima")], NOW
    )

    put_engines(db_session, aapl, scenario_id, [("sga_pct_revenue", "blend")], NOW)

    assert _stored(db_session, scenario_id) == {"sga_pct_revenue": "blend", "tax_rate": "arima"}


def test_mean_gives_the_m4_default_exactly(db_session: Session, aapl: Company) -> None:
    scenario_id = _main_id(db_session, aapl)
    put_engines(db_session, aapl, scenario_id, [("sga_pct_revenue", "mean")], NOW)
    scenario = scenarios_service.get_scenario(db_session, aapl, scenario_id)
    history = scenarios_service.load_history(db_session, aapl)
    expected = default_drivers(history, scenarios_service.settings_of(scenario))["sga_pct_revenue"]

    row = _row(driver_grid(db_session, aapl, scenario_id, "base"), "sga_pct_revenue")

    assert row.engine_used == "mean"
    assert set(row.values) == {expected}
    assert set(row.sources) == {"default"}


def test_stl_makes_the_quarterly_values_seasonal(db_session: Session, aapl: Company) -> None:
    scenario_id = _main_id(db_session, aapl)
    put_engines(db_session, aapl, scenario_id, [("gross_margin", "stl")], NOW)

    quarterly = driver_grid(db_session, aapl, scenario_id, "base", "quarterly")

    assert "seasonal" in _row(quarterly, "gross_margin").sources


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([("nope", "ets")], "nope is not a driver of the growth method"),
        ([("revenue_growth", "stl")], "STL applies to ratio and days drivers only: revenue_growth"),
        ([("tax_rate", "ets"), ("tax_rate", "mean")], "tax_rate is given twice"),
    ],
)
def test_put_refuses_a_rule_break_and_writes_nothing(
    db_session: Session, aapl: Company, rows: list[tuple[str, str]], message: str
) -> None:
    scenario_id = _main_id(db_session, aapl)

    with pytest.raises(InvalidEngineChoice, match=message):
        put_engines(db_session, aapl, scenario_id, [("gross_margin", "ets"), *rows], NOW)

    assert _stored(db_session, scenario_id) == {}


def test_put_refuses_an_unknown_engine(db_session: Session, aapl: Company) -> None:
    with pytest.raises(InvalidEngineChoice, match="prophet is not an engine"):
        put_engines(db_session, aapl, _main_id(db_session, aapl), [("tax_rate", "prophet")], NOW)


def test_an_unknown_scenario_is_not_found(db_session: Session, aapl: Company) -> None:
    with pytest.raises(ScenarioNotFound):
        get_engines(db_session, aapl, 999_999)


def test_a_stale_row_is_ignored_and_kept(db_session: Session, aapl: Company) -> None:
    scenario_id = _main_id(db_session, aapl)
    engines_repo.put(db_session, scenario_id, {"no_such_driver": "ets"}, NOW.replace(tzinfo=None))
    db_session.commit()

    view = get_engines(db_session, aapl, scenario_id)
    driver_grid(db_session, aapl, scenario_id, "base")

    assert "no_such_driver" not in {r.driver_code for r in view.rows}
    assert _stored(db_session, scenario_id) == {"no_such_driver": "ets"}


def test_a_second_grid_on_the_same_history_fits_nothing(db_session: Session, aapl: Company) -> None:
    scenario_id = _main_id(db_session, aapl)
    driver_grid(db_session, aapl, scenario_id, "base")

    misses = engines_service.fit_cache_info().misses
    driver_grid(db_session, aapl, scenario_id, "bull")
    get_engines(db_session, aapl, scenario_id)

    assert engines_service.fit_cache_info().misses == misses


def test_the_memo_is_keyed_on_the_series_values() -> None:
    engines_service.fit_cache_clear()
    a = SeriesInput(annual_values(2010, [1.0, 2.0, 1.5, 2.5, 2.0, 3.0, 2.5, 3.5]))
    b = SeriesInput(annual_values(2010, [1.0, 2.0, 1.5, 2.5, 2.0, 3.0, 2.5, 3.6]))

    first = engines_service.memo_fit("ets", a, 3)
    again = engines_service.memo_fit("ets", a, 3)
    engines_service.memo_fit("ets", b, 3)

    assert again is first
    assert engines_service.fit_cache_info().misses == 2
    assert engines_service.fit_cache_info().hits == 1
